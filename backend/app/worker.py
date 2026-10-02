"""Optional Celery deployment of the scheduler (requires Redis): `celery -A app.worker worker -B`.

The dependency-free alternative is `python -m app.scheduler`. Both call the same, lock-protected code.
"""
from celery import Celery

from .config import get_settings
from .db import SessionLocal
from .services import scheduler

s = get_settings()
celery = Celery("jobpilot", broker=s.redis_url or "redis://localhost:6379/0", backend=s.redis_url or None)
celery.conf.beat_schedule = {"scheduler-tick": {"task": "app.worker.tick", "schedule": float(s.scheduler_poll_seconds)}}
celery.conf.task_acks_late = True


@celery.task(name="app.worker.tick")
def tick() -> list[int]:
    return scheduler.run_due(SessionLocal)


@celery.task(name="app.worker.run_profile", bind=True, max_retries=0)
def run_profile(self, profile_id: int):
    run = scheduler.run_profile_with_retries(SessionLocal, profile_id, "manual")
    return run.id if run else None
