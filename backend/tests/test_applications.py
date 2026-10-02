import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.models import Application, ApplicationEvent, User
from app.services import applications as appsvc
from .conftest import gh_job, make_profile, register, run_now, upload


def setup_job(client, auth, web, title="Software Engineer"):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, title)]
    run_now(make_profile(client, auth)["id"])
    return client.get("/api/jobs", headers=auth).json()["items"][0]["id"]


def prepared(client, auth, web):
    """Default automation mode (prepare_for_review) prepares the application during the search run."""
    jid = setup_job(client, auth, web)
    r = client.post(f"/api/jobs/{jid}/prepare-application", headers=auth, json={}).json()
    return jid, r["application"]["id"]


def events(aid):
    with SessionLocal() as db:
        return [(e.event_type, e.new_status, e.actor_type) for e in
                db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == aid).order_by(ApplicationEvent.id))]


class Counting(appsvc.Submitter):
    name = "counting"

    def __init__(self, script=None, delay=0.0):
        self.calls, self.script, self.delay, self.lock = 0, list(script or []), delay, threading.Lock()

    def supports(self, job):
        return True

    def submit(self, package, key):
        with self.lock:
            self.calls += 1
            step = self.script.pop(0) if self.script else None
        time.sleep(self.delay)
        if isinstance(step, Exception):
            raise step
        return step or appsvc.SubmissionResult(True, reference=f"REF-{key[:6]}")


def user_obj(email="a@example.com"):
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.email == email))


def test_happy_path_links_exact_resume_version_and_records_history(client, auth, web):
    jid, aid = prepared(client, auth, web)
    a = client.get(f"/api/applications/{aid}", headers=auth).json()
    assert a["status"] == "awaiting_user_approval" and a["resume_version"]["validation_results"]["passed"]
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).status_code == 409  # not approved yet
    assert client.post(f"/api/applications/{aid}/approve", headers=auth).json()["status"] == "ready_to_apply"
    s = client.post(f"/api/applications/{aid}/submit", headers=auth).json()
    assert s["status"] == "submitted" and s["external_reference"].startswith("SANDBOX-") and s["submission_method"] == "sandbox"
    d = client.get(f"/api/applications/{aid}", headers=auth).json()
    assert d["resume_version"]["id"] == a["resume_version"]["id"] and d["resume_version"]["locked"] and d["resume_version"]["approved_at"]
    assert [e["event_type"] for e in d["events"]] == ["application_prepared", "user_approved", "submission_started", "submission_confirmed"]
    assert d["job"]["description"] and d["job"]["listings"]  # original description + source links preserved
    # a second submit is refused and does not add events
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).status_code == 409
    assert len(events(aid)) == 4


def test_prepare_is_idempotent_one_application_per_job(client, auth, web):
    jid, aid = prepared(client, auth, web)
    r = client.post(f"/api/jobs/{jid}/prepare-application", headers=auth, json={}).json()
    assert r["created"] is False and r["application"]["id"] == aid
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Application)) == 1


def test_db_constraint_blocks_duplicate_applications(client, auth, web):
    jid, aid = prepared(client, auth, web)
    with SessionLocal() as db:
        db.add(Application(user_id=1, job_id=jid, status="x", idempotency_key="different-key"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_concurrent_workers_submit_exactly_once(client, auth, web):
    jid, aid = prepared(client, auth, web)
    client.post(f"/api/applications/{aid}/approve", headers=auth)
    sub = Counting(delay=0.2)
    appsvc.register_submitter(sub)
    results, errors = [], []

    def worker():
        with SessionLocal() as db:
            try:
                results.append(appsvc.submit(db, user_obj(), aid, "user").status)
            except appsvc.ApplicationError as e:
                errors.append(e.code)

    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sub.calls == 1 and results == ["submitted"] and errors.count("not_claimable") == 7
    with SessionLocal() as db:
        assert db.get(Application, aid).attempts == 1


def test_transient_failure_can_be_retried_without_double_submit(client, auth, web):
    jid, aid = prepared(client, auth, web)
    client.post(f"/api/applications/{aid}/approve", headers=auth)
    sub = Counting(script=[appsvc.SubmissionResult(False, error="503 from employer", transient=True)])
    appsvc.register_submitter(sub)
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).json()["status"] == "application_failed"
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).json()["status"] == "submitted"
    assert sub.calls == 2
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).status_code == 409 and sub.calls == 2
    types = [e[0] for e in events(aid)]
    assert types.count("submission_failed") == 1 and types.count("submission_confirmed") == 1


