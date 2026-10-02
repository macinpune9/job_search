import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import audit, current_user
from ..models import Application, Job, Resume, ResumeVersion, User, as_dict
from ..security import decode_token, signed_download_token, storage
from ..services import resume_gen, resume_parser, versions

router = APIRouter(prefix="/api", tags=["resumes"])


def owned_resume(db: Session, user: User, rid: int) -> Resume:
    r = db.get(Resume, rid)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    return r


def owned_version(db: Session, user: User, vid: int) -> ResumeVersion:
    v = db.get(ResumeVersion, vid)
    if not v or v.resume.user_id != user.id:
        raise HTTPException(404, "Resume version not found")
    return v


def _summary(r: Resume, full: bool = False) -> dict:
    d = as_dict(r, "original_file_key", "extracted_text", "structured_profile")
    if full:
        d["extracted_text"], d["structured_profile"] = r.extracted_text, r.structured_profile
    return d


@router.post("/resumes", status_code=201)
async def upload_resume(file: UploadFile = File(...), label: str = "", user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    s = get_settings()
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {s.max_upload_mb} MB")
    filename = (file.filename or "resume").replace("\\", "/").split("/")[-1][:200]
    try:
        ftype = resume_parser.detect_type(filename, data)
    except resume_parser.ResumeError as e:
        raise HTTPException(415 if e.code == "unsupported_type" else 422, e.message)
    h = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(Resume).where(Resume.user_id == user.id, Resume.content_hash == h))
    if dup:
        raise HTTPException(409, f"This file was already uploaded (resume #{dup.id}).")
    key = storage().put(user.id, data, "." + ftype)  # original preserved, encrypted at rest
    r = Resume(user_id=user.id, label=label or filename, filename=filename, file_type=ftype, original_file_key=key,
               content_hash=h, is_primary=db.scalar(select(Resume.id).where(Resume.user_id == user.id)) is None)
    try:
        text = resume_parser.extract_text(ftype, data)
        r.extracted_text, r.structured_profile = text, resume_parser.parse_structured(text)
        r.processing_status = "parsed"
    except resume_parser.ResumeError as e:
        r.processing_status, r.processing_error = "failed", e.message
    db.add(r)
    audit(db, user.id, "resume_uploaded", "resume", None, status=r.processing_status, type=ftype)
    db.commit()
    if r.processing_status == "failed":
        raise HTTPException(422, {"message": r.processing_error, "resume_id": r.id})
    return _summary(r, True)


@router.get("/resumes")
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_summary(r) for r in db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.uploaded_at.desc()))]


@router.get("/resumes/{rid}")
def get_resume(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _summary(owned_resume(db, user, rid), True)


class ResumePatch(BaseModel):
    label: str | None = None
    is_primary: bool | None = None
    structured_profile: dict | None = None  # user corrections to parsed data


@router.patch("/resumes/{rid}")
def patch_resume(rid: int, body: ResumePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned_resume(db, user, rid)
    if body.label is not None:
        r.label = body.label
    if body.structured_profile is not None:
        r.structured_profile = body.structured_profile
        audit(db, user.id, "resume_profile_corrected", "resume", r.id)
    if body.is_primary:
        for o in db.scalars(select(Resume).where(Resume.user_id == user.id)):
            o.is_primary = o.id == r.id
    db.commit()
    return _summary(r, True)


@router.delete("/resumes/{rid}", status_code=204)
def delete_resume(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned_resume(db, user, rid)
    used = db.scalar(select(Application.id).join(ResumeVersion, ResumeVersion.id == Application.resume_version_id)
                     .where(ResumeVersion.resume_id == r.id).limit(1))
    if used:
        raise HTTPException(409, "This resume has versions attached to applications; they are kept as an immutable record.")
    st = storage()
    st.delete(r.original_file_key)
    for v in r.versions:
        st.delete(v.docx_file_key)
        st.delete(v.pdf_file_key)
    audit(db, user.id, "resume_deleted", "resume", r.id)
    db.delete(r)
    db.commit()


@router.get("/resumes/{rid}/download-link")
def resume_download_link(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned_resume(db, user, rid)
    return {"url": f"/api/files/{signed_download_token(user.id, r.original_file_key, r.filename)}", "expires_in": 300}


@router.get("/files/{token}")
def download(token: str):
    """Short-lived signed URL (5 min). The token itself is the credential, so keep it out of logs."""
    d = decode_token(token, "download")
    if not d:
        raise HTTPException(403, "Link expired or invalid")
    try:
        body = storage().get(d["key"])
    except (OSError, ValueError):
        raise HTTPException(404, "File not found")
    ct = "application/pdf" if d["key"].endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(body, media_type=ct, headers={"Content-Disposition": f'attachment; filename="{d["fn"]}"',
                                                  "Cache-Control": "no-store"})


# ---------------- versions ----------------
def _version(v: ResumeVersion) -> dict:
    return as_dict(v, "docx_file_key", "pdf_file_key") | {"has_docx": bool(v.docx_file_key), "has_pdf": bool(v.pdf_file_key)}


@router.get("/resumes/{rid}/versions")
def list_versions(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_resume(db, user, rid)
    return [_version(v) for v in db.scalars(select(ResumeVersion).where(ResumeVersion.resume_id == rid).order_by(ResumeVersion.id.desc()))]


@router.get("/resume-versions/{vid}")
def get_version(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = owned_version(db, user, vid)
    return _version(v) | {"original_profile": v.resume.structured_profile}


@router.get("/resume-versions/{vid}/download-link")
def version_link(vid: int, fmt: str = "docx", user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = owned_version(db, user, vid)
    key = v.pdf_file_key if fmt == "pdf" else v.docx_file_key
    if not key:
        raise HTTPException(404, f"No {fmt} available for this version")
    name = f"resume-v{v.version_number}.{fmt}"
    return {"url": f"/api/files/{signed_download_token(user.id, key, name)}", "expires_in": 300}


class VersionEdit(BaseModel):
    content: dict


@router.post("/resume-versions/{vid}/edit", status_code=201)
def edit_version(vid: int, body: VersionEdit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Editing never mutates the original version: a new version is created and re-validated."""
    v = owned_version(db, user, vid)
    job = db.get(Job, v.job_id) if v.job_id else None
    nv = versions.revalidate_edit(db, v, body.content, f"{job.title}\n{job.description}" if job else "")
    audit(db, user.id, "resume_version_edited", "resume_version", nv.id)
    db.commit()
    return _version(nv)
