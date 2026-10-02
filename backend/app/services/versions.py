"""Tailored resume / cover-letter version creation."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CoverLetter, Job, Resume, ResumeVersion
from ..security import storage
from . import resume_gen


def store_version(db: Session, resume: Resume, job: Job | None, content: dict, analysis: dict,
                  validation: dict) -> ResumeVersion:
    cond = ResumeVersion.job_id == job.id if job else ResumeVersion.job_id.is_(None)
    n = db.scalar(select(func.coalesce(func.max(ResumeVersion.version_number), 0)).where(
        ResumeVersion.resume_id == resume.id, cond)) + 1
    st = storage()
    docx_key = st.put(resume.user_id, resume_gen.render_docx(content), ".docx")
    try:
        pdf_key = st.put(resume.user_id, resume_gen.render_pdf(content), ".pdf")
    except Exception:  # noqa: BLE001 - PDF is best-effort; DOCX is the primary artifact
        pdf_key = None
    rv = ResumeVersion(resume_id=resume.id, job_id=job.id if job else None, version_number=n,
                       generated_content=content, docx_file_key=docx_key, pdf_file_key=pdf_key,
                       validation_results=validation, analysis=analysis)
    db.add(rv)
    db.flush()
    return rv


def generate_for_job(db: Session, resume: Resume, job: Job) -> ResumeVersion:
    src = resume.structured_profile or {}
    text = f"{job.title}\n{job.description}"
    content, analysis = resume_gen.generate(src, job.title, job.description, job.company_name)
    validation = resume_gen.validate(content, src, text)
    return store_version(db, resume, job, content, analysis, validation)


def revalidate_edit(db: Session, rv: ResumeVersion, new_content: dict, job_text: str) -> ResumeVersion:
    """User edits create a NEW version (versions are never mutated once created)."""
    resume = rv.resume
    validation = resume_gen.validate(new_content, resume.structured_profile or {}, job_text)
    job = db.get(Job, rv.job_id) if rv.job_id else None
    return store_version(db, resume, job, new_content, {**(rv.analysis or {}), "edited_from": rv.id}, validation)


def make_cover_letter(db: Session, user_id: int, resume: Resume, job: Job, matched: list[str]) -> CoverLetter:
    src = resume.structured_profile or {}
    text = resume_gen.cover_letter(src, job.title, job.company_name, matched)
    validation = resume_gen.validate_text(text, src)
    n = (db.scalar(select(func.max(CoverLetter.version_number)).where(
        CoverLetter.user_id == user_id, CoverLetter.job_id == job.id)) or 0) + 1
    cl = CoverLetter(user_id=user_id, job_id=job.id, version_number=n, content=text, validation_results=validation)
    db.add(cl)
    db.flush()
    return cl