def test_unknown_outcome_is_never_blindly_retried(client, auth, web):
    jid, aid = prepared(client, auth, web)
    client.post(f"/api/applications/{aid}/approve", headers=auth)
    sub = Counting(script=[RuntimeError("connection reset after send")])
    appsvc.register_submitter(sub)
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).json()["status"] == "submission_confirmation_pending"
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).status_code == 409 and sub.calls == 1
    # the user can later verify with the employer and attest
    r = client.patch(f"/api/applications/{aid}", headers=auth, json={"status": "submitted"})
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    assert events(aid)[-1][0] == "user_attested_submission"


def test_unconfirmed_response_is_not_marked_submitted(client, auth, web):
    jid, aid = prepared(client, auth, web)
    client.post(f"/api/applications/{aid}/approve", headers=auth)
    appsvc.register_submitter(Counting(script=[appsvc.SubmissionResult(False)]))
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).json()["status"] == "submission_confirmation_pending"


def test_worker_crash_recovery(client, auth, web):
    jid, aid = prepared(client, auth, web)
    with SessionLocal() as db:
        a = db.get(Application, aid)
        a.status, a.updated_at = "application_in_progress", utcnow() - timedelta(hours=2)
        db.commit()
        assert appsvc.recover_stale(db) == 1
        assert db.get(Application, aid).status == "submission_confirmation_pending"


def test_manual_fallback_package_when_no_integration(client, auth, web, monkeypatch):
    monkeypatch.setattr(get_settings(), "sandbox_mode", False)
    jid, aid = prepared(client, auth, web)
    a = client.get(f"/api/applications/{aid}", headers=auth).json()
    assert a["status"] == "manual_application_required"
    pkg = a["package"]
    assert pkg["application_url"].startswith("https://boards.greenhouse.io") and pkg["resume_version_id"] == a["resume_version"]["id"]
    assert pkg["checklist"] and pkg["reason_manual_action"] and pkg["suggested_answers"]["email"] == "a@example.com"
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).status_code == 422
    r = client.patch(f"/api/applications/{aid}", headers=auth, json={"status": "submitted", "notes": "applied via site"})
    assert r.json()["status"] == "submitted" and r.json()["submission_method"] == "manual"
    assert ("user_attested_submission", "submitted", "user") in events(aid)
    assert client.patch(f"/api/applications/{aid}", headers=auth, json={"status": "ready_to_apply"}).status_code == 422  # no arbitrary jumps


