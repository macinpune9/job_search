"""Job ingestion + deduplication.

Identity signals, strongest first:
  1. (source_name, source_job_id)           -> same listing
  2. normalized source / application URL    -> same listing
  3. loose key (company|title|location) AND description fingerprint -> same logical job on another source
  4. loose key only (description differs)   -> NOT merged; new job flagged `needs_dedup_review`
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors.base import RawListing
from ..db import utcnow
from ..models import Job, JobSourceListing
from .textutil import fingerprint, norm_company, norm_location, norm_title, norm_url, sha, split_sections


@dataclass
class UpsertResult:
    job: Job
    listing: JobSourceListing
    created_job: bool
    created_listing: bool
    changed: bool


def identity_for(raw: RawListing) -> tuple[str, str, str]:
    loose = sha(norm_company(raw.company), norm_title(raw.title), norm_location(raw.location))
    fp = fingerprint(raw.description)
    return sha(loose, fp), loose, fp


def upsert_listing(db: Session, raw: RawListing) -> UpsertResult:
    now = utcnow()
    identity, loose, fp = identity_for(raw)
    surl, aurl = norm_url(raw.source_url), norm_url(raw.application_url)

    listing = db.scalar(select(JobSourceListing).where(
        JobSourceListing.source_name == raw.source_name,
        JobSourceListing.source_job_id == raw.source_job_id))
    if listing is None:
        urls = [u for u in (surl, aurl) if u]
        if urls:
            listing = db.scalar(select(JobSourceListing).where(
                (JobSourceListing.source_url.in_(urls)) | (JobSourceListing.application_url.in_(urls))))

    if listing is not None:
        job = listing.job
        changed = listing.content_hash != fp
        listing.last_checked_at = now
        listing.status = "open"
        listing.content_hash = fp
        listing.source_posted_at = raw.posted_at or listing.source_posted_at
        job.last_seen_at = now
        job.status = "open"
        if changed:
            # Description changed on the source: refresh text, keep identity & original discovery date.
            job.description = raw.description
            job.normalized_description_hash = fp
            job.sections = split_sections(raw.description)
        if raw.salary and not job.salary_information:
            job.salary_information = raw.salary
        job.modified_at = raw.modified_at or job.modified_at
        return UpsertResult(job, listing, False, False, changed)

    job = db.scalar(select(Job).where(Job.canonical_identity == identity))
    created_job = False
    if job is None:
        sibling = db.scalar(select(Job).where(Job.loose_key == loose).order_by(Job.id))
        job = Job(
            canonical_identity=identity, loose_key=loose, company_name=raw.company, title=raw.title,
            normalized_title=norm_title(raw.title), description=raw.description,
            normalized_description_hash=fp, sections=split_sections(raw.description),
            location=raw.location, country=raw.country, remote_status=raw.remote_status,
            employment_type=raw.employment_type, salary_information=raw.salary,
            posted_at=raw.posted_at, posted_at_reliable=raw.posted_at_reliable and raw.posted_at is not None,
            modified_at=raw.modified_at, closing_date=raw.closing_date,
            company_career_url=raw.company_career_url, first_discovered_at=now, last_seen_at=now,
        )
        if sibling is not None:  # same company/title/location but different text: don't auto-merge
            job.needs_dedup_review = True
            job.possible_duplicate_of = sibling.id
        db.add(job)
        db.flush()
        created_job = True
    else:
        job.last_seen_at = now
        job.status = "open"
        if raw.posted_at and (job.posted_at is None or raw.posted_at < job.posted_at) and raw.posted_at_reliable:
            job.posted_at, job.posted_at_reliable = raw.posted_at, True

    listing = JobSourceListing(
        job_id=job.id, source_name=raw.source_name, source_board=raw.board, source_job_id=raw.source_job_id,
        source_url=surl or raw.source_url, application_url=aurl, source_posted_at=raw.posted_at,
        last_checked_at=now, content_hash=fp, source_metadata=raw.metadata or {},
    )
    db.add(listing)
    db.flush()
    return UpsertResult(job, listing, created_job, True, False)
