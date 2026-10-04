"""Database models. All timestamps are UTC."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (JSON, Boolean, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, utcnow


def _pk() -> Mapped[int]:
    return mapped_column(Integer, primary_key=True)


class JobStatus:
    NEW = "newly_discovered"
    NEEDS_REVIEW = "needs_review"
    RESUME_PENDING = "resume_generation_pending"
    RESUME_READY = "resume_ready_for_review"
    READY = "ready_to_apply"
    AWAITING_APPROVAL = "awaiting_user_approval"
    IN_PROGRESS = "application_in_progress"
    SUBMITTED = "submitted"
    CONFIRMATION_PENDING = "submission_confirmation_pending"
    MANUAL = "manual_application_required"
    FAILED = "application_failed"
    CLOSED = "closed_or_expired"
    REJECTED = "rejected"
    INTERVIEW = "interview"
    OFFER = "offer_received"
    WITHDRAWN = "withdrawn"


# Statuses from which a submission attempt may be claimed.
SUBMITTABLE = (JobStatus.READY, JobStatus.AWAITING_APPROVAL, JobStatus.FAILED)
# Statuses that mean "an application already exists / is happening".
LIVE_APPLICATION = (JobStatus.IN_PROGRESS, JobStatus.SUBMITTED, JobStatus.CONFIRMATION_PENDING,
                    JobStatus.INTERVIEW, JobStatus.OFFER)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    external_identity: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    account_status: Mapped[str] = mapped_column(String(32), default="active")  # active|disabled|deleted
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class EmailToken(Base):
    __tablename__ = "email_tokens"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))  # verify|reset
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(200))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    linkedin_data: Mapped[dict | None] = mapped_column(JSON)  # user-supplied/authorized import only
    verified_facts: Mapped[dict] = mapped_column(JSON, default=dict)
    work_authorization: Mapped[dict | None] = mapped_column(JSON)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(8))
    original_file_key: Mapped[str] = mapped_column(String(500))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    structured_profile: Mapped[dict | None] = mapped_column(JSON)
    processing_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|parsed|failed
    processing_error: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    insights: Mapped[dict | None] = mapped_column(JSON)  # cached AI career snapshot {key, data}
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    versions: Mapped[list["ResumeVersion"]] = relationship(back_populates="resume", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("user_id", "content_hash", name="uq_resume_user_hash"),)


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    id: Mapped[int] = _pk()
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    generated_content: Mapped[dict] = mapped_column(JSON)
    docx_file_key: Mapped[str | None] = mapped_column(String(500))
    pdf_file_key: Mapped[str | None] = mapped_column(String(500))
    validation_results: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)  # matched/missing/changes
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # True once used by an application
    resume: Mapped[Resume] = relationship(back_populates="versions")
    __table_args__ = (UniqueConstraint("resume_id", "job_id", "version_number", name="uq_resume_version"),)


class CoverLetter(Base):
    __tablename__ = "cover_letters"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)
    validation_results: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class SearchProfile(Base):
    __tablename__ = "search_profiles"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_name: Mapped[str] = mapped_column(String(200))
    # [{term, kind, required, excluded, synonyms[], weight}]
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    match_mode: Mapped[str] = mapped_column(String(16), default="weighted")  # and|or|weighted
    exclusions: Mapped[dict] = mapped_column(JSON, default=dict)  # companies, industries, keywords, roles
    employment_types: Mapped[list] = mapped_column(JSON, default=list)
    role_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    salary_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    location_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    remote_preferences: Mapped[list] = mapped_column(JSON, default=list)  # remote|hybrid|onsite
    other_filters: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{source, board}]
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    date_lookback_days: Mapped[int] = mapped_column(Integer, default=30)
    unknown_date_policy: Mapped[str] = mapped_column(String(16), default="include")  # include|exclude
    min_match_score: Mapped[float] = mapped_column(Float, default=40.0)
    # flexible: preferences (employment type, work mode, location, ...) only lower the score; strict: they exclude jobs
    strictness: Mapped[str] = mapped_column(String(12), default="flexible", server_default="flexible")
    overlap_hours: Mapped[int] = mapped_column(Integer, default=48)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = _pk()
    canonical_identity: Mapped[str] = mapped_column(String(64), unique=True)
    loose_key: Mapped[str] = mapped_column(String(64), index=True)  # company|title|location
    company_name: Mapped[str] = mapped_column(String(300), index=True)
    title: Mapped[str] = mapped_column(String(500))
    normalized_title: Mapped[str] = mapped_column(String(500), index=True)
    description: Mapped[str] = mapped_column(Text, default="")  # original, kept for audit
    normalized_description_hash: Mapped[str] = mapped_column(String(64))
    sections: Mapped[dict] = mapped_column(JSON, default=dict)  # responsibilities/required/preferred/skills
    location: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str | None] = mapped_column(String(100))
    remote_status: Mapped[str] = mapped_column(String(16), default="unknown")  # remote|hybrid|onsite|unknown
    employment_type: Mapped[str | None] = mapped_column(String(32))
    salary_information: Mapped[dict | None] = mapped_column(JSON)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    posted_at_reliable: Mapped[bool] = mapped_column(Boolean, default=False)
    modified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closing_date: Mapped[datetime | None] = mapped_column(UTCDateTime)
    company_career_url: Mapped[str | None] = mapped_column(String(1000))
    first_discovered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|closed
    needs_dedup_review: Mapped[bool] = mapped_column(Boolean, default=False)
    possible_duplicate_of: Mapped[int | None] = mapped_column(Integer)
    listings: Mapped[list["JobSourceListing"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobSourceListing(Base):
    __tablename__ = "job_source_listings"
    id: Mapped[int] = _pk()
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source_name: Mapped[str] = mapped_column(String(64))
    source_board: Mapped[str] = mapped_column(String(200), default="")
    source_job_id: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(1000), index=True)
    application_url: Mapped[str | None] = mapped_column(String(1000), index=True)
    source_posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="open")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    job: Mapped[Job] = relationship(back_populates="listings")
    __table_args__ = (UniqueConstraint("source_name", "source_job_id", name="uq_source_job"),)


class JobMatch(Base):
    __tablename__ = "job_matches"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    search_profile_id: Mapped[int] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    matching_factors: Mapped[list] = mapped_column(JSON, default=list)
    exclusion_reasons: Mapped[list] = mapped_column(JSON, default=list)
    qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    workflow_status: Mapped[str] = mapped_column(String(48), default=JobStatus.NEW)
    reported: Mapped[bool] = mapped_column(Boolean, default=False)  # included in a daily report already
    first_run_id: Mapped[int | None] = mapped_column(Integer)
    rules_score: Mapped[float | None] = mapped_column(Float)      # score before any AI blending
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)        # {key, fit_score, matched, gaps, reasoning, model}
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("search_profile_id", "job_id", name="uq_match_profile_job"),
                      Index("ix_match_user_qualified", "user_id", "qualified"))


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_versions.id"))
    cover_letter_version_id: Mapped[int | None] = mapped_column(ForeignKey("cover_letters.id"))
    status: Mapped[str] = mapped_column(String(48), default=JobStatus.RESUME_PENDING, index=True)
    application_url: Mapped[str | None] = mapped_column(String(1000))
    submission_method: Mapped[str | None] = mapped_column(String(32))  # api|form|manual|sandbox
    submission_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime)
    external_reference: Mapped[str | None] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    manual_reason: Mapped[str | None] = mapped_column(String(500))
    package: Mapped[dict | None] = mapped_column(JSON)  # manual-application package
    notes: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[datetime | None] = mapped_column(UTCDateTime)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),)


class ApplicationEvent(Base):
    """Append-only. Never updated or deleted by application code."""
    __tablename__ = "application_events"
    id: Mapped[int] = _pk()
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    previous_status: Mapped[str | None] = mapped_column(String(48))
    new_status: Mapped[str | None] = mapped_column(String(48))
    event_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    actor_type: Mapped[str] = mapped_column(String(16), default="system")  # user|system|scheduler


class SearchRun(Base):
    __tablename__ = "search_runs"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    search_profile_id: Mapped[int] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(24), default="running")  # running|completed|partial|failed
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    source_statistics: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[str | None] = mapped_column(Text)


class SourceCursor(Base):
    __tablename__ = "source_cursors"
    id: Mapped[int] = _pk()
    search_profile_id: Mapped[int] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True)
    source_name: Mapped[str] = mapped_column(String(200))  # "<source>:<board>"
    last_successful_cursor: Mapped[str | None] = mapped_column(String(500))
    last_successful_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (UniqueConstraint("search_profile_id", "source_name", name="uq_cursor"),)


class ConnectorHealth(Base):
    __tablename__ = "connector_health"
    source_name: Mapped[str] = mapped_column(String(200), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(500))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class DailyReport(Base):
    __tablename__ = "daily_reports"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    search_profile_id: Mapped[int] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"))
    search_run_id: Mapped[int] = mapped_column(ForeignKey("search_runs.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notification_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AutomationSettings(Base):
    __tablename__ = "automation_settings"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    # discovery_only | prepare_for_review | fill_and_request_approval | auto_submit_authorized
    mode: Mapped[str] = mapped_column(String(32), default="prepare_for_review")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_submit_consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cover_letters_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_prepare_min_score: Mapped[float] = mapped_column(Float, default=60.0)
    run_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=False)
    report_hour_local: Mapped[int] = mapped_column(Integer, default=8)
    data_retention_days: Mapped[int] = mapped_column(Integer, default=730)
    # AI features (job-fit scoring, resume rewording, keyword suggestions): off until the user opts in.
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false())
    ai_consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # never contains secrets in plaintext
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_integration"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = _pk()
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RunLock(Base):
    """Database-backed distributed lock (works without Redis)."""
    __tablename__ = "run_locks"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DeadLetter(Base):
    __tablename__ = "dead_letters"
    id: Mapped[int] = _pk()
    task_name: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


def as_dict(obj: Any, *skip: str) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in skip}
