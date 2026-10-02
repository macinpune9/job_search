from collections import Counter

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import connectors
from ..db import SessionLocal, get_db, utcnow
from ..deps import audit, current_user
from ..models import (ConnectorHealth, Job, Resume, SearchProfile, SearchRun, SourceCursor, User, as_dict)
from ..services import engine, keywords, matching
from ..services import scheduler as sched

router = APIRouter(prefix="/api", tags=["search"])

EMPLOYMENT = {"permanent", "part_time", "fixed_term", "temporary", "freelance", "contract_to_hire", "internship"}
REMOTE = {"remote", "hybrid", "onsite"}


class Keyword(BaseModel):
    term: str = Field(min_length=1, max_length=80)
    kind: str = "skill"
    required: bool = False
    excluded: bool = False
    synonyms: list[str] = []
    weight: float = Field(1.0, ge=0, le=10)


class SourceRef(BaseModel):
    source: str
    board: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")

    @field_validator("source")
    @classmethod
    def known(cls, v):
        if v not in connectors.REGISTRY:
            raise ValueError(f"Unknown source. Available: {', '.join(connectors.REGISTRY)}")
        return v


class ProfileIn(BaseModel):
    profile_name: str = Field(min_length=1, max_length=200)
    keywords: list[Keyword] = []
    match_mode: str = Field("weighted", pattern="^(and|or|weighted)$")
    exclusions: dict = {}
    employment_types: list[str] = []
    role_preferences: dict = {}
    salary_preferences: dict = {}
    location_preferences: dict = {}
    remote_preferences: list[str] = []
    other_filters: dict = {}
    sources: list[SourceRef] = []
    resume_id: int | None = None
    date_lookback_days: int = Field(30, ge=1, le=365)
    unknown_date_policy: str = Field("include", pattern="^(include|exclude)$")
    min_match_score: float = Field(40, ge=0, le=100)
    overlap_hours: int = Field(48, ge=0, le=24 * 14)
    active: bool = True

    @field_validator("employment_types")
    @classmethod
    def _emp(cls, v):
        bad = set(v) - EMPLOYMENT
        if bad:
            raise ValueError(f"Unknown employment types: {sorted(bad)}")
        return v

    @field_validator("remote_preferences")
    @classmethod
    def _rem(cls, v):
        bad = set(v) - REMOTE
        if bad:
            raise ValueError(f"Unknown work modes: {sorted(bad)}")
        return v

    @field_validator("salary_preferences")
    @classmethod
    def _sal(cls, v):
        if v.get("min") is not None and (not v.get("currency") or not v.get("period")):
            raise ValueError("Salary needs a currency and a period (year/month/week/day/hour) so it can be compared safely")
        return v


class ProfilePatch(ProfileIn):
    profile_name: str | None = None  # type: ignore[assignment]


def owned_profile(db: Session, user: User, pid: int) -> SearchProfile:
    p = db.get(SearchProfile, pid)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Search profile not found")
    return p


def _out(p: SearchProfile) -> dict:
    return as_dict(p)


@router.get("/search-profiles")
def list_profiles(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_out(p) for p in db.scalars(select(SearchProfile).where(SearchProfile.user_id == user.id).order_by(SearchProfile.id))]


@router.post("/search-profiles", status_code=201)
def create_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump()
    if data["resume_id"]:
        r = db.get(Resume, data["resume_id"])
        if not r or r.user_id != user.id:
            raise HTTPException(422, "Unknown resume")
    p = SearchProfile(user_id=user.id, **data)
    db.add(p)
    db.commit()
    return _out(p)


