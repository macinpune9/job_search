import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditEvent, AutomationSettings, CandidateProfile, User
from app.routers import oauth
from .conftest import PASSWORD, register


class FakeGoogle:
    def __init__(self):
        self.info = {"sub": "g-123", "email": "gina@example.com", "email_verified": True, "name": "Gina G"}
        self.token_status = 200
        self.token_form = None

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            self.token_form = parse_qs(req.content.decode())
            return httpx.Response(self.token_status, json={"access_token": "at-1"})
        if req.url.host == "openidconnect.googleapis.com":
            assert req.headers["authorization"] == "Bearer at-1"
            return httpx.Response(200, json=self.info)
        return httpx.Response(404)


@pytest.fixture()
def google(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(s, "google_client_secret", "csecret")
    g = FakeGoogle()
    oauth.set_http_factory(lambda: httpx.Client(transport=httpx.MockTransport(g.handler)))
    yield g
    oauth.set_http_factory(lambda: httpx.Client(timeout=20))


def start(client):
    r = client.get("/api/auth/google/login", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return r, q


def finish(client, state, code="abc"):
    return client.get("/api/auth/google/callback", params={"code": code, "state": state}, follow_redirects=False)


def token_of(resp):
    loc = resp.headers["location"]
    assert "/auth/callback#token=" in loc, loc
    return loc.split("#token=")[1]


def test_not_configured_hides_button_and_login_redirects_with_error(client):
    assert client.get("/api/auth/providers").json() == {"google": False}
    r = client.get("/api/auth/google/login", follow_redirects=False)
    assert r.headers["location"].endswith("/login?error=google_not_configured")


def test_login_redirect_has_state_and_pkce(client, google):
    assert client.get("/api/auth/providers").json() == {"google": True}
    r, q = start(client)
    assert r.headers["location"].startswith("https://accounts.google.com/")
    assert q["client_id"] == ["cid.apps.googleusercontent.com"] and q["code_challenge_method"] == ["S256"]
    assert q["scope"] == ["openid email profile"] and q["state"][0]
    assert "httponly" in r.headers["set-cookie"].lower()
    assert "csecret" not in r.headers["location"]


def test_full_flow_creates_user_and_issues_working_session(client, google):
    r, q = start(client)
    resp = finish(client, q["state"][0])
    tok = token_of(resp)
    me = client.get("/api/users/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["email"] == "gina@example.com" and me["email_verified"] is True
    # PKCE: verifier sent to Google hashes to the challenge from step 1
    v = google.token_form["code_verifier"][0]
    assert base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode() == q["code_challenge"][0]
    assert google.token_form["client_secret"] == ["csecret"] and google.token_form["code"] == ["abc"]
    with SessionLocal() as db:
        u = db.scalar(select(User))
        assert u.password_hash is None and u.external_identity == "google:g-123"
        assert db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == u.id)).full_name == "Gina G"
        assert db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == u.id))
        assert "csecret" not in str([a.details for a in db.scalars(select(AuditEvent))])
    # password login is impossible for a Google-only account
    assert client.post("/api/auth/login", json={"email": "gina@example.com", "password": PASSWORD}).status_code == 401


def test_second_login_reuses_account(client, google):
    for _ in range(2):
        _, q = start(client)
        token_of(finish(client, q["state"][0]))
    with SessionLocal() as db:
        assert len(db.scalars(select(User)).all()) == 1


def test_state_mismatch_or_missing_cookie_rejected(client, google):
    _, q = start(client)
    assert finish(client, "forged").headers["location"].endswith("error=invalid_state")
    fresh = type(client)(client.app)  # no cookie jar
    assert finish(fresh, q["state"][0]).headers["location"].endswith("error=invalid_state")
    assert google.token_form is None  # never reached Google


def test_denied_and_token_failure(client, google):
    assert client.get("/api/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False).headers["location"].endswith("google_denied")
    _, q = start(client)
    google.token_status = 400
    assert finish(client, q["state"][0]).headers["location"].endswith("token_exchange_failed")


def test_unverified_google_email_rejected(client, google):
    google.info["email_verified"] = False
    _, q = start(client)
    assert finish(client, q["state"][0]).headers["location"].endswith("email_not_verified")
    with SessionLocal() as db:
        assert db.scalars(select(User)).all() == []


def test_links_existing_verified_account_and_keeps_password(client, google):
    register(client, "gina@example.com")
    with SessionLocal() as db:
        db.scalar(select(User)).email_verified = True
        db.commit()
    _, q = start(client)
    token_of(finish(client, q["state"][0]))
    assert client.post("/api/auth/login", json={"email": "gina@example.com", "password": PASSWORD}).status_code == 200
    with SessionLocal() as db:
        assert len(db.scalars(select(User)).all()) == 1 and db.scalar(select(User)).external_identity == "google:g-123"


def test_linking_unverified_password_account_drops_attackers_password(client, google):
    register(client, "gina@example.com")  # e.g. pre-registered by someone who doesn't own the mailbox
    _, q = start(client)
    token_of(finish(client, q["state"][0]))
    assert client.post("/api/auth/login", json={"email": "gina@example.com", "password": PASSWORD}).status_code == 401


def test_conflicting_google_identity_and_disabled_account(client, google):
    with SessionLocal() as db:
        db.add(User(email="gina@example.com", external_identity="google:someone-else", email_verified=True))
        db.commit()
    _, q = start(client)
    assert finish(client, q["state"][0]).headers["location"].endswith("account_conflict")
    with SessionLocal() as db:
        u = db.scalar(select(User))
        u.external_identity, u.account_status = "google:g-123", "disabled"
        db.commit()
    _, q = start(client)
    assert finish(client, q["state"][0]).headers["location"].endswith("account_disabled")
