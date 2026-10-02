import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import audit, current_user
from ..models import (Application, AutomationSettings, CoverLetter, Job, JobMatch, JobSourceListing, JobStatus, Resume,
                      ResumeVersion, User, as_dict)
from ..services import applications as appsvc
from ..services import versions
from ..services.llm import llm_for_user

router = APIRouter(prefix="/api", tags=["jobs"])


def user_job(db: Session, user: User, job_id: int) -> tuple[Job, JobMatch]:
    """A job is visible only if it matched one of the user's own search profiles."""
    job = db.get(Job, job_id)
    m = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job_id)
                  .order_by(JobMatch.id.desc()))
    if not job or not m:
        raise HTTPException(404, "Job not found")
    return job, m


def _job_row(j: Job, m: JobMatch, app: Application | None, sources: list[str]) -> dict:
    return {"id": j.id, "title": j.title, "company": j.company_name, "location": j.location, "remote_status": j.remote_status,
            "employment_type": j.employment_type, "salary": j.salary_information,
            "posted_at": j.posted_at, "posted_at_reliable": j.posted_at_reliable, "first_discovered_at": j.first_discovered_at,
            "status": j.status, "needs_dedup_review": j.needs_dedup_review, "sources": sources,
            "match_score": m.match_score, "qualified": m.qualified, "exclusion_reasons": m.exclusion_reasons,
            "workflow_status": app.status if app else m.workflow_status, "application_id": app.id if app else None}


@router.get("/jobs")
def list_jobs(q: str | None = None, qualified: str = Query("true", pattern="(?i)^(true|false|all)$"), min_score: float | None = None, status: str | None = None,
              source: str | None = None, remote: str | None = None, new_since_hours: int | None = None,
              sort: str = "score", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    from datetime import timedelta

    from ..db import utcnow
    # one row per job: the user's most recent match
    latest = select(func.max(JobMatch.id)).where(JobMatch.user_id == user.id).group_by(JobMatch.job_id)
    stmt = select(Job, JobMatch).join(JobMatch, JobMatch.job_id == Job.id).where(JobMatch.id.in_(latest))
    if qualified.lower() != "all":
        stmt = stmt.where(JobMatch.qualified.is_(qualified.lower() == "true"))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Job.title).like(like), func.lower(Job.company_name).like(like)))
    if min_score is not None:
        stmt = stmt.where(JobMatch.match_score >= min_score)
    if remote:
        stmt = stmt.where(Job.remote_status == remote)
    if source:
        stmt = stmt.where(Job.id.in_(select(JobSourceListing.job_id).where(
            or_(JobSourceListing.source_name == source, JobSourceListing.source_name.like(source + ":%")))))
    if new_since_hours:
        stmt = stmt.where(Job.first_discovered_at >= utcnow() - timedelta(hours=new_since_hours))
    if status:
        stmt = stmt.outerjoin(Application, (Application.job_id == Job.id) & (Application.user_id == user.id)).where(
            func.coalesce(Application.status, JobMatch.workflow_status) == status)
    order = {"score": JobMatch.match_score.desc(), "posted": Job.posted_at.desc(), "discovered": Job.first_discovered_at.desc()}.get(sort, JobMatch.match_score.desc())
    stmt = stmt.order_by(order, Job.id.desc())
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    items = []
    for j, m in rows:
        app = appsvc.get_application(db, user.id, j.id)
        items.append(_job_row(j, m, app, sorted({l.source_name for l in j.listings})))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _next_action(job: Job, m: JobMatch, app: Application | None) -> str:
    S = JobStatus
    if job.status != "open":
        return "This listing appears closed; no action possible."
    if not app:
        return "Review the match, then prepare an application." if m.qualified else "Does not meet your criteria; review the exclusion reasons."
    return {S.RESUME_READY: "Fix the factual-validation errors in the resume, then approve.",
            S.AWAITING_APPROVAL: "Review the tailored resume and approve it.",
            S.READY: "Approved. Submit the application.",
            S.MANUAL: "Apply on the employer's site using the prepared package, then mark it submitted.",
            S.IN_PROGRESS: "Submission in progress.",
            S.CONFIRMATION_PENDING: "Verify with the employer whether the application was received.",
            S.FAILED: "Submission failed. You can retry or apply manually.",
            S.SUBMITTED: "Submitted. Track follow-ups and interview status."}.get(app.status, "No action required.")


