"""Application lifecycle with duplicate-submission protection.

Guarantees:
  * one Application per (user, job)         -> UNIQUE constraint + get-or-create
  * one submission attempt claimed at once  -> atomic compare-and-set on status (works on SQLite & Postgres)
  * retries never re-submit                 -> only READY/FAILED may be claimed; unknown outcomes become
                                               SUBMISSION_CONFIRMATION_PENDING, which is never auto-retried
  * "submitted" requires confirmation from the submitter (or an explicit user attestation)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import (Application, ApplicationEvent, AutomationSettings, CoverLetter, Job, JobStatus,
                      Resume, ResumeVersion, SUBMITTABLE, User)
from .textutil import sha

S = JobStatus


class ApplicationError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class SubmissionResult:
    confirmed: bool
    reference: str | None = None
    error: str | None = None
    transient: bool = False
    requires_manual: bool = False


class Submitter:
    """Tier-1 integration point: implement `supports` and `submit` for an authorized employer/ATS API."""
    name = "base"

    def supports(self, job: Job) -> bool:
        return False

    def submit(self, package: dict, idempotency_key: str) -> SubmissionResult:
        raise NotImplementedError


class SandboxSubmitter(Submitter):
    """TEST DOUBLE. Never contacts an employer. Only active while SANDBOX_MODE=true."""
    name = "sandbox"

    def supports(self, job: Job) -> bool:
        return get_settings().sandbox_mode

    def submit(self, package, idempotency_key):
        return SubmissionResult(confirmed=True, reference=f"SANDBOX-{idempotency_key[:10]}")


_submitters: list[Submitter] = [SandboxSubmitter()]


def register_submitter(s: Submitter, first: bool = True) -> None:
    _submitters.insert(0 if first else len(_submitters), s)


def reset_submitters() -> None:
    _submitters[:] = [SandboxSubmitter()]


def submitter_for(job: Job) -> Submitter | None:
    return next((s for s in _submitters if s.supports(job)), None)


# ---------------------------------------------------------------------------------------
def add_event(db: Session, app: Application, event_type: str, new_status: str | None = None,
              prev: str | None = None, actor: str = "system", **details) -> None:
    db.add(ApplicationEvent(application_id=app.id, event_type=event_type, previous_status=prev,
                            new_status=new_status, actor_type=actor, details=details))


def set_status(db: Session, app: Application, new: str, event: str, actor: str = "system", **details) -> None:
    prev, app.status = app.status, new
    add_event(db, app, event, new, prev, actor, **details)


def build_package(db: Session, user: User, job: Job, rv: ResumeVersion | None, cl: CoverLetter | None,
                  reason: str | None) -> dict:
    from ..models import CandidateProfile

    prof = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    src = rv.resume.structured_profile if rv else {}
    answers = {"full_name": (prof.full_name if prof and prof.full_name else (src or {}).get("name")),
               "email": user.email, "phone": prof.phone if prof else (src or {}).get("phone"),
               "linkedin": prof.linkedin_url if prof else None}
    if prof and prof.work_authorization:
        answers["work_authorization"] = prof.work_authorization
    listing = job.listings[0] if job.listings else None
    return {
        "job_title": job.title, "company": job.company_name,
        "application_url": (listing.application_url or listing.source_url) if listing else None,
        "resume_version_id": rv.id if rv else None, "cover_letter_id": cl.id if cl else None,
        "suggested_answers": {k: v for k, v in answers.items() if v},
        "checklist": ["Review the tailored resume and cover letter", "Complete any screening questions yourself",
                      "Answer demographic / EEO questions only if you choose to",
                      "Confirm work-authorization and legal attestations personally",
                      "Do not state salary expectations unless you decide to"],
        "reason_manual_action": reason,
    }


def get_application(db: Session, user_id: int, job_id: int) -> Application | None:
    return db.scalar(select(Application).where(Application.user_id == user_id, Application.job_id == job_id))


def prepare_application(db: Session, user: User, job: Job, rv: ResumeVersion, cl: CoverLetter | None = None,
                        actor: str = "user") -> tuple[Application, bool]:
    """Get-or-create. Returns (application, created). Never creates a second application for a job."""
    existing = get_application(db, user.id, job.id)
    if existing:
        return existing, False
    sub = submitter_for(job)
    manual_reason = None
    if sub is None:
        manual_reason = ("No authorized submission integration is available for this employer; "
                         "apply through the employer's page using the prepared package.")
    if not rv.validation_results.get("passed"):
        manual_reason = "Resume failed factual validation; fix it before applying."
    status = S.MANUAL if manual_reason and sub is None else S.AWAITING_APPROVAL
    if not rv.validation_results.get("passed"):
        status = S.RESUME_READY
    listing = job.listings[0] if job.listings else None
    app = Application(user_id=user.id, job_id=job.id, resume_version_id=rv.id,
                      cover_letter_version_id=cl.id if cl else None, status=status,
                      application_url=(listing.application_url or listing.source_url) if listing else None,
                      idempotency_key=sha("app", str(user.id), str(job.id)), manual_reason=manual_reason,
                      submission_method="manual" if status == S.MANUAL else None)
    db.add(app)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return get_application(db, user.id, job.id), False  # type: ignore[return-value]
    app.package = build_package(db, user, job, rv, cl, manual_reason)
    add_event(db, app, "application_prepared", status, None, actor, resume_version_id=rv.id,
              validation_passed=bool(rv.validation_results.get("passed")))
    return app, True


def attach_version(db: Session, app: Application, rv: ResumeVersion) -> Application:
    """Swap in a different (e.g. user-edited) resume version before submission; requires re-approval."""
    if app.status not in (S.AWAITING_APPROVAL, S.RESUME_READY, S.READY, S.MANUAL):
        raise ApplicationError("bad_state", "The resume can no longer be changed for this application.")
    job = db.get(Job, app.job_id)
    old = app.resume_version_id
    app.resume_version_id, app.approved_at = rv.id, None
    target = S.MANUAL if submitter_for(job) is None else (S.AWAITING_APPROVAL if rv.validation_results.get("passed") else S.RESUME_READY)
    if not rv.validation_results.get("passed"):
        target = S.RESUME_READY
    set_status(db, app, target, "resume_version_changed", "user", old_version=old, new_version=rv.id)
    return app


def approve(db: Session, user: User, app: Application, acknowledge_warnings: bool = False) -> Application:
    if app.status not in (S.AWAITING_APPROVAL, S.RESUME_READY, S.MANUAL):
        raise ApplicationError("bad_state", f"Cannot approve an application in status '{app.status}'.")
    rv = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    if rv is None:
        raise ApplicationError("no_resume", "No resume version attached.", 422)
    if not rv.validation_results.get("passed"):
        raise ApplicationError("validation_failed", "The resume has unresolved factual-validation errors. "
                               "Edit it to remove unsupported content first.", 422)
    now = utcnow()
    rv.approved_at = rv.approved_at or now
    if app.cover_letter_version_id:
        cl = db.get(CoverLetter, app.cover_letter_version_id)
        if cl and not cl.validation_results.get("passed", True):
            raise ApplicationError("validation_failed", "The cover letter contains unsupported claims.", 422)
        if cl:
            cl.approved_at = cl.approved_at or now
    app.approved_at = now
    job = db.get(Job, app.job_id)
    if app.status != S.MANUAL:
        set_status(db, app, S.READY if submitter_for(job) else S.MANUAL, "user_approved", "user")
        if app.status == S.MANUAL:
            app.manual_reason = app.manual_reason or "No authorized integration; apply manually."
            app.submission_method = "manual"
    else:
        add_event(db, app, "user_approved", S.MANUAL, S.MANUAL, "user")
    return app


def _lock_documents(db: Session, app: Application) -> None:
    if app.resume_version_id:
        rv = db.get(ResumeVersion, app.resume_version_id)
        if rv:
            rv.locked = True
    if app.cover_letter_version_id:
        cl = db.get(CoverLetter, app.cover_letter_version_id)
        if cl:
            cl.locked = True


def claim(db: Session, app_id: int, user_id: int) -> bool:
    """Atomically move READY/FAILED -> IN_PROGRESS. Exactly one concurrent caller gets True."""
    res = db.execute(update(Application).where(
        Application.id == app_id, Application.user_id == user_id,
        Application.status.in_(SUBMITTABLE), Application.approved_at.is_not(None))
        .values(status=S.IN_PROGRESS, attempts=Application.attempts + 1, updated_at=utcnow()))
    db.commit()
    return res.rowcount == 1


def submit(db: Session, user: User, app_id: int, actor: str = "user") -> Application:
    app = db.scalar(select(Application).where(Application.id == app_id, Application.user_id == user.id))
    if app is None:
        raise ApplicationError("not_found", "Application not found.", 404)
    job = db.get(Job, app.job_id)
    if actor == "scheduler":
        auto = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user.id))
        if not auto or auto.paused or auto.mode != "auto_submit_authorized" or not auto.auto_submit_consent_at:
            raise ApplicationError("automation_disabled", "Automatic submission is not enabled.", 403)
    if job.status != "open":
        raise ApplicationError("listing_closed", "The listing is closed or expired.")
    sub = submitter_for(job)
    if sub is None:
        raise ApplicationError("no_integration", "No authorized submission method; use the manual package.", 422)

    if not claim(db, app.id, user.id):
        db.refresh(app)
        raise ApplicationError("not_claimable", f"Application is '{app.status}' and cannot be submitted now "
                               "(already submitted, in progress, or not approved).")
    db.refresh(app)
    add_event(db, app, "submission_started", S.IN_PROGRESS, None, actor, attempt=app.attempts, submitter=sub.name)
    db.commit()

    try:
        result = sub.submit(app.package or {}, app.idempotency_key)
    except Exception as e:  # noqa: BLE001 - outcome unknown: do NOT allow blind retry
        set_status(db, app, S.CONFIRMATION_PENDING, "submission_outcome_unknown", actor, error=type(e).__name__)
        db.commit()
        return app

    if result.confirmed:
        app.submission_timestamp = utcnow()
        app.external_reference = result.reference
        app.submission_method = sub.name
        _lock_documents(db, app)
        set_status(db, app, S.SUBMITTED, "submission_confirmed", actor, reference=result.reference, submitter=sub.name)
    elif result.requires_manual:
        app.manual_reason = result.error or "Employer requires manual completion."
        app.submission_method = "manual"
        set_status(db, app, S.MANUAL, "manual_required", actor, reason=app.manual_reason)
    elif result.error:  # definite failure: safe to retry later
        app.manual_reason = None
        set_status(db, app, S.FAILED, "submission_failed", actor, error=result.error, transient=result.transient)
    else:  # sent but no confirmation
        _lock_documents(db, app)
        set_status(db, app, S.CONFIRMATION_PENDING, "submission_unconfirmed", actor)
    db.commit()
    return app


def recover_stale(db: Session, older_than: timedelta = timedelta(minutes=30)) -> int:
    """Worker-crash recovery: IN_PROGRESS rows with unknown outcome -> CONFIRMATION_PENDING (never resubmitted)."""
    cutoff = utcnow() - older_than
    rows = db.scalars(select(Application).where(Application.status == S.IN_PROGRESS,
                                                Application.updated_at < cutoff)).all()
    for a in rows:
        set_status(db, a, S.CONFIRMATION_PENDING, "recovered_after_worker_failure", "system",
                   note="Outcome unknown; verify with the employer before retrying.")
    db.commit()
    return len(rows)


USER_STATUSES = {S.SUBMITTED, S.INTERVIEW, S.REJECTED, S.OFFER, S.WITHDRAWN, S.CLOSED, S.MANUAL}
USER_TRANSITIONS = {
    S.MANUAL: {S.SUBMITTED, S.WITHDRAWN, S.CLOSED},
    S.CONFIRMATION_PENDING: {S.SUBMITTED, S.FAILED, S.WITHDRAWN, S.CLOSED},
    S.SUBMITTED: {S.INTERVIEW, S.REJECTED, S.OFFER, S.WITHDRAWN, S.CLOSED},
    S.INTERVIEW: {S.REJECTED, S.OFFER, S.WITHDRAWN},
    S.OFFER: {S.REJECTED, S.WITHDRAWN},
    S.AWAITING_APPROVAL: {S.WITHDRAWN, S.CLOSED},
    S.READY: {S.WITHDRAWN, S.CLOSED},
    S.RESUME_READY: {S.WITHDRAWN, S.CLOSED},
    S.FAILED: {S.MANUAL, S.WITHDRAWN, S.CLOSED},
}


def user_update(db: Session, app: Application, status: str | None, notes: str | None,
                follow_up: datetime | None, set_follow_up: bool) -> Application:
    if notes is not None:
        app.notes = notes
        add_event(db, app, "note_updated", actor="user")
    if set_follow_up:
        app.follow_up_date = follow_up
        add_event(db, app, "follow_up_set", actor="user", follow_up=follow_up.isoformat() if follow_up else None)
    if status and status != app.status:
        if status not in USER_TRANSITIONS.get(app.status, set()):
            raise ApplicationError("bad_transition", f"Cannot change status from '{app.status}' to '{status}'.", 422)
        if status == S.SUBMITTED:
            app.submission_timestamp = utcnow()
            app.submission_method = app.submission_method or "manual"
            _lock_documents(db, app)
            set_status(db, app, status, "user_attested_submission", "user",
                       confirmation="user_attested", note="Marked submitted by the user; not independently verified.")
        else:
            set_status(db, app, status, "status_changed", "user")
    return app
