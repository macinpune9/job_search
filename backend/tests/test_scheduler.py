import threading
from datetime import timedelta

from sqlalchemy import func, select

from app.db import SessionLocal, utcnow
from app.models import Application, DeadLetter, Job, RunLock, SearchRun
from app.services import engine, scheduler
from .conftest import gh_job, lever_job, make_profile, register, run_now, upload


def count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_due_logic_24h_and_configurable_interval(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    pid = make_profile(client, auth)["id"]
    t0 = utcnow()
    assert scheduler.run_due(now=t0) == [pid]                    # never ran -> due
    assert scheduler.run_due(now=t0 + timedelta(hours=23)) == []  # not yet
    assert scheduler.run_due(now=t0 + timedelta(hours=25)) == [pid]
    client.patch("/api/automation-settings", headers=auth, json={"run_interval_hours": 48})
    assert scheduler.run_due(now=utcnow() + timedelta(hours=30)) == []
    assert count(Job) == 1  # three runs, still one job
    with SessionLocal() as db:
        assert {r.trigger for r in db.scalars(select(SearchRun))} == {"scheduler"}


def test_scheduler_runs_for_multiple_users_independently_of_login(client, web):
    a, b = register(client, "a@example.com"), register(client, "b@example.com")
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    web.lever["globex"] = [lever_job("L1", "Software Engineer")]
    pa = make_profile(client, a)["id"]
    pb = make_profile(client, b, sources=[{"source": "lever", "board": "globex"}])["id"]
    assert sorted(scheduler.run_due()) == sorted([pa, pb])  # no HTTP session / browser needed
    ja = {i["title"] for i in client.get("/api/jobs", headers=a).json()["items"]}
    jb = {i["company"] for i in client.get("/api/jobs", headers=b).json()["items"]}
    assert ja == {"Software Engineer"} and jb == {"globex"}
    assert len(client.get("/api/reports/daily", headers=a).json()) == 1 and len(client.get("/api/reports/daily", headers=b).json()) == 1


def test_paused_or_inactive_profiles_are_skipped(client, auth, web):
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    pid = make_profile(client, auth)["id"]
    client.patch("/api/automation-settings", headers=auth, json={"paused": True})
    assert scheduler.run_due() == []
    client.patch("/api/automation-settings", headers=auth, json={"paused": False})
    client.patch(f"/api/search-profiles/{pid}", headers=auth, json={"active": False})
    assert scheduler.run_due() == []


def test_distributed_lock_mutual_exclusion_and_expiry():
    with SessionLocal() as db1, SessionLocal() as db2:
        assert scheduler.acquire_lock(db1, "k", "w1", 60)
        assert not scheduler.acquire_lock(db2, "k", "w2", 60)
        scheduler.release_lock(db2, "k", "w2")          # wrong owner can't release
        assert not scheduler.acquire_lock(db2, "k", "w2", 60)
        scheduler.release_lock(db1, "k", "w1")
        assert scheduler.acquire_lock(db2, "k", "w2", 60)
        # expired lock (crashed worker) can be taken over
        lk = db1.get(RunLock, "k")
        lk.expires_at = utcnow() - timedelta(seconds=1)
        db1.commit()
        assert scheduler.acquire_lock(db1, "k", "w3", 60)


def test_concurrent_workers_same_profile_only_one_runs(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(i, f"Software Engineer {i}") for i in range(1, 15)]
    pid = make_profile(client, auth)["id"]
    out = []
    ts = [threading.Thread(target=lambda: out.append(scheduler.run_profile_with_retries(SessionLocal, pid))) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len([o for o in out if o is not None]) >= 1
    assert count(Job) == 14 and count(RunLock) == 0  # no duplicates, lock released


def test_transient_crash_retried_then_succeeds_idempotently(client, auth, web, monkeypatch):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    pid = make_profile(client, auth)["id"]
    real, calls, sleeps = engine.run_search, {"n": 0}, []

    def flaky(db, profile_id, trigger="manual", run_id=None):
        calls["n"] += 1
        if calls["n"] < 3:
            real(db, profile_id, trigger, run_id)  # does the work, then dies before acknowledging
            raise RuntimeError("worker lost connection")
        return real(db, profile_id, trigger, run_id)

    monkeypatch.setattr(engine, "run_search", flaky)
    run = scheduler.run_profile_with_retries(SessionLocal, pid, sleep=sleeps.append)
    assert run is not None and calls["n"] == 3 and sleeps == [0.0, 0.0]
    assert count(Job) == 1 and count(DeadLetter) == 0
    assert count(Application) == 1  # three attempts, still exactly one prepared application


def test_exponential_backoff_and_dead_letter_after_bounded_retries(client, auth, web, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "retry_base_seconds", 2.0)
    monkeypatch.setattr(get_settings(), "max_task_retries", 3)
    pid = make_profile(client, auth)["id"]

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(engine, "run_search", boom)
    sleeps = []
    assert scheduler.run_profile_with_retries(SessionLocal, pid, sleep=sleeps.append) is None
    assert sleeps == [2.0, 4.0]  # exponential, bounded (3 attempts -> 2 waits)
    with SessionLocal() as db:
        dl = db.scalar(select(DeadLetter))
        assert dl.task_name == "run_search" and dl.payload == {"profile_id": pid} and "db down" in dl.error
    auth_notes = client.get("/api/notifications", headers=auth).json()
    assert any("failed repeatedly" in n["title"] for n in auth_notes)
    assert count(RunLock) == 0


def test_stale_running_run_marked_failed_after_worker_restart(client, auth, web):
    pid = make_profile(client, auth)["id"]
    with SessionLocal() as db:
        db.add(SearchRun(user_id=1, search_profile_id=pid, status="running", started_at=utcnow() - timedelta(hours=30)))
        db.commit()
    scheduler.run_due()
    with SessionLocal() as db:
        statuses = [r.status for r in db.scalars(select(SearchRun).order_by(SearchRun.id))]
    assert statuses[0] == "failed" and len(statuses) == 2  # recovered, then a fresh run executed


def test_manual_run_endpoint_returns_task_id_and_is_pollable(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    pid = make_profile(client, auth)["id"]
    r = client.post(f"/api/search-profiles/{pid}/run", headers=auth)
    assert r.status_code == 202
    run = client.get(r.json()["poll"], headers=auth).json()  # TestClient runs background tasks before returning
    assert run["status"] == "completed" and run["stats"]["new_jobs"] == 1
    assert client.get(r.json()["poll"], headers=register(client, "z@example.com")).status_code == 404


# ---------------- automation policy ----------------
def test_discovery_only_prepares_nothing(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    client.patch("/api/automation-settings", headers=auth, json={"mode": "discovery_only"})
    run = run_now(make_profile(client, auth)["id"])
    assert run.stats.get("resumes_generated", 0) == 0 and count(Application) == 0


def test_default_mode_prepares_for_review_and_never_submits(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    run = run_now(make_profile(client, auth)["id"])
    assert run.stats["applications_prepared"] == 1 and run.stats.get("submitted", 0) == 0
    a = client.get("/api/applications", headers=auth).json()["items"][0]
    assert a["status"] == "awaiting_user_approval" and a["date_applied"] is None
    rep = client.get("/api/reports/daily", headers=auth).json()[0]
    assert rep["ready_for_review"] == 1 and rep["resumes_generated"] == 1
    assert {n["notification_type"] for n in client.get("/api/notifications", headers=auth).json()} >= {"report", "ready_to_review"}


def test_auto_submit_requires_explicit_consent_then_submits_once(client, auth, web):
    r = client.patch("/api/automation-settings", headers=auth, json={"mode": "auto_submit_authorized"})
    assert r.status_code == 422 and "consent" in r.text
    ok = client.patch("/api/automation-settings", headers=auth, json={"mode": "auto_submit_authorized", "consent_to_auto_submit": True})
    assert ok.status_code == 200 and ok.json()["auto_submit_consent_at"]
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    pid = make_profile(client, auth)["id"]
    run = run_now(pid)
    assert run.stats["submitted"] == 1
    run_now(pid)
    run_now(pid)
    a = client.get("/api/applications", headers=auth).json()
    assert a["total"] == 1 and a["items"][0]["status"] == "submitted"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Application)) == 1
    # leaving auto mode revokes consent
    off = client.patch("/api/automation-settings", headers=auth, json={"mode": "prepare_for_review"}).json()
    assert off["auto_submit_consent_at"] is None


def test_auto_submit_never_runs_while_paused(client, auth, web):
    client.patch("/api/automation-settings", headers=auth, json={"mode": "auto_submit_authorized", "consent_to_auto_submit": True})
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    pid = make_profile(client, auth)["id"]
    client.patch("/api/automation-settings", headers=auth, json={"paused": True})
    run = run_now(pid)
    assert run.stats.get("submitted", 0) == 0 and count(Application) == 0
    from app.services import applications as appsvc
    from app.models import User
    with SessionLocal() as db:
        u = db.scalar(select(User))
        try:
            appsvc.submit(db, u, 1, "scheduler")
            raise AssertionError("scheduler submit must be refused while paused")
        except appsvc.ApplicationError as e:
            assert e.code in ("automation_disabled", "not_found")


def test_dashboard_uses_real_database_values(client, auth, web):
    d0 = client.get("/api/dashboard", headers=auth).json()
    assert d0["total_jobs_discovered"] == 0 and d0["last_successful_run"] is None
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer"), gh_job(2, "Software Engineer Senior", days_ago=40)]
    run_now(make_profile(client, auth)["id"])
    d = client.get("/api/dashboard", headers=auth).json()
    assert d["total_jobs_discovered"] == 2 and d["matching_jobs"] == 1 and d["new_jobs_24h"] == 2
    assert d["ready_for_review_or_apply"] == 1 and d["search_runs_completed"] == 1 and d["last_successful_run"]
    assert d["next_scheduled_search"] and d["recent_activity"][0]["event"] == "application_prepared"
