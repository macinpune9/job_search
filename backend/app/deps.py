from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditEvent, RevokedToken, User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(401, "Not authenticated")
    data = decode_token(cred.credentials)
    if not data or db.get(RevokedToken, data["jti"]):
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, int(data["sub"]))
    if not user or user.account_status != "active":
        raise HTTPException(401, "Account unavailable")
    request.state.jti = data["jti"]
    request.state.token_exp = datetime.fromtimestamp(data["exp"], tz=timezone.utc)
    return user


def audit(db: Session, user_id: int | None, event_type: str, entity_type: str | None = None,
          entity_id: int | None = None, **details) -> None:
    """Audit log. Callers must not pass personal data or secrets in details."""
    db.add(AuditEvent(user_id=user_id, event_type=event_type, entity_type=entity_type,
                      entity_id=entity_id, details=details))
