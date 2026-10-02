"""Source connector interface and shared HTTP helper.

To add a source: subclass Connector, implement `fetch`, and register it in
`app/connectors/__init__.py`. See docs/integrations.md.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from ..config import get_settings


class ConnectorError(Exception):
    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


class ConnectorUnavailable(ConnectorError):
    """Source needs credentials / configuration that the user has not provided."""


@dataclass
class RawListing:
    source_name: str
    board: str
    source_job_id: str
    title: str
    company: str
    description: str = ""
    location: str | None = None
    country: str | None = None
    remote_status: str = "unknown"          # remote|hybrid|onsite|unknown
    employment_type: str | None = None      # permanent|part_time|fixed_term|temporary|freelance|contract_to_hire|internship
    salary: dict | None = None              # {min,max,currency,period,basis}
    posted_at: datetime | None = None       # ORIGINAL publication date only
    posted_at_reliable: bool = False
    modified_at: datetime | None = None     # never promoted to posted_at
    source_url: str = ""
    application_url: str | None = None
    closing_date: datetime | None = None
    company_career_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    listings: list[RawListing]
    complete: bool = True   # True only if the whole board was enumerated (enables closed-job detection)
    cursor: str | None = None


class Connector(ABC):
    name: str = ""
    display_name: str = ""
    requires_credentials: bool = False
    compliance_note: str = ""

    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        self.client = client or httpx.Client(
            timeout=s.http_timeout_seconds, headers={"User-Agent": s.user_agent}, follow_redirects=True)

    @abstractmethod
    def fetch(self, board: str, since: datetime | None = None) -> FetchResult: ...

    def get_json(self, url: str, params: dict | None = None, retries: int = 3) -> Any:
        delay = get_settings().retry_base_seconds
        last: Exception | None = None
        for attempt in range(retries):
            try:
                r = self.client.get(url, params=params)
            except httpx.TransportError as e:
                last = ConnectorError(f"network error: {type(e).__name__}", transient=True)
            else:
                if r.status_code == 200:
                    try:
                        return r.json()
                    except ValueError:
                        raise ConnectorError("invalid JSON from source")
                if r.status_code in (401, 403):
                    raise ConnectorUnavailable(f"access denied ({r.status_code})")
                if r.status_code == 404:
                    raise ConnectorError("board not found (404)")
                if r.status_code == 429 or r.status_code >= 500:
                    ra = r.headers.get("Retry-After")
                    if ra and ra.isdigit():
                        delay = min(float(ra), 30.0)
                    last = ConnectorError(f"source returned {r.status_code}", transient=True)
                else:
                    raise ConnectorError(f"unexpected status {r.status_code}")
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
        raise last or ConnectorError("request failed", transient=True)


EMPLOYMENT_MAP = [
    ("contract to hire", "contract_to_hire"), ("contract-to-hire", "contract_to_hire"),
    ("intern", "internship"), ("part", "part_time"), ("temp", "temporary"),
    ("freelance", "freelance"), ("contractor", "freelance"), ("independent", "freelance"),
    ("fixed", "fixed_term"), ("contract", "fixed_term"),
    ("full", "permanent"), ("perm", "permanent"), ("regular", "permanent"),
]


def norm_employment(value: str | None) -> str | None:
    v = (value or "").lower()
    for needle, out in EMPLOYMENT_MAP:
        if needle in v:
            return out
    return None


def norm_remote(value: str | None, location: str | None = None) -> str:
    v = f"{value or ''} {location or ''}".lower()
    if "hybrid" in v:
        return "hybrid"
    if "remote" in v:
        return "remote"
    if "on-site" in v or "onsite" in v or "on site" in v:
        return "onsite"
    return "unknown"