@router.get("/search-profiles/{pid}")
def get_profile(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(owned_profile(db, user, pid))


@router.patch("/search-profiles/{pid}")
def patch_profile(pid: int, body: ProfilePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = owned_profile(db, user, pid)
    data = body.model_dump(exclude_unset=True)
    if data.get("resume_id"):
        r = db.get(Resume, data["resume_id"])
        if not r or r.user_id != user.id:
            raise HTTPException(422, "Unknown resume")
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    return _out(p)


@router.delete("/search-profiles/{pid}", status_code=204)
def delete_profile(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_profile(db, user, pid))
    db.commit()


@router.get("/keywords/suggest")
def suggest_keywords(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    if not r.structured_profile:
        raise HTTPException(422, "Resume has not been parsed")
    return {"keywords": keywords.suggest(r.structured_profile),
            "note": "Suggestions are optional. Nothing is required unless you mark it required."}


class Preview(BaseModel):
    keywords: list[Keyword]
    match_mode: str = "weighted"
    exclusions: dict = {}


@router.post("/search-profiles/{pid}/keyword-preview")
def keyword_preview(pid: int, body: Preview, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Dry-run the keyword settings against jobs already discovered for this user (no persistence)."""
    p = owned_profile(db, user, pid)
    probe = SearchProfile(user_id=user.id, profile_name="preview", keywords=[k.model_dump() for k in body.keywords],
                          match_mode=body.match_mode, exclusions=body.exclusions, employment_types=p.employment_types,
                          role_preferences=p.role_preferences, salary_preferences=p.salary_preferences,
                          location_preferences=p.location_preferences, remote_preferences=p.remote_preferences,
                          date_lookback_days=p.date_lookback_days, unknown_date_policy=p.unknown_date_policy,
                          min_match_score=p.min_match_score)
    from ..models import JobMatch
    job_ids = [m for m in db.scalars(select(JobMatch.job_id).where(JobMatch.user_id == user.id).limit(500))]
    r = engine.pick_resume(db, p)
    reasons, qualified = Counter(), 0
    for j in db.scalars(select(Job).where(Job.id.in_(job_ids))) if job_ids else []:
        mr = matching.evaluate(j, probe, r.structured_profile if r else None)
        if mr.qualified:
            qualified += 1
        for e in mr.exclusions:
            reasons[e["code"]] += 1
    return {"jobs_evaluated": len(job_ids), "would_qualify": qualified, "exclusion_reasons": dict(reasons),
            "explanation": {"mode": body.match_mode, "required": [k.term for k in body.keywords if k.required and not k.excluded],
                            "excluded": [k.term for k in body.keywords if k.excluded],
                            "optional": [k.term for k in body.keywords if not k.required and not k.excluded]}}


# ---------------- runs ----------------
def _run_in_background(profile_id: int, run_id: int) -> None:
    owner = f"manual-{run_id}"
    with SessionLocal() as db:
        if not sched.acquire_lock(db, f"search:{profile_id}", owner):
            run = db.get(SearchRun, run_id)
            run.status, run.completed_at, run.error_summary = "failed", utcnow(), "another run is already in progress"
            db.commit()
            return
    try:
        with SessionLocal() as db:
            try:
                engine.run_search(db, profile_id, "manual", run_id)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                run = db.get(SearchRun, run_id)
                run.status, run.completed_at, run.error_summary = "failed", utcnow(), f"{type(e).__name__}"
                db.commit()
    finally:
        with SessionLocal() as db:
            sched.release_lock(db, f"search:{profile_id}", owner)


@router.post("/search-profiles/{pid}/run", status_code=202)
def run_profile(pid: int, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = owned_profile(db, user, pid)
    if db.scalar(select(SearchRun.id).where(SearchRun.search_profile_id == p.id, SearchRun.status == "running")):
        raise HTTPException(409, "A search is already running for this profile")
    run = SearchRun(user_id=user.id, search_profile_id=p.id, trigger="manual")
    db.add(run)
    db.commit()
    bg.add_task(_run_in_background, p.id, run.id)
    return {"task_id": run.id, "status": "running", "poll": f"/api/search-runs/{run.id}"}


@router.get("/search-runs")
def list_runs(user: User = Depends(current_user), db: Session = Depends(get_db), limit: int = 20):
    return [as_dict(r) for r in db.scalars(select(SearchRun).where(SearchRun.user_id == user.id).order_by(SearchRun.id.desc()).limit(min(limit, 100)))]


@router.get("/search-runs/{rid}")
def get_run(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(SearchRun, rid)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Run not found")
    return as_dict(r)


@router.get("/sources")
def sources(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Source registry with live health and which of the user's configured boards use each source."""
    health = {h.source_name: h for h in db.scalars(select(ConnectorHealth))}
    mine = Counter()
    for p in db.scalars(select(SearchProfile).where(SearchProfile.user_id == user.id)):
        for s in p.sources or []:
            mine[s["source"]] += 1
    out = []
    for name, cls in connectors.REGISTRY.items():
        hs = [h for k, h in health.items() if k.startswith(name + ":")]
        out.append({"name": name, "display_name": cls.display_name, "requires_credentials": cls.requires_credentials,
                    "compliance_note": cls.compliance_note, "configured_boards": mine[name],
                    "last_success_at": max((h.last_success_at for h in hs if h.last_success_at), default=None),
                    "last_error": next((h.last_error for h in hs if h.last_error), None),
                    "status": ("unavailable" if hs and all(h.consecutive_failures for h in hs) else "ok" if hs else "unused")})
    return out