def test_validation_failure_blocks_approval_until_fixed(client, auth, web):
    jid, aid = prepared(client, auth, web)
    rv = client.get(f"/api/applications/{aid}", headers=auth).json()["resume_version"]
    bad = rv["generated_content"]
    bad["skills"].append("Kubernetes")
    nv = client.post(f"/api/resume-versions/{rv['id']}/edit", headers=auth, json={"content": bad}).json()
    assert client.patch(f"/api/applications/{aid}", headers=auth, json={"resume_version_id": nv["id"]}).status_code == 200
    assert client.get(f"/api/applications/{aid}", headers=auth).json()["status"] == "resume_ready_for_review"
    r = client.post(f"/api/applications/{aid}/approve", headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    fixed = {**rv["generated_content"], "skills": [s for s in bad["skills"] if s != "Kubernetes"]}
    good = client.post(f"/api/resume-versions/{rv['id']}/edit", headers=auth, json={"content": fixed}).json()
    client.patch(f"/api/applications/{aid}", headers=auth, json={"resume_version_id": good["id"]})
    assert client.post(f"/api/applications/{aid}/approve", headers=auth).json()["status"] == "ready_to_apply"


def test_closed_listing_cannot_be_submitted(client, auth, web):
    jid, aid = prepared(client, auth, web)
    client.post(f"/api/applications/{aid}/approve", headers=auth)
    web.greenhouse["acme"] = []
    run_now(client.get("/api/search-profiles", headers=auth).json()[0]["id"])
    assert client.get(f"/api/applications/{aid}", headers=auth).json()["status"] == "closed_or_expired"
    assert client.post(f"/api/applications/{aid}/submit", headers=auth).status_code == 409


def test_resume_cannot_change_after_submission(client, auth, web):
    jid, aid = prepared(client, auth, web)
    client.post(f"/api/applications/{aid}/approve", headers=auth)
    client.post(f"/api/applications/{aid}/submit", headers=auth)
    rv = client.get(f"/api/applications/{aid}", headers=auth).json()["resume_version"]
    nv = client.post(f"/api/resume-versions/{rv['id']}/edit", headers=auth, json={"content": rv["generated_content"]}).json()
    assert client.patch(f"/api/applications/{aid}", headers=auth, json={"resume_version_id": nv["id"]}).status_code == 409
    assert client.get(f"/api/applications/{aid}", headers=auth).json()["resume_version"]["id"] == rv["id"]
    # the used resume (and its versions) can't be deleted out from under the record
    rid = client.get("/api/resumes", headers=auth).json()[0]["id"]
    assert client.delete(f"/api/resumes/{rid}", headers=auth).status_code == 409


def test_cover_letter_versioned_with_application(client, auth, web):
    client.patch("/api/automation-settings", headers=auth, json={"mode": "discovery_only"})
    jid = setup_job(client, auth, web)
    r = client.post(f"/api/jobs/{jid}/prepare-application", headers=auth, json={"cover_letter": True}).json()
    d = client.get(f"/api/applications/{r['application']['id']}", headers=auth).json()
    assert d["cover_letter"]["version_number"] == 1 and d["cover_letter"]["validation_results"]["passed"]
    assert "Jane Doe" in d["cover_letter"]["content"]


def test_history_search_filter_and_csv_export(client, auth, web):
    jid, aid = prepared(client, auth, web)
    client.patch(f"/api/applications/{aid}", headers=auth, json={"notes": "=HYPERLINK(\"http://evil\")"})
    assert client.get("/api/applications", headers=auth, params={"q": "software"}).json()["total"] == 1
    assert client.get("/api/applications", headers=auth, params={"q": "nomatch"}).json()["total"] == 0
    assert client.get("/api/applications", headers=auth, params={"status": "submitted"}).json()["total"] == 0
    row = client.get("/api/applications", headers=auth).json()["items"][0]
    assert row["company"] == "Acme" and row["resume_version"] and row["date_prepared"] and row["job_url"]
    csv = client.get("/api/applications/export.csv", headers=auth)
    assert csv.headers["content-type"].startswith("text/csv") and "Software Engineer" in csv.text
    assert "'=HYPERLINK" in csv.text  # formula injection neutralised


def test_applications_isolated_between_users(client, auth, web):
    jid, aid = prepared(client, auth, web)
    other = register(client, "b@example.com")
    for method, path in (("get", f"/api/applications/{aid}"), ("post", f"/api/applications/{aid}/approve"),
                         ("post", f"/api/applications/{aid}/submit"), ("patch", f"/api/applications/{aid}"),
                         ("post", f"/api/jobs/{jid}/prepare-application")):
        r = getattr(client, method)(path, headers=other, **({"json": {}} if method == "patch" else {}))
        assert r.status_code == 404, path
    assert client.get("/api/applications", headers=other).json()["total"] == 0


def test_event_log_is_append_only_across_status_updates(client, auth, web):
    jid, aid = prepared(client, auth, web)
    client.post(f"/api/applications/{aid}/approve", headers=auth)
    before = events(aid)
    client.patch(f"/api/applications/{aid}", headers=auth, json={"notes": "n"})
    after = events(aid)
    assert after[:len(before)] == before and len(after) == len(before) + 1
