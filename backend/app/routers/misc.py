from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import connectors
from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import audit, current_user
from ..services import llm
from ..models import (Application, ApplicationEvent, AutomationSettings, DailyReport, Integration, Job, JobMatch,
                      JobStatus, Notification, SearchProfile, SearchRun, User, as_dict)

router = APIRouter(prefix="/api", tags=["misc"])
S = JobStatus


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    uid, day = user.id, utcnow() - timedelta(hours=24)
    cnt = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    matches = select(func.count(func.distinct(JobMatch.job_id))).where(JobMatch.user_id == uid)
    apps = lambda *st: cnt(select(func.count(Application.id)).where(Application.user_id == uid, Application.status.in_(st)))  # noqa: E731
    last_ok = db.scalar(select(SearchRun.completed_at).where(SearchRun.user_id == uid, SearchRun.status.in_(("completed", "partial")))
                        .order_by(SearchRun.completed_at.desc()).limit(1))
    auto = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == uid))
    nxt = None
    if auto and not auto.paused:
        for sp in db.scalars(select(SearchProfile).where(SearchProfile.user_id == uid, SearchProfile.active.is_(True))):
            last = db.scalar(select(SearchRun.started_at).where(SearchRun.search_profile_id == sp.id).order_by(SearchRun.started_at.desc()).limit(1))
            t = (last + timedelta(hours=auto.run_interval_hours)) if last else utcnow()
            nxt = t if nxt is None or t < nxt else nxt
    recent = db.execute(select(ApplicationEvent, Application, Job).join(Application, Application.id == ApplicationEvent.application_id)
                        .join(Job, Job.id == Application.job_id).where(Application.user_id == uid)
                        .order_by(ApplicationEvent.id.desc()).limit(10)).all()
    return {
        "total_jobs_discovered": cnt(matches),
        "new_jobs_24h": cnt(matches.where(JobMatch.evaluated_at >= day, JobMatch.first_run_id.is_not(None)).join(Job, Job.id == JobMatch.job_id).where(Job.first_discovered_at >= day)),
        "matching_jobs": cnt(matches.where(JobMatch.qualified.is_(True))),
        "ready_for_review_or_apply": apps(S.AWAITING_APPROVAL, S.RESUME_READY, S.READY),
        "applications_submitted": apps(S.SUBMITTED, S.INTERVIEW, S.OFFER, S.REJECTED),
        "manual_action_required": apps(S.MANUAL, S.CONFIRMATION_PENDING, S.FAILED),
        "interviews": apps(S.INTERVIEW),
        "search_runs_completed": cnt(select(func.count(SearchRun.id)).where(SearchRun.user_id == uid, SearchRun.status.in_(("completed", "partial")))),
        "last_successful_run": last_ok, "next_scheduled_search": nxt, "automation_paused": bool(auto and auto.paused),
        "recent_activity": [{"event": e.event_type, "status": e.new_status, "at": e.event_timestamp, "company": j.company_name,
                             "title": j.title, "application_id": a.id, "actor": e.actor_type} for e, a, j in recent],
    }


@router.get("/reports/daily")
def reports(limit: int = 14, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(DailyReport).where(DailyReport.user_id == user.id).order_by(DailyReport.id.desc()).limit(min(limit, 90))).all()
    return [{"id": r.id, "created_at": r.created_at, **r.data} for r in rows]


@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return [as_dict(n) for n in db.scalars(stmt.order_by(Notification.id.desc()).limit(min(limit, 200)))]


@router.post("/notifications/{nid}/read")
def mark_read(nid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return as_dict(n)


@router.get("/integrations")
def integrations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    return {"sources": [{"name": n, "display_name": c.display_name, "requires_credentials": c.requires_credentials,
                         "compliance_note": c.compliance_note} for n, c in connectors.REGISTRY.items()],
            "submitters": [{"name": "sandbox", "active": s.sandbox_mode, "note": "Test double. Never contacts employers."}],
            "linkedin": {"mode": "user-provided paste/export only", "note": "No scraping or unauthorized access."},
            "ai_provider": {"name": s.llm_provider if llm.provider_configured() else "rules", "model": s.ai_model if llm.provider_configured() else None,
                            "note": ("Claude via the Anthropic API, only for users who opt in (Automation Settings)." if llm.provider_configured()
                                     else "No AI provider configured: deterministic, local rules only; nothing leaves this server.")},
            "configured": [as_dict(i) for i in db.scalars(select(Integration).where(Integration.user_id == user.id))]}


MODES = ("discovery_only", "prepare_for_review", "fill_and_request_approval", "auto_submit_authorized")


class AutomationPatch(BaseModel):
    mode: str | None = Field(None, pattern="^(discovery_only|prepare_for_review|fill_and_request_approval|auto_submit_authorized)$")
    paused: bool | None = None
    cover_letters_enabled: bool | None = None
    auto_prepare_min_score: float | None = Field(None, ge=0, le=100)
    run_interval_hours: int | None = Field(None, ge=1, le=24 * 7)
    email_notifications: bool | None = None
    report_hour_local: int | None = Field(None, ge=0, le=23)
    data_retention_days: int | None = Field(None, ge=30, le=3650)
    consent_to_auto_submit: bool | None = None  # explicit, required for auto_submit_authorized
    ai_enabled: bool | None = None              # opt in to sending resume facts + job text to the AI provider


def _auto(db: Session, user: User) -> AutomationSettings:
    a = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user.id))
    if not a:
        a = AutomationSettings(user_id=user.id)
        db.add(a)
        db.flush()
    return a


AI_DISCLOSURE = ("When enabled, JobPilot sends to the AI provider (Anthropic): the text of each job posting being evaluated, and your "
                 "documented career facts (skills, job titles, employers, dates, bullet points, education, certifications). It does NOT "
                 "send your name, email, phone, address or links. Providers may retain API data per their own policy. Turn this off at any time.")


def _auto_out(a: AutomationSettings) -> dict:
    s = get_settings()
    return as_dict(a) | {"sandbox_mode": s.sandbox_mode, "ai_available": llm.provider_configured(),
                         "ai_model": s.ai_model if llm.provider_configured() else None, "ai_disclosure": AI_DISCLOSURE}


@router.get("/automation-settings")
def get_auto(user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _auto(db, user)
    db.commit()
    return _auto_out(a)


@router.patch("/automation-settings")
def patch_auto(body: AutomationPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _auto(db, user)
    d = body.model_dump(exclude_unset=True)
    consent = d.pop("consent_to_auto_submit", None)
    if d.get("ai_enabled") and not llm.provider_configured():
        raise HTTPException(422, "No AI provider is configured on this server (set LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY).")
    if "ai_enabled" in d:
        a.ai_consent_at = utcnow() if d["ai_enabled"] and not a.ai_enabled else (a.ai_consent_at if d["ai_enabled"] else None)
    if d.get("mode") == "auto_submit_authorized" and not (consent or a.auto_submit_consent_at):
        raise HTTPException(422, "Automatic submission requires explicit consent (consent_to_auto_submit=true). "
                                 "It never covers legal attestations, demographic questions, salary or eligibility statements.")
    if consent:
        a.auto_submit_consent_at = utcnow()
    if d.get("mode") and d["mode"] != "auto_submit_authorized":
        a.auto_submit_consent_at = None  # leaving auto mode revokes consent
    for k, v in d.items():
        setattr(a, k, v)
    audit(db, user.id, "automation_settings_changed", "automation", a.id, mode=a.mode, paused=a.paused, ai_enabled=a.ai_enabled)
    db.commit()
    return _auto_out(a)
