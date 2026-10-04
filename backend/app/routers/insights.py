from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import audit, current_user
from ..models import AutomationSettings, CandidateProfile, Resume, SearchProfile, User, as_dict
from ..services import ai_match, insights, llm
from ..services.textutil import sha

router = APIRouter(prefix="/api", tags=["insights"])


def snapshot_for(db: Session, user: User, resume: Resume, use_ai: bool, refresh: bool = False) -> dict:
    """Career snapshot for a resume. Rules always; AI (cached) when requested and permitted."""
    if not resume.structured_profile:
        raise HTTPException(422, "This resume has not been parsed yet")
    prof = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    linkedin = prof.linkedin_data if prof else None
    rules = insights.compute(resume.structured_profile, linkedin)
    out = rules
    if use_ai:
        client = llm.llm_for_user(db, user.id)
        if client is None:
            raise HTTPException(422, "AI features are off. Enable them in Automation Settings (needs a configured AI provider).")
        key = sha(ai_match.facts_hash(resume.structured_profile), str(sorted((linkedin or {}).items(), key=str)), get_settings().ai_model)
        cached = resume.insights if isinstance(resume.insights, dict) else None
        if cached and cached.get("key") == key and not refresh:
            out = cached["data"]
        else:
            try:
                ai = client.insights(llm.facts_for_ai(resume.structured_profile), llm.facts_for_ai_linkedin(linkedin))
                out = insights.merge_ai(rules, ai, insights.source_text(resume.structured_profile, linkedin))
                resume.insights = {"key": key, "data": out}
                db.commit()
            except llm.LLMError as e:
                out = {**rules, "ai_error": f"AI suggestions unavailable ({e}); showing the rules-based snapshot."}
    a = db.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user.id))
    return {**out, "ai_available": llm.provider_configured(), "ai_enabled": bool(a and a.ai_enabled),
            "linkedin_missing": not out.get("used_linkedin")}


@router.get("/resumes/{rid}/insights")
def get_insights(rid: int, ai: bool = False, refresh: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Resume, rid)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    return snapshot_for(db, user, r, ai, refresh)


class ToolIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    proficiency: str = "Intermediate"


class ApplyIn(BaseModel):
    resume_id: int | None = None
    search_profile_id: int | None = None
    profile_name: str = Field("My job search", max_length=200)
    roles: list[str] = Field(default_factory=list, max_length=5)
    technical: list[str] = Field(default_factory=list, max_length=10)
    behavioural: list[str] = Field(default_factory=list, max_length=6)
    tools: list[ToolIn] = Field(default_factory=list, max_length=10)


@router.post("/insights/apply")
def apply_insights(body: ApplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Turn the (user-edited) snapshot into search settings: target roles + a SHORT optional keyword list, flexible matching."""
    clean = lambda xs: [x.strip()[:80] for x in xs if x and x.strip()]  # noqa: E731
    roles, tech, beh = clean(body.roles), clean(body.technical), clean(body.behavioural)
    tools = [{"name": t.name.strip(), "proficiency": t.proficiency} for t in body.tools if t.name.strip()]
    if not roles:
        raise HTTPException(422, "Pick at least one role to search for")
    conf = insights.selection_to_profile(roles, tech, beh, tools)
    if body.resume_id:
        r = db.get(Resume, body.resume_id)
        if not r or r.user_id != user.id:
            raise HTTPException(404, "Resume not found")
    sp = db.get(SearchProfile, body.search_profile_id) if body.search_profile_id else db.scalar(
        select(SearchProfile).where(SearchProfile.user_id == user.id, SearchProfile.active.is_(True)).order_by(SearchProfile.id))
    created = sp is None
    if sp is not None and sp.user_id != user.id:
        raise HTTPException(404, "Search profile not found")
    if created:
        sp = SearchProfile(user_id=user.id, profile_name=body.profile_name, strictness="flexible", min_match_score=40.0,
                           resume_id=body.resume_id, sources=[])
        db.add(sp)
    previous = len(sp.keywords or [])
    sp.keywords = conf["keywords"]
    sp.role_preferences = {**(sp.role_preferences or {}), "target_titles": conf["target_titles"], "alternative_titles": conf["alternative_titles"]}
    if body.resume_id and not sp.resume_id:
        sp.resume_id = body.resume_id
    audit(db, user.id, "insights_applied", "search_profile", None, keywords=len(conf["keywords"]), created=created)
    db.commit()
    return {"created": created, "replaced_keywords": 0 if created else previous, "profile": as_dict(sp)}
