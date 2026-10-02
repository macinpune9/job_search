"""Scheduler: due-run detection, distributed locks, bounded retries with exponential backoff, dead letters.

Runs independently of the web app: `python -m app.scheduler` (no Redis needed) or the Celery beat task in
app/worker.py. Locks live in the database so any number of workers/processes can coordinate.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from ..db import SessionLocal, utcnow
from ..models import (AutomationSettings, DeadLetter, Notification, RunLock, SearchProfile, SearchRun, User)
from . import applications as appsvc
from . import engine

log = logging.getLogger("jobpilot.scheduler")


def acquire_lock(db: Session, key: str, owner: str, ttl_seconds: int | None = None) -> bool:
    ttl = ttl_seconds or get_settings().lock_ttl_seconds
    now = utcnow()
    try:
        db.add(RunLock(key=key, owner=owner, expires_at=now + timedelta(seconds=ttl)))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
    # steal only if expired (compare-and-set)
    res = db.execute(update(RunLock).where(RunLock.key == key, RunLock.expires_at < now)
                     .values(owner=owner, expires_at=now + timedelta(seconds=ttl)))
    db.commit()
    return res.rowcount == 1


def release_lock(db: Session, key: str, owner: str) -> None:
    db.execute(delete(RunLock).where(RunLock.key == key, RunLock.owner == owner))
    db.commit()


def is_due(db: Session, sp: SearchProfile, interval_hours: int, now: datetime) -> bool:
    last = db.scalar(select(SearchRun.started_at).where(SearchRun.search_profile_id == sp.id)
                     .order_by(SearchRun.started_at.desc()).limit(1))
    return last is None or now - last >= timedelta(hours=interval_hours)


def run_profile_with_retries(factory: sessionmaker, profile_id: int, trigger: str = "scheduler",
                             sleep=time.sleep) -> SearchRun | None:
    """Lock -> run -> retry transient crashes (exponential backoff, bounded) -> dead-letter."""
    s = get_settings()
    owner = uuid.uuid4().hex
    key = f"search:{profile_id}"
    with factory() as db:
        if not acquire_lock(db, key, owner):
            log.info("profile %s already running elsewhere; skipping", profile_id)
            return None
    run_id = None
    try:
        last_err = ""
        for attempt in range(1, s.max_task_retries + 1):
            with factory() as db:
                try:
                    run = engine.run_search(db, profile_id, trigger, run_id=run_id)
                    return run
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    last_err = f"{type(e).__name__}: {str(e)[:300]}"
                    log.warning("run for profile %s failed (attempt %s/%s): %s", profile_id, attempt, s.max_task_retries, last_err)
                    if run_id is None:
                        r = db.scalar(select(SearchRun).where(SearchRun.search_profile_id == profile_id,
                                                              SearchRun.status == "running").order_by(SearchRun.id.desc()))
                        run_id = r.id if r else None
            if attempt < s.max_task_retries:
                sleep(s.retry_base_seconds * (2 ** (attempt - 1)))
        with factory() as db:
            db.add(DeadLetter(task_name="run_search", payload={"profile_id": profile_id}, error=last_err,
                              attempts=s.max_task_retries))
            sp = db.get(SearchProfile, profile_id)
            if run_id and (r := db.get(SearchRun, run_id)):
                r.status, r.completed_at, r.error_summary = "failed", utcnow(), last_err
            if sp:
                db.add(Notification(user_id=sp.user_id, notification_type="needs_attention",
                                    title="Scheduled search failed repeatedly", content=last_err))
            db.commit()
        return None
    finally:
        with factory() as db:
            release_lock(db, key, owner)


def run_due(factory: sessionmaker = SessionLocal, now: datetime | None = None, sleep=time.sleep) -> list[int]:
    """One scheduler tick. Returns the profile ids that were run."""
    now = now or utcnow()
    ran: list[int] = []
    with factory() as db:
        appsvc.recover_stale(db)
        stale = db.scalars(select(SearchRun).where(SearchRun.status == "running",
                                                   SearchRun.started_at < now - timedelta(seconds=get_settings().lock_ttl_seconds))).all()
        for r in stale:  # worker died mid-run
            r.status, r.completed_at, r.error_summary = "failed", now, "worker terminated before completion"
        db.commit()
        due = []
        for sp, user in db.execute(select(SearchProfile, User).join(User, User.id == SearchProfile.user_id).where(
                SearchProfile.active.is_(True), User.account_status == "active")):
            auto = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user.id))
            if auto and auto.paused:
                continue
            if is_due(db, sp, auto.run_interval_hours if auto else 24, now):
                due.append(sp.id)
    for pid in due:
        run_profile_with_retries(factory, pid, "scheduler", sleep)
        ran.append(pid)
    return ran


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    poll = get_settings().scheduler_poll_seconds
    log.info("scheduler started; polling every %ss", poll)
    while True:
        try:
            run_due()
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick failed")
        time.sleep(poll)
