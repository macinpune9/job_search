"""Connectors for public, documented job-board endpoints (no scraping, no credentials).

- Greenhouse Job Board API: https://developers.greenhouse.io/job-board.html
- Lever Postings API:       https://github.com/lever/postings-api
- Ashby Job Postings API:   https://developers.ashbyhq.com/docs/public-job-posting-api
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..services.textutil import html_to_text
from .base import Connector, ConnectorError, FetchResult, RawListing, norm_employment, norm_remote


def _iso(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class GreenhouseConnector(Connector):
    name = "greenhouse"
    display_name = "Greenhouse (public job boards)"
    compliance_note = "Uses the public Job Board API. The `board` is the company's board token."

    def fetch(self, board, since=None, lookback_days=None):
        data = self.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", {"content": "true"})
        out = []
        for j in data.get("jobs", []):
            loc = (j.get("location") or {}).get("name")
            # `first_published` is the original publication date; `updated_at` is only a modification time.
            first = _iso(j.get("first_published"))
            out.append(RawListing(
                source_name=self.name, board=board, source_job_id=str(j["id"]),
                title=j.get("title", ""), company=j.get("company_name") or board,
                description=html_to_text(j.get("content")), location=loc,
                remote_status=norm_remote(None, loc),
                posted_at=first, posted_at_reliable=first is not None,
                modified_at=_iso(j.get("updated_at")),
                source_url=j.get("absolute_url", ""), application_url=j.get("absolute_url"),
                company_career_url=f"https://boards.greenhouse.io/{board}",
                metadata={"requisition_id": j.get("requisition_id"),
                          "departments": [d.get("name") for d in j.get("departments", [])]},
            ))
        return FetchResult(out, complete=True)


class LeverConnector(Connector):
    name = "lever"
    display_name = "Lever (public postings)"
    compliance_note = "Uses the public Postings API. The `board` is the company's Lever site name."

    def fetch(self, board, since=None, lookback_days=None):
        out, skip, page = [], 0, 100
        while True:
            data = self.get_json(f"https://api.lever.co/v0/postings/{board}",
                                 {"mode": "json", "skip": skip, "limit": page})
            if not isinstance(data, list):
                raise ConnectorError("unexpected Lever response")
            for j in data:
                cats = j.get("categories") or {}
                created = j.get("createdAt")
                posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else None
                desc = j.get("descriptionPlain") or html_to_text(j.get("description"))
                for lst in j.get("lists", []):
                    desc += f"\n\n{lst.get('text', '')}\n" + html_to_text(lst.get("content"))
                loc = cats.get("location") or ", ".join(cats.get("allLocations", []) or [])
                sal = j.get("salaryRange")
                out.append(RawListing(
                    source_name=self.name, board=board, source_job_id=str(j["id"]),
                    title=j.get("text", ""), company=board, description=desc.strip(), location=loc or None,
                    remote_status=norm_remote(j.get("workplaceType"), loc),
                    employment_type=norm_employment(cats.get("commitment")),
                    salary={"min": sal.get("min"), "max": sal.get("max"), "currency": sal.get("currency"),
                            "period": (sal.get("interval") or "").replace("per-", "").replace("-salary", "") or None,
                            "basis": "gross"} if sal else None,
                    posted_at=posted, posted_at_reliable=posted is not None,
                    source_url=j.get("hostedUrl", ""), application_url=j.get("applyUrl") or j.get("hostedUrl"),
                    company_career_url=f"https://jobs.lever.co/{board}",
                    metadata={"team": cats.get("team"), "department": cats.get("department")},
                ))
            if len(data) < page:
                break
            skip += page
        return FetchResult(out, complete=True)


class AshbyConnector(Connector):
    name = "ashby"
    display_name = "Ashby (public job boards)"
    compliance_note = "Uses the public Job Posting API. The `board` is the Ashby job-board name."

    def fetch(self, board, since=None, lookback_days=None):
        data = self.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}",
                             {"includeCompensation": "true"})
        out = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            posted = _iso(j.get("publishedAt") or j.get("publishedDate"))
            loc = j.get("location")
            comp = (j.get("compensation") or {})
            sal = None
            for tier in comp.get("summaryComponents", []) or []:
                if tier.get("compensationType") == "Salary":
                    sal = {"min": tier.get("minValue"), "max": tier.get("maxValue"),
                           "currency": tier.get("currencyCode"),
                           "period": (tier.get("interval") or "").replace("1 ", "").lower() or None, "basis": "gross"}
            out.append(RawListing(
                source_name=self.name, board=board, source_job_id=str(j.get("id")),
                title=j.get("title", ""), company=board,
                description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")), location=loc,
                remote_status="remote" if j.get("isRemote") else norm_remote(j.get("workplaceType"), loc),
                employment_type=norm_employment(j.get("employmentType")), salary=sal,
                posted_at=posted, posted_at_reliable=posted is not None,
                source_url=j.get("jobUrl", ""), application_url=j.get("applyUrl") or j.get("jobUrl"),
                company_career_url=f"https://jobs.ashbyhq.com/{board}",
            ))
        return FetchResult(out, complete=True)
