"""Daily report + notification generation."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import (Application, AutomationSettings, DailyReport, Job, JobMatch, JobStatus, Notification,
                      SearchProfile, SearchRun, User)

log = logging.getLogger("jobpilot.reports")


def send_email(to: str, subject: str, body: str) -> None:
    """Console backend by default. Replace with SMTP/provider in production (see docs/operations.md)."""
    log.info("EMAIL to=%s subject=%s", to, subject)


def build_report(db: Session, run: SearchRun) -> DailyReport:
    existing = db.scalar(select(DailyReport).where(DailyReport.search_run_id == run.id))
    if existing:
        return existing
    sp = db.get(SearchProfile, run.search_profile_id)
    stats = run.stats or {}
    new_matches = db.scalars(select(JobMatch).where(
        JobMatch.search_profile_id == sp.id, JobMatch.first_run_id == run.id, JobMatch.qualified.is_(True))).all()
    new_jobs = []
    for m in new_matches:
        j = db.get(Job, m.job_id)
        new_jobs.append({"job_id": j.id, "title": j.title, "company": j.company_name, "score": m.match_score,
                         "posted_at": j.posted_at.isoformat() if j.posted_at else None})
        m.reported = True

    def count(*statuses):
        return db.scalar(select(func.count(Application.id)).where(
            Application.user_id == run.user_id, Application.status.in_(statuses))) or 0

    srcs = run.source_statistics or {}
    data = {
        "run_id": run.id, "run_status": run.status, "run_time": (run.started_at.isoformat() if run.started_at else None),
        "profile": sp.profile_name,
        "sources_searched": [k for k, v in srcs.items() if v.get("status") == "ok"],
        "sources_failed": {k: v.get("error") for k, v in srcs.items() if v.get("status") != "ok"},
        "listings_retrieved": stats.get("retrieved", 0), "new_unique_jobs": stats.get("new_jobs", 0),
        "matching_jobs": len(new_jobs), "resumes_generated": stats.get("resumes_generated", 0),
        "ready_for_review": count(JobStatus.AWAITING_APPROVAL, JobStatus.RESUME_READY),
        "ready_to_apply": count(JobStatus.READY),
        "applications_submitted": stats.get("submitted", 0),
        "applications_manual_action": count(JobStatus.MANUAL),
        "jobs_skipped": sum((stats.get("skipped_reasons") or {}).values()),
        "skipped_reasons": stats.get("skipped_reasons", {}),
        "closed_listings": stats.get("closed", 0),
        "failed_tasks": stats.get("failed_tasks", 0), "errors": run.error_summary,
        "new_jobs": new_jobs,
        "no_new_jobs": len(new_jobs) == 0,
        "summary": ("No new qualifying jobs were found during this run."
                    if not new_jobs else f"{len(new_jobs)} new qualifying job(s) found."),
    }
    rep = DailyReport(user_id=run.user_id, search_profile_id=sp.id, search_run_id=run.id, data=data)
    db.add(rep)

    def note(kind, title, content=""):
        db.add(Notification(user_id=run.user_id, notification_type=kind, title=title, content=content))

    if not new_jobs:
        note("report", f"{sp.profile_name}: no new qualifying jobs", data["summary"])
    else:
        note("report", f"{sp.profile_name}: {len(new_jobs)} new qualifying job(s)",
             "; ".join(f"{j['title']} @ {j['company']}" for j in new_jobs[:10]))
    if data["ready_for_review"]:
        note("ready_to_review", f"{data['ready_for_review']} job(s) with a tailored resume ready to review")
    if data["ready_to_apply"]:
        note("ready_to_apply", f"{data['ready_to_apply']} application(s) approved and ready to submit")
    if data["applications_manual_action"]:
        note("manual_action", f"{data['applications_manual_action']} application(s) need manual action")
    if data["applications_submitted"]:
        note("submitted", f"{data['applications_submitted']} application(s) submitted and confirmed")
    if run.status in ("partial", "failed") or data["failed_tasks"]:
        note("needs_attention", f"Search run {run.status}", run.error_summary or "")
    auto = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == run.user_id))
    if auto and auto.email_notifications:
        u = db.get(User, run.user_id)
        send_email(u.email, f"Job search report: {data['summary']}", str(data["summary"]))
    db.commit()
    return rep