@router.get("/jobs/{job_id}")
def get_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job, m = user_job(db, user, job_id)
    app = appsvc.get_application(db, user.id, job_id)
    vers = db.scalars(select(ResumeVersion).join(Resume, Resume.id == ResumeVersion.resume_id).where(
        Resume.user_id == user.id, ResumeVersion.job_id == job_id).order_by(ResumeVersion.id.desc())).all()
    best = next((v for v in vers if v.validation_results.get("passed")), None)
    d = as_dict(job)
    d["listings"] = [as_dict(l) for l in job.listings]
    d["match"] = as_dict(m)
    d["application"] = as_dict(app) if app else None
    d["resume_versions"] = [as_dict(v, "docx_file_key", "pdf_file_key") for v in vers]
    d["recommended_resume_version_id"] = best.id if best else None
    d["application_method"] = ("authorized integration (sandbox)" if appsvc.submitter_for(job) else "manual (no authorized integration)")
    d["next_action"] = _next_action(job, m, app)
    return d


@router.get("/jobs/{job_id}/match")
def get_match(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job, m = user_job(db, user, job_id)
    vers = db.scalars(select(ResumeVersion).join(Resume, Resume.id == ResumeVersion.resume_id).where(
        Resume.user_id == user.id, ResumeVersion.job_id == job_id).order_by(ResumeVersion.id.desc())).first()
    return {"job_id": job_id, "score": m.match_score, "qualified": m.qualified, "factors": m.matching_factors,
            "exclusions": m.exclusion_reasons, "resume_analysis": vers.analysis if vers else None}


class PrepareIn(BaseModel):
    resume_id: int | None = None
    cover_letter: bool | None = None


@router.post("/jobs/{job_id}/prepare-application")
def prepare(job_id: int, body: PrepareIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    body = body or PrepareIn()
    job, m = user_job(db, user, job_id)
    if job.status != "open":
        raise HTTPException(409, "The listing is closed")
    existing = appsvc.get_application(db, user.id, job.id)
    if existing:
        return {"created": False, "application": as_dict(existing), "detail": "An application already exists for this job."}
    resume = db.get(Resume, body.resume_id) if body.resume_id else db.scalar(
        select(Resume).where(Resume.user_id == user.id, Resume.processing_status == "parsed")
        .order_by(Resume.is_primary.desc(), Resume.uploaded_at.desc()))
    if not resume or resume.user_id != user.id or resume.processing_status != "parsed":
        raise HTTPException(422, "Upload and parse a resume first")
    rv = versions.generate_for_job(db, resume, job, llm_for_user(db, user.id))
    auto = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user.id))
    want_cl = body.cover_letter if body.cover_letter is not None else bool(auto and auto.cover_letters_enabled)
    cl = versions.make_cover_letter(db, user.id, resume, job, rv.analysis.get("matched_skills", [])) if want_cl else None
    app, created = appsvc.prepare_application(db, user, job, rv, cl, actor="user")
    audit(db, user.id, "application_prepared", "application", app.id)
    db.commit()
    return {"created": created, "application": as_dict(app), "resume_version": as_dict(rv, "docx_file_key", "pdf_file_key")}


# ---------------- manual import (for sites we may not access automatically) ----------------
class ImportIn(BaseModel):
    site: str = Field("other", max_length=40)          # linkedin | indeed | jobs.ch | jobup.ch | ... (a label only)
    url: str | None = Field(None, max_length=1000)
    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=1, max_length=300)
    location: str | None = Field(None, max_length=300)
    description: str = Field(min_length=20, max_length=60000)   # text the user pasted from the posting
    employment_type: str | None = None
    remote_status: str | None = Field(None, pattern="^(remote|hybrid|onsite)$")
    posted_at: datetime | None = None
    search_profile_id: int | None = None

    @field_validator("url")
    @classmethod
    def http_only(cls, v):
        if v and not re.match(r"^https?://[^\s]+$", v.strip(), re.I):
            raise ValueError("URL must start with http:// or https://")
        return v.strip() if v else v


