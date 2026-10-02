import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import audit, current_user
from ..models import (Application, ApplicationEvent, AuditEvent, CoverLetter, Job, JobMatch, ResumeVersion, User, as_dict)
from ..services import applications as appsvc
from .resumes import owned_version

router = APIRouter(prefix="/api", tags=["applications"])


def owned_app(db: Session, user: User, aid: int) -> Application:
    a = db.get(Application, aid)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Application not found")
    return a


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except appsvc.ApplicationError as e:
        raise HTTPException(e.status, {"code": e.code, "message": e.message})


def _row(db: Session, a: Application) -> dict:
    j = db.get(Job, a.job_id)
    m = db.scalar(select(JobMatch).where(JobMatch.user_id == a.user_id, JobMatch.job_id == a.job_id).order_by(JobMatch.match_score.desc()))
    rv = db.get(ResumeVersion, a.resume_version_id) if a.resume_version_id else None
    cl = db.get(CoverLetter, a.cover_letter_version_id) if a.cover_letter_version_id else None
    l = j.listings[0] if j.listings else None
    return {"id": a.id, "job_id": j.id, "company": j.company_name, "job_title": j.title, "location": j.location,
            "employment_type": j.employment_type, "salary": j.salary_information, "date_posted": j.posted_at,
            "date_discovered": j.first_discovered_at, "date_prepared": a.created_at, "date_applied": a.submission_timestamp,
            "status": a.status, "job_match": m.match_score if m else None, "source": l.source_name if l else None,
            "job_url": l.source_url if l else None, "application_url": a.application_url,
            "resume_version": f"v{rv.version_number} (#{rv.id})" if rv else None, "resume_version_id": a.resume_version_id,
            "cover_letter_version": f"v{cl.version_number}" if cl else None,
            "submission_method": a.submission_method, "external_reference": a.external_reference,
            "notes": a.notes, "follow_up_date": a.follow_up_date, "manual_reason": a.manual_reason}


def _query(user: User, q, status):
    stmt = select(Application).join(Job, Job.id == Application.job_id).where(Application.user_id == user.id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Job.title).like(like), func.lower(Job.company_name).like(like), func.lower(func.coalesce(Application.notes, "")).like(like)))
    if status:
        stmt = stmt.where(Application.status.in_(status.split(",")))
    return stmt


@router.get("/applications")
def list_applications(q: str | None = None, status: str | None = None, page: int = Query(1, ge=1),
                      page_size: int = Query(25, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = _query(user, q, status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Application.updated_at.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [_row(db, a) for a in rows], "total": total, "page": page, "page_size": page_size}


def _csv_safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s  # neutralise spreadsheet formula injection


@router.get("/applications/export.csv")
def export_csv(q: str | None = None, status: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = [_row(db, a) for a in db.scalars(_query(user, q, status).order_by(Application.id))]
    buf = io.StringIO()
    cols = ["company", "job_title", "location", "employment_type", "date_posted", "date_discovered", "date_prepared", "date_applied",
            "status", "job_match", "source", "job_url", "resume_version", "cover_letter_version", "submission_method",
            "external_reference", "notes", "follow_up_date"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([_csv_safe(r.get(c)) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="applications.csv"'})


@router.get("/applications/{aid}")
def get_application(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned_app(db, user, aid)
    j = db.get(Job, a.job_id)
    rv = db.get(ResumeVersion, a.resume_version_id) if a.resume_version_id else None
    cl = db.get(CoverLetter, a.cover_letter_version_id) if a.cover_letter_version_id else None
    events = db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == a.id).order_by(ApplicationEvent.id)).all()
    audit_events = db.scalars(select(AuditEvent).where(AuditEvent.user_id == user.id, AuditEvent.entity_type == "application",
                                                       AuditEvent.entity_id == a.id).order_by(AuditEvent.id)).all()
    return _row(db, a) | {
        "job": as_dict(j) | {"listings": [as_dict(l) for l in j.listings]},
        "original_resume_id": rv.resume_id if rv else None,
        "resume_version": as_dict(rv, "docx_file_key", "pdf_file_key") if rv else None,
        "cover_letter": as_dict(cl) if cl else None, "package": a.package,
        "events": [as_dict(e) for e in events], "audit_events": [as_dict(e) for e in audit_events]}


class AppPatch(BaseModel):
    status: str | None = None
    notes: str | None = None
    follow_up_date: datetime | None = None
    resume_version_id: int | None = None


@router.patch("/applications/{aid}")
def patch_application(aid: int, body: AppPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned_app(db, user, aid)
    data = body.model_dump(exclude_unset=True)
    if data.get("resume_version_id"):
        _call(appsvc.attach_version, db, a, owned_version(db, user, data["resume_version_id"]))
    _call(appsvc.user_update, db, a, data.get("status"), data.get("notes"), data.get("follow_up_date"), "follow_up_date" in data)
    db.commit()
    return _row(db, a)


@router.post("/applications/{aid}/approve")
def approve(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned_app(db, user, aid)
    _call(appsvc.approve, db, user, a)
    audit(db, user.id, "application_approved", "application", a.id)
    db.commit()
    return _row(db, a)


@router.post("/applications/{aid}/submit")
def submit(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_app(db, user, aid)
    a = _call(appsvc.submit, db, user, aid, "user")
    audit(db, user.id, "application_submit_attempted", "application", a.id, outcome=a.status)
    db.commit()
    return _row(db, a)
