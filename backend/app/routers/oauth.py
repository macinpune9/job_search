"""Google sign-in (OpenID Connect authorization-code flow with PKCE).

Flow: /google/login sets an httpOnly cookie holding the PKCE verifier + nonce and redirects to Google with
state=nonce. /google/callback checks state against the cookie (CSRF), exchanges the code server-to-server,
reads the userinfo for that access token, and requires a Google-verified email. The session token is handed to
the SPA in the URL *fragment* (never sent to servers or logged).
"""
import base64
import hashlib
import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import audit
from ..models import AutomationSettings, CandidateProfile, User
from ..security import create_token, decode_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("jobpilot.oauth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
COOKIE = "oauth_tx"

# Replaceable in tests so no real network call is made.
_http_factory = lambda: httpx.Client(timeout=get_settings().http_timeout_seconds)  # noqa: E731


def set_http_factory(f) -> None:
    global _http_factory
    _http_factory = f


def configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


@router.get("/providers")
def providers():
    return {"google": configured()}


def _fail(reason: str) -> RedirectResponse:
    r = RedirectResponse(f"{get_settings().frontend_url}/login?error={reason}", status_code=302)
    r.delete_cookie(COOKIE)
    return r


@router.get("/google/login")
def google_login():
    s = get_settings()
    if not configured():
        return RedirectResponse(f"{s.frontend_url}/login?error=google_not_configured", status_code=302)
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(24)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = urlencode({"client_id": s.google_client_id, "redirect_uri": s.google_redirect_uri, "response_type": "code",
                   "scope": "openid email profile", "state": nonce, "code_challenge": challenge,
                   "code_challenge_method": "S256", "prompt": "select_account"})
    resp = RedirectResponse(f"{AUTH_URL}?{q}", status_code=302)
    tx, _ = create_token(0, "oauth_tx", 10, {"v": verifier, "n": nonce})
    resp.set_cookie(COOKIE, tx, max_age=600, httponly=True, samesite="lax", secure=s.env == "production", path="/api/auth")
    return resp


@router.get("/google/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                    db: Session = Depends(get_db)):
    s = get_settings()
    if not configured():
        return _fail("google_not_configured")
    if error or not code or not state:
        return _fail("google_denied")
    tx = decode_token(request.cookies.get(COOKIE, ""), "oauth_tx")
    if not tx or not secrets.compare_digest(str(tx.get("n", "")), state):
        return _fail("invalid_state")
    try:
        with _http_factory() as http:
            tr = http.post(TOKEN_URL, data={"code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
                                            "redirect_uri": s.google_redirect_uri, "grant_type": "authorization_code",
                                            "code_verifier": tx["v"]})
            if tr.status_code != 200:
                return _fail("token_exchange_failed")
            ur = http.get(USERINFO_URL, headers={"Authorization": f"Bearer {tr.json().get('access_token', '')}"})
            if ur.status_code != 200:
                return _fail("userinfo_failed")
            info = ur.json()
    except (httpx.HTTPError, ValueError):
        return _fail("google_unreachable")

    sub, email = info.get("sub"), (info.get("email") or "").lower()
    if not sub or not email or info.get("email_verified") is not True:
        return _fail("email_not_verified")
    ident = f"google:{sub}"

    user = db.scalar(select(User).where(User.external_identity == ident))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            if user.external_identity and user.external_identity != ident:
                return _fail("account_conflict")
            if not user.email_verified:
                # Pre-hijack defence: a password someone set before verifying the address must not survive linking.
                user.password_hash = None
            user.external_identity, user.email_verified = ident, True
            audit(db, user.id, "oauth_linked", "user", user.id, provider="google")
        else:
            user = User(email=email, external_identity=ident, email_verified=True, password_hash=None)
            db.add(user)
            db.flush()
            db.add(CandidateProfile(user_id=user.id, full_name=info.get("name")))
            db.add(AutomationSettings(user_id=user.id))
            audit(db, user.id, "user_registered", "user", user.id, provider="google")
    if user.account_status != "active":
        db.commit()
        return _fail("account_disabled")
    audit(db, user.id, "login", provider="google")
    db.commit()
    token, _ = create_token(user.id)
    resp = RedirectResponse(f"{s.frontend_url}/auth/callback#token={token}", status_code=302)
    resp.delete_cookie(COOKIE, path="/api/auth")
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp
