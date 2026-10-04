import base64
import hashlib
import secrets
import uuid
from datetime import timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from .config import get_settings
from .db import utcnow

_ph = PasswordHasher()
ALGO = "HS256"


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_token(subject: int, purpose: str = "access", minutes: int | None = None, extra: dict | None = None) -> tuple[str, str]:
    s = get_settings()
    jti = uuid.uuid4().hex
    exp = utcnow() + timedelta(minutes=minutes or s.access_token_minutes)
    payload = {"sub": str(subject), "jti": jti, "exp": exp, "purpose": purpose, **(extra or {})}
    return jwt.encode(payload, s.secret_key, algorithm=ALGO), jti


def decode_token(token: str, purpose: str = "access") -> dict | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=[ALGO])
    except JWTError:
        return None
    if data.get("purpose") != purpose:
        return None
    return data


def random_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().secret_key.encode()).digest())
    return Fernet(key)


class Storage:
    """Encrypted-at-rest local file storage (swap for S3 by keeping this interface)."""

    def __init__(self):
        self.root = Path(get_settings().storage_dir)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        plain = lambda x: str(x).removeprefix("\\\\?\\")  # noqa: E731 (Windows long paths come back with a \\?\ prefix)
        if not plain(p).startswith(plain(self.root.resolve())):
            raise ValueError("invalid storage key")
        return p

    def put(self, user_id: int, data: bytes, suffix: str) -> str:
        key = f"{user_id}/{uuid.uuid4().hex}{suffix}"
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_fernet().encrypt(data))
        return key

    def get(self, key: str) -> bytes:
        return _fernet().decrypt(self._path(key).read_bytes())

    def delete(self, key: str | None) -> None:
        if key:
            try:
                self._path(key).unlink(missing_ok=True)
            except OSError:
                pass


def storage() -> Storage:
    return Storage()


def signed_download_token(user_id: int, key: str, filename: str, minutes: int = 5) -> str:
    return create_token(user_id, "download", minutes, {"key": key, "fn": filename})[0]