@router.post("/jobs/import", status_code=201)
def import_job(body: ImportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Add a job you found yourself (LinkedIn, Indeed, jobs.ch, a friend's email...). Nothing is fetched from the URL:
    the pasted text is the source, so no site's access rules are touched."""
    from ..connectors.base import RawListing
    from ..models import SearchProfile
    from ..services import ai_match, engine, matching
    from ..services.ingest import upsert_listing
    from ..services.textutil import html_to_text, sha

    sp = db.get(SearchProfile, body.search_profile_id) if body.search_profile_id else db.scalar(
        select(SearchProfile).where(SearchProfile.user_id == user.id, SearchProfile.active.is_(True)).order_by(SearchProfile.id))
    if not sp or sp.user_id != user.id:
        raise HTTPException(422, "Create a search profile first (Job Search Preferences); imported jobs are matched against it.")
    if body.employment_type and body.employment_type not in {"permanent", "part_time", "fixed_term", "temporary", "freelance", "contract_to_hire", "internship"}:
        raise HTTPException(422, "Unknown employment type")
    site = re.sub(r"[^a-z0-9.\-]", "", body.site.lower()) or "other"
    desc = html_to_text(body.description) if "<" in body.description else body.description.strip()  # never keep markup
    ident = (body.url or "").strip() or f"{body.title}|{body.company}|{body.location or ''}"
    raw = RawListing(source_name=f"manual:{site}", board=str(user.id), source_job_id=sha(str(user.id), ident)[:40], title=body.title.strip(),
                     company=body.company.strip(), description=desc, location=body.location, remote_status=body.remote_status or "unknown",
                     employment_type=body.employment_type, posted_at=body.posted_at, posted_at_reliable=body.posted_at is not None,
                     source_url=body.url or "", application_url=body.url,
                     metadata={"imported_by_user": True, "site": site})
    with db.begin_nested():
        up = upsert_listing(db, raw)
        resume = engine.pick_resume(db, sp)
        structured = resume.structured_profile if resume else None
        mr = matching.evaluate(up.job, sp, structured)
        m = db.scalar(select(JobMatch).where(JobMatch.search_profile_id == sp.id, JobMatch.job_id == up.job.id))
        created = m is None
        if created:
            m = JobMatch(user_id=user.id, search_profile_id=sp.id, job_id=up.job.id, workflow_status=JobStatus.NEW)
            db.add(m)
        m.rules_score = mr.score
        client = llm_for_user(db, user.id) if resume and structured else None
        if client is not None:
            try:
                r = client.fit(ai_match.facts_for_ai(structured), up.job.title, up.job.company_name, up.job.description)
                m.ai_analysis = {"key": ai_match.ai_key(ai_match.facts_hash(structured), up.job), "fit_score": r.fit_score,
                                 "matched": r.matched, "gaps": r.gaps, "reasoning": r.reasoning, "model": client.model}
                ai_match.apply_ai(mr, m.ai_analysis, sp)
            except Exception:  # noqa: BLE001 - AI is optional; keep the rules-based result
                pass
        mr.factors.append({"name": "manual_import", "kind": "soft", "detail": f"Added by you from {body.site}; shown even if below your minimum score."})
        m.match_score, m.matching_factors, m.exclusion_reasons = mr.score, mr.factors, mr.exclusions
        m.qualified = True  # you chose this job explicitly; reasons it would normally be filtered stay visible on the job page
        m.evaluated_at = utcnow()
    audit(db, user.id, "job_imported", "job", up.job.id, site=site)
    db.commit()
    return {"job_id": up.job.id, "created": created and up.created_job, "match_score": m.match_score,
            "would_normally_be_excluded": [e["code"] for e in mr.exclusions]}