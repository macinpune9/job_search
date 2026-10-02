"""Search-run orchestration: discover -> dedup -> filter -> match -> prepare -> (authorized) submit -> report."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import connectors
from ..connectors.base import ConnectorError, ConnectorUnavailable
from ..db import utcnow
from ..models import (Application, AutomationSettings, ConnectorHealth, Job, JobMatch, JobSourceListing,
                      JobStatus, Resume, ResumeVersion, SearchProfile, SearchRun, SourceCursor, User)
from . import applications as appsvc
from . import matching, reports, versions
from .ingest import upsert_listing

log = logging.getLogger("jobpilot.engine")


def _health(db: Session, key: str, ok: bool, err: str | None = None) -> None:
    h = db.get(ConnectorHealth, key) or ConnectorHealth(source_name=key, consecutive_failures=0)
    db.add(h)
    if ok:
        h.last_success_at, h.consecutive_failures, h.last_error = utcnow(), 0, None
    else:
        h.last_error_at, h.last_error = utcnow(), (err or "")[:500]
        h.consecutive_failures = (h.consecutive_failures or 0) + 1


def pick_resume(db: Session, sp: SearchProfile) -> Resume | None:
    r = db.get(Resume, sp.resume_id) if sp.resume_id else None
    if r and r.user_id == sp.user_id:
        return r
    return db.scalar(select(Resume).where(Resume.user_id == sp.user_id, Resume.processing_status == "parsed")
                     .order_by(Resume.is_primary.desc(), Resume.uploaded_at.desc()))


def run_search(db: Session, profile_id: int, trigger: str = "manual", run_id: int | None = None) -> SearchRun:
    sp = db.get(SearchProfile, profile_id)
    if sp is None:
        raise ValueError("search profile not found")
    run = db.get(SearchRun, run_id) if run_id else None
    if run is None:
        run = SearchRun(user_id=sp.user_id, search_profile_id=sp.id, trigger=trigger)
        db.add(run)
        db.commit()
    started = run.started_at
    resume = pick_resume(db, sp)
    structured = resume.structured_profile if resume else None
    auto = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == sp.user_id)) or AutomationSettings(user_id=sp.user_id)
    user = db.get(User, sp.user_id)

    stats = Counter()
    skipped: Counter = Counter()
    src_stats: dict[str, dict] = {}
    new_match_ids: list[int] = []
    errors: list[str] = []
    ok_sources = 0

    if not sp.sources:
        run.status, run.error_summary, run.completed_at = "failed", "No job sources configured for this search profile.", utcnow()
        db.commit()
        reports.build_report(db, run)
        return run

    for src in sp.sources:
        name, board = src.get("source"), src.get("board", "")
        key = f"{name}:{board}"
        cur = db.scalar(select(SourceCursor).where(SourceCursor.search_profile_id == sp.id, SourceCursor.source_name == key))
        try:
            conn = connectors.make_connector(name)
            since = (cur.last_successful_run_at - timedelta(hours=sp.overlap_hours)) if cur and cur.last_successful_run_at else None
            result = conn.fetch(board, since=since)
        except ConnectorUnavailable as e:
            src_stats[key] = {"status": "unavailable", "error": str(e)}
            errors.append(f"{key}: {e}")
            _health(db, key, False, str(e))
            db.commit()
            continue
        except ConnectorError as e:
            src_stats[key] = {"status": "failed", "error": str(e), "transient": e.transient}
            errors.append(f"{key}: {e}")
            _health(db, key, False, str(e))
            db.commit()
            continue
        except Exception as e:  # noqa: BLE001 - one broken connector must not stop the others
            log.exception("connector crashed: %s", key)
            src_stats[key] = {"status": "failed", "error": f"{type(e).__name__}"}
            errors.append(f"{key}: {type(e).__name__}")
            _health(db, key, False, type(e).__name__)
            db.commit()
            continue

        s = {"status": "ok", "retrieved": len(result.listings), "new_jobs": 0, "qualified_new": 0, "closed": 0, "skipped_bad_records": 0}
        for raw in result.listings:
            stats["retrieved"] += 1
            try:
                with db.begin_nested():
                    up = upsert_listing(db, raw)
                    m = db.scalar(select(JobMatch).where(JobMatch.search_profile_id == sp.id, JobMatch.job_id == up.job.id))
                    mr = matching.evaluate(up.job, sp, structured)
                    if m is None:
                        m = JobMatch(user_id=sp.user_id, search_profile_id=sp.id, job_id=up.job.id, first_run_id=run.id,
                                     workflow_status=JobStatus.NEEDS_REVIEW if up.job.needs_dedup_review else JobStatus.NEW)
                        db.add(m)
                        db.flush()
                        if mr.qualified:
                            s["qualified_new"] += 1
                            stats["qualified_new"] += 1
                            new_match_ids.append(m.id)
                        else:
                            for ex in mr.exclusions:
                                skipped[ex["code"]] += 1
                    elif mr.qualified and not m.qualified:
                        m.first_run_id = m.first_run_id or run.id  # newly qualifies (e.g. profile edited)
                        new_match_ids.append(m.id)
                    m.match_score, m.matching_factors, m.exclusion_reasons = mr.score, mr.factors, mr.exclusions
                    m.qualified, m.evaluated_at = mr.qualified, utcnow()
                    if up.created_job:
                        s["new_jobs"] += 1
                        stats["new_jobs"] += 1
                    elif up.changed:
                        stats["changed"] += 1
            except Exception as e:  # noqa: BLE001
                s["skipped_bad_records"] += 1
                stats["bad_records"] += 1
                log.warning("bad listing %s/%s: %s", key, raw.source_job_id, type(e).__name__)

        if result.complete:  # only trust absence when the whole board was enumerated
            gone = db.scalars(select(JobSourceListing).where(
                JobSourceListing.source_name == name, JobSourceListing.source_board == board,
                JobSourceListing.status == "open", JobSourceListing.last_checked_at < started)).all()
            for l in gone:
                l.status = "closed"
                s["closed"] += 1
                stats["closed"] += 1
                if all(x.status == "closed" for x in l.job.listings):
                    l.job.status = "closed"
                    for a in db.scalars(select(Application).where(Application.job_id == l.job_id)):
                        if a.status in (JobStatus.AWAITING_APPROVAL, JobStatus.READY, JobStatus.RESUME_READY):
                            appsvc.set_status(db, a, JobStatus.CLOSED, "listing_closed", "system")
        if cur is None:
            cur = SourceCursor(search_profile_id=sp.id, source_name=key)
            db.add(cur)
        cur.last_successful_run_at, cur.last_successful_cursor = utcnow(), result.cursor
        _health(db, key, True)
        src_stats[key] = s
        ok_sources += 1
        db.commit()

    # ----- automation policy -----
    if resume and user and auto.mode != "discovery_only" and not auto.paused:
        for mid in new_match_ids:
            m = db.get(JobMatch, mid)
            if not m or not m.qualified or m.match_score < auto.auto_prepare_min_score:
                continue
            job = db.get(Job, m.job_id)
            if job.status != "open" or appsvc.get_application(db, user.id, job.id):
                continue
            try:
                with db.begin_nested():
                    rv = versions.generate_for_job(db, resume, job)
                    stats["resumes_generated"] += 1
                    cl = None
                    if auto.cover_letters_enabled:
                        cl = versions.make_cover_letter(db, user.id, resume, job, rv.analysis.get("matched_skills", []))
                    app, created = appsvc.prepare_application(db, user, job, rv, cl, actor="scheduler")
                    if created:
                        stats["applications_prepared"] += 1
                        if app.status == JobStatus.MANUAL:
                            stats["manual_required"] += 1
            except Exception as e:  # noqa: BLE001
                stats["failed_tasks"] += 1
                errors.append(f"prepare job {m.job_id}: {type(e).__name__}")
                log.warning("prepare failed for job %s: %s", m.job_id, type(e).__name__)
        db.commit()

        if auto.mode == "auto_submit_authorized" and auto.auto_submit_consent_at:
            for a in db.scalars(select(Application).where(
                    Application.user_id == user.id, Application.status == JobStatus.AWAITING_APPROVAL)).all():
                rv = db.get(ResumeVersion, a.resume_version_id)
                if not rv or not rv.validation_results.get("passed"):
                    continue
                try:
                    appsvc.approve(db, user, a)
                    db.commit()
                    done = appsvc.submit(db, user, a.id, actor="scheduler")
                    stats["submitted" if done.status == JobStatus.SUBMITTED else "submit_unconfirmed"] += 1
                except appsvc.ApplicationError as e:
                    stats["failed_tasks"] += 1
                    errors.append(f"submit app {a.id}: {e.code}")
                    db.rollback()

    run.stats = {**dict(stats), "skipped_reasons": dict(skipped)}
    run.source_statistics = src_stats
    run.error_summary = "; ".join(errors)[:2000] or None
    run.status = "completed" if ok_sources == len(sp.sources) and not errors else ("partial" if ok_sources else "failed")
    run.completed_at = utcnow()
    db.commit()
    reports.build_report(db, run)
    return run
