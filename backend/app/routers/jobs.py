from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import audit, current_user
from ..models import (Application, AutomationSettings, CoverLetter, Job, JobMatch, JobSourceListing, JobStatus, Resume,
                      ResumeVersion, User, as_dict)
from ..services import applications as appsvc
from ..services import versions

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
def list_jobs(q: str | None = None, qualified: bool | None = True, min_score: float | None = None, status: str | None = None,
              source: str | None = None, remote: str | None = None, new_since_hours: int | None = None,
              sort: str = "score", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    from datetime import timedelta

    from ..db import utcnow
    # one row per job: the user's most recent match
    latest = select(func.max(JobMatch.id)).where(JobMatch.user_id == user.id).group_by(JobMatch.job_id)
    stmt = select(Job, JobMatch).join(JobMatch, JobMatch.job_id == Job.id).where(JobMatch.id.in_(latest))
    if qualified is not None:
        stmt = stmt.where(JobMatch.qualified.is_(qualified))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Job.title).like(like), func.lower(Job.company_name).like(like)))
    if min_score is not None:
        stmt = stmt.where(JobMatch.match_score >= min_score)
    if remote:
        stmt = stmt.where(Job.remote_status == remote)
    if source:
        stmt = stmt.where(Job.id.in_(select(JobSourceListing.job_id).where(JobSourceListing.source_name == source)))
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
    rv = versions.generate_for_job(db, resume, job)
    auto = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user.id))
    want_cl = body.cover_letter if body.cover_letter is not None else bool(auto and auto.cover_letters_enabled)
    cl = versions.make_cover_letter(db, user.id, resume, job, rv.analysis.get("matched_skills", [])) if want_cl else None
    app, created = appsvc.prepare_application(db, user, job, rv, cl, actor="user")
    audit(db, user.id, "application_prepared", "application", app.id)
    db.commit()
    return {"created": created, "application": as_dict(app), "resume_version": as_dict(rv, "docx_file_key", "pdf_file_key")}
