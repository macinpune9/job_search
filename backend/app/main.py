import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal
from .ratelimit import RateLimitMiddleware
from .routers import applications, auth, insights, jobs, misc, oauth, resumes, searches, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# Never log request bodies/headers; uvicorn access logs include paths only.

app = FastAPI(title="JobPilot API", version="0.1.0",
              description="Job discovery, ATS resume tailoring and application tracking. All endpoints except /api/auth/* require a bearer token.")
s = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RateLimitMiddleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


def _err(status: int, code: str, message, details=None):
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status)


@app.exception_handler(HTTPException)
async def http_exc(_: Request, exc: HTTPException):
    d = exc.detail
    if isinstance(d, dict):
        return _err(exc.status_code, d.get("code", f"http_{exc.status_code}"), d.get("message", "Error"), d)
    return _err(exc.status_code, f"http_{exc.status_code}", d)


@app.exception_handler(RequestValidationError)
async def validation_exc(_: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return _err(422, "validation_error", "Request validation failed", details)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logging.getLogger("jobpilot").exception("unhandled error")
    return _err(500, "internal_error", "Something went wrong")


for r in (auth.router, oauth.router, insights.router, users.router, resumes.router, searches.router, jobs.router, applications.router, misc.router):
    app.include_router(r)


@app.get("/health")
def health():
    with SessionLocal() as db:
        db.execute(text("select 1"))
    return {"status": "ok"}
