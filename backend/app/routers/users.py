import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import audit, current_user
from ..models import (Application, ApplicationEvent, CandidateProfile, CoverLetter, JobMatch, Notification, Resume,
                      SearchProfile, User, as_dict)
from ..security import storage
from ..services import resume_parser

router = APIRouter(prefix="/api", tags=["users"])


class UserPatch(BaseModel):
    timezone: str | None = None


def _me(u: User) -> dict:
    return {"id": u.id, "email": u.email, "timezone": u.timezone, "email_verified": u.email_verified,
            "account_status": u.account_status, "created_at": u.created_at}


@router.get("/users/me")
def me(user: User = Depends(current_user)):
    return _me(user)


@router.patch("/users/me")
def patch_me(body: UserPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.timezone:
        try:
            ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, "Unknown time zone")
        user.timezone = body.timezone
    db.commit()
    return _me(user)


@router.delete("/users/me", status_code=204)
def delete_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Permanent account deletion: all rows (FK cascade) and stored files."""
    st = storage()
    from ..models import ResumeVersion
    for r in db.scalars(select(Resume).where(Resume.user_id == user.id)):
        st.delete(r.original_file_key)
        for v in db.scalars(select(ResumeVersion).where(ResumeVersion.resume_id == r.id)):
            st.delete(v.docx_file_key)
            st.delete(v.pdf_file_key)
    audit(db, None, "account_deleted", "user", user.id)
    db.delete(user)
    db.commit()


@router.get("/users/me/export")
def export_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Personal-data export (JSON)."""
    uid = user.id
    prof = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == uid))
    apps = db.scalars(select(Application).where(Application.user_id == uid)).all()
    return {
        "user": _me(user), "candidate_profile": as_dict(prof) if prof else None,
        "resumes": [as_dict(r, "original_file_key") for r in db.scalars(select(Resume).where(Resume.user_id == uid))],
        "search_profiles": [as_dict(s) for s in db.scalars(select(SearchProfile).where(SearchProfile.user_id == uid))],
        "applications": [as_dict(a) for a in apps],
        "application_events": [as_dict(e) for a in apps for e in db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == a.id))],
        "cover_letters": [as_dict(c) for c in db.scalars(select(CoverLetter).where(CoverLetter.user_id == uid))],
        "matches": [as_dict(m) for m in db.scalars(select(JobMatch).where(JobMatch.user_id == uid))],
        "notifications": [as_dict(n) for n in db.scalars(select(Notification).where(Notification.user_id == uid))],
    }


# ---------------- candidate profile + LinkedIn ----------------
LINKEDIN_RE = re.compile(r"^https://([a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]{3,100}/?$")


class ProfilePatch(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    work_authorization: dict | None = None
    verified_facts: dict | None = None


def _profile(db: Session, user: User) -> CandidateProfile:
    p = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if not p:
        p = CandidateProfile(user_id=user.id)
        db.add(p)
        db.flush()
    return p


@router.get("/profiles/me")
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return as_dict(_profile(db, user))


@router.patch("/profiles/me")
def patch_profile(body: ProfilePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _profile(db, user)
    data = body.model_dump(exclude_unset=True)
    if data.get("linkedin_url"):
        data["linkedin_url"] = data["linkedin_url"].strip()
        if not LINKEDIN_RE.match(data["linkedin_url"]):
            raise HTTPException(422, "Enter a LinkedIn profile URL like https://www.linkedin.com/in/your-name")
    for k, v in data.items():
        setattr(p, k, v)
    p.profile_version += 1
    db.commit()
    return as_dict(p)


class LinkedInImport(BaseModel):
    url: str | None = None
    pasted_text: str | None = None   # text copied from the user's own profile, or from LinkedIn's data export
    export_json: dict | None = None  # parsed 'Profile'/'Positions' data from LinkedIn's official data export


@router.post("/profiles/linkedin/import")
def linkedin_import(body: LinkedInImport, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """No scraping: LinkedIn content is accepted only from the user (paste/export) or an authorized API."""
    p = _profile(db, user)
    if body.url:
        if not LINKEDIN_RE.match(body.url.strip()):
            raise HTTPException(422, "Enter a LinkedIn profile URL like https://www.linkedin.com/in/your-name")
        p.linkedin_url = body.url.strip()
    if not body.pasted_text and not body.export_json:
        db.commit()
        return {"imported": False, "linkedin_url": p.linkedin_url, "limitation":
                "Automatic import is unavailable: LinkedIn does not allow scraping profiles and no authorized API "
                "is configured. Your URL was saved. To import details, paste your profile text or upload LinkedIn's "
                "official data export."}
    if body.export_json:
        ex = body.export_json
        data = {"summary": ex.get("summary", ""), "skills": [s if isinstance(s, str) else s.get("name", "") for s in ex.get("skills", [])],
                "experience": [{"title": e.get("title", ""), "company": e.get("company", e.get("companyName", "")),
                                "start": e.get("start"), "end": e.get("end"), "bullets": [e["description"]] if e.get("description") else []}
                               for e in ex.get("positions", ex.get("experience", []))]}
    else:
        if len(body.pasted_text) > 50_000:
            raise HTTPException(413, "Pasted text is too long")
        data = resume_parser.parse_structured(body.pasted_text)
    p.linkedin_data = data
    resume = db.scalar(select(Resume).where(Resume.user_id == user.id, Resume.processing_status == "parsed")
                       .order_by(Resume.is_primary.desc(), Resume.uploaded_at.desc()))
    db.commit()
    return {"imported": True, "data": data, "discrepancies": discrepancies(data, resume.structured_profile if resume else None)}


def discrepancies(li: dict, resume: dict | None) -> list[dict]:
    if not resume:
        return [{"type": "no_resume", "detail": "Upload a resume to compare against."}]
    out = []
    norm = lambda s: re.sub(r"\W+", " ", (s or "").lower()).strip()  # noqa: E731
    rs = {norm(s) for s in resume.get("skills", [])}
    ls = {norm(s) for s in li.get("skills", [])}
    for s in sorted(ls - rs):
        out.append({"type": "skill_only_on_linkedin", "detail": s})
    for s in sorted(rs - ls):
        out.append({"type": "skill_only_on_resume", "detail": s})
    r_roles = {(norm(e.get("company")), norm(e.get("title"))) for e in resume.get("experience", [])}
    for e in li.get("experience", []):
        k = (norm(e.get("company")), norm(e.get("title")))
        if k not in r_roles:
            out.append({"type": "role_only_on_linkedin", "detail": f"{e.get('title')} @ {e.get('company')}"})
    l_roles = {(norm(e.get("company")), norm(e.get("title"))) for e in li.get("experience", [])}
    for e in resume.get("experience", []):
        if (norm(e.get("company")), norm(e.get("title"))) not in l_roles:
            out.append({"type": "role_only_on_resume", "detail": f"{e.get('title')} @ {e.get('company')}"})
    return out
