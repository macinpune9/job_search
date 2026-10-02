import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import audit, current_user
from ..models import AutomationSettings, CandidateProfile, EmailToken, RevokedToken, User
from ..security import create_token, hash_password, hash_token, random_token, verify_password
from ..services.reports import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("jobpilot.auth")


def _check_password(pw: str) -> str:
    if len(pw) < 10 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise ValueError("Password must be at least 10 characters and include a letter and a digit")
    return pw


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    timezone: str = "UTC"

    @field_validator("password")
    @classmethod
    def strong(cls, v):
        return _check_password(v)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _issue_email_token(db: Session, user: User, purpose: str, hours: int) -> str:
    raw, h = random_token()
    db.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=h, expires_at=utcnow() + timedelta(hours=hours)))
    return raw


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        # Same response shape as success to limit account enumeration is impractical with a token flow; be explicit.
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password), timezone=body.timezone)
    db.add(user)
    db.flush()
    db.add(CandidateProfile(user_id=user.id))
    db.add(AutomationSettings(user_id=user.id))
    raw = _issue_email_token(db, user, "verify", 48)
    audit(db, user.id, "user_registered", "user", user.id)
    db.commit()
    send_email(email, "Verify your email", f"Verification token: {raw}")
    if get_settings().env != "production":
        log.info("DEV verification token for %s: %s", email, raw)
    return {"id": user.id, "email": user.email, "verification_required": get_settings().require_email_verification}


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else None)
    if not user or not ok or user.account_status != "active":
        audit(db, user.id if user else None, "login_failed")
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    if get_settings().require_email_verification and not user.email_verified:
        raise HTTPException(403, "Please verify your email before logging in")
    token, _ = create_token(user.id)
    audit(db, user.id, "login")
    db.commit()
    return TokenOut(access_token=token)


@router.post("/logout", status_code=204)
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.merge(RevokedToken(jti=request.state.jti, expires_at=request.state.token_exp))
    audit(db, user.id, "logout")
    db.commit()


class TokenIn(BaseModel):
    token: str


@router.post("/verify-email")
def verify_email(body: TokenIn, db: Session = Depends(get_db)):
    t = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(body.token), EmailToken.purpose == "verify"))
    if not t or t.used_at or t.expires_at < utcnow():
        raise HTTPException(400, "Invalid or expired token")
    t.used_at = utcnow()
    db.get(User, t.user_id).email_verified = True
    db.commit()
    return {"verified": True}


class ResetRequest(BaseModel):
    email: EmailStr


@router.post("/request-password-reset", status_code=202)
def request_reset(body: ResetRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.account_status == "active":
        raw = _issue_email_token(db, user, "reset", 1)
        db.commit()
        send_email(user.email, "Password reset", f"Reset token: {raw}")
        if get_settings().env != "production":
            log.info("DEV reset token for %s: %s", user.email, raw)
    return {"detail": "If the account exists, a reset email has been sent."}  # same response either way


class ResetIn(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def strong(cls, v):
        return _check_password(v)


@router.post("/reset-password")
def reset_password(body: ResetIn, db: Session = Depends(get_db)):
    t = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(body.token), EmailToken.purpose == "reset"))
    if not t or t.used_at or t.expires_at < utcnow():
        raise HTTPException(400, "Invalid or expired token")
    t.used_at = utcnow()
    db.get(User, t.user_id).password_hash = hash_password(body.new_password)
    audit(db, t.user_id, "password_reset")
    db.commit()
    return {"reset": True}
