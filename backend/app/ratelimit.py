import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

_hits: dict[str, deque] = defaultdict(deque)
_lock = Lock()


def reset() -> None:
    with _lock:
        _hits.clear()


def allow(bucket: str, limit: int, window: float = 60.0) -> bool:
    now = time.monotonic()
    with _lock:
        q = _hits[bucket]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-process limiter. Use a Redis-backed limiter when running multiple API replicas."""

    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        ip = request.client.host if request.client else "unknown"
        path = request.url.path
        is_auth = path.startswith("/api/auth/") and request.method == "POST"
        limit = s.rate_limit_auth_per_min if is_auth else s.rate_limit_default_per_min
        bucket = f"{'auth' if is_auth else 'api'}:{ip}"
        if not allow(bucket, limit):
            return JSONResponse({"error": {"code": "rate_limited", "message": "Too many requests"}},
                                status_code=429, headers={"Retry-After": "60"})
        return await call_next(request)
