"""Additional permitted sources, popular with Swiss and DACH employers.

Company career feeds (public, documented, no credentials): Personio, SmartRecruiters, Workable, Recruitee.
Search aggregator (free API key required): Adzuna (covers Switzerland).

NOT included on purpose: LinkedIn, Indeed and jobs.ch. None offers a public job-search API (Indeed retired its Publisher API;
LinkedIn's is partner-only), their terms forbid automated collection, and jobs.ch's robots.txt disallows automated access to
its API and job pages. Use "Add job manually" for jobs found there.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ..config import get_settings
from ..services.textutil import html_to_text
from .base import (Connector, ConnectorError, ConnectorUnavailable, FetchResult, RawListing, norm_employment, norm_remote)
from .boards import _iso

log = logging.getLogger("jobpilot.connectors")


def _join(*parts) -> str | None:
    out = [str(p).strip() for p in parts if p and str(p).strip()]
    return ", ".join(dict.fromkeys(out)) or None


class PersonioConnector(Connector):
    name = "personio"
    display_name = "Personio (company career feeds)"
    compliance_note = "Uses the company's public XML job feed (jobs.personio.de / .com). No credentials."
    board_hint = "the company's Personio subdomain (the part before .jobs.personio.de)"
    board_example = "personio"

    def _feed(self, url, lang):
        raw = self.get_text(url, {"language": lang} if lang else None)
        try:
            return ET.fromstring(raw)
        except (ET.ParseError, DefusedXmlException) as e:
            raise ConnectorError(f"invalid feed XML ({type(e).__name__})")

    def fetch(self, board, since=None, lookback_days=None):
        root, tld = None, ""
        for tld in ("de", "com"):
            try:
                root = self._feed(f"https://{board}.jobs.personio.{tld}/xml", None)
                break
            except ConnectorError as e:
                if "404" not in str(e) or tld == "com":
                    raise
        # Feeds are per language: the default one may have no text. Fall back to en, de, fr until descriptions appear.
        if root is not None and not root.findall(".//jobDescription"):
            for lang in ("en", "de", "fr"):
                alt = self._feed(f"https://{board}.jobs.personio.{tld}/xml", lang)
                if alt.findall(".//jobDescription"):
                    root = alt
                    break
        out = []
        for p in root.findall("position"):
            pid = (p.findtext("id") or "").strip()
            title = (p.findtext("name") or "").strip()
            if not pid or not title:
                continue
            office = p.findtext("office")
            extra = [o.text for o in p.findall("additionalOffices/office")]
            sections = []
            for jd in p.findall("jobDescriptions/jobDescription"):
                body = html_to_text(jd.findtext("value") or "")
                if body:
                    sections.append(f"{(jd.findtext('name') or '').strip()}\n{body}".strip())
            created = _iso(p.findtext("createdAt"))
            loc = _join(office, *extra)
            url = f"https://{board}.jobs.personio.{tld}/job/{pid}"
            out.append(RawListing(
                source_name=self.name, board=board, source_job_id=pid, title=title,
                company=(p.findtext("subcompany") or board).strip(), description="\n\n".join(sections), location=loc,
                remote_status=norm_remote(None, loc),
                employment_type=norm_employment(f"{p.findtext('employmentType') or ''} {p.findtext('schedule') or ''}"),
                posted_at=created, posted_at_reliable=created is not None, source_url=url, application_url=url,
                company_career_url=f"https://{board}.jobs.personio.{tld}",
                metadata={"department": p.findtext("department"), "category": p.findtext("recruitingCategory"),
                          "seniority": p.findtext("seniority"), "years_of_experience": p.findtext("yearsOfExperience")}))
        return FetchResult(out, complete=True)


class SmartRecruitersConnector(Connector):
    name = "smartrecruiters"
    display_name = "SmartRecruiters (company career feeds)"
    compliance_note = "Uses the public Posting API. One extra request per posting for its description (capped per run)."
    board_hint = "the company identifier in its SmartRecruiters URL"
    board_example = "smartrecruiters"
    DETAIL_CAP = 120

    def fetch(self, board, since=None, lookback_days=None):
        base = f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
        items, offset = [], 0
        while True:
            data = self.get_json(base, {"limit": 100, "offset": offset})
            page = data.get("content", [])
            items += page
            offset += len(page)
            if not page or offset >= data.get("totalFound", 0) or offset >= 1000:
                break
        out = []
        for n, it in enumerate(items):
            pid, loc = str(it["id"]), it.get("location") or {}
            desc, post_url, apply_url = "", f"https://jobs.smartrecruiters.com/{board}/{pid}", None
            if n < self.DETAIL_CAP:
                try:
                    d = self.get_json(f"{base}/{pid}")
                    secs = (d.get("jobAd") or {}).get("sections") or {}
                    desc = "\n\n".join(f"{s.get('title', '')}\n{html_to_text(s.get('text'))}".strip()
                                       for s in secs.values() if isinstance(s, dict) and s.get("text"))
                    post_url, apply_url = d.get("postingUrl") or post_url, d.get("applyUrl")
                except ConnectorError as e:
                    log.info("smartrecruiters detail failed for %s/%s: %s", board, pid, e)
            released = _iso(it.get("releasedDate"))
            remote = "remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else norm_remote(None, loc.get("fullLocation"))
            out.append(RawListing(
                source_name=self.name, board=board, source_job_id=pid, title=it.get("name", "").strip(),
                company=(it.get("company") or {}).get("name") or board, description=desc,
                location=loc.get("fullLocation") or _join(loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()),
                country=(loc.get("country") or "").upper() or None, remote_status=remote,
                employment_type=norm_employment((it.get("typeOfEmployment") or {}).get("label")),
                posted_at=released, posted_at_reliable=released is not None, source_url=post_url,
                application_url=apply_url or post_url, company_career_url=f"https://careers.smartrecruiters.com/{board}",
                metadata={"department": (it.get("department") or {}).get("label"),
                          "experience_level": (it.get("experienceLevel") or {}).get("label"),
                          "description_truncated": n >= self.DETAIL_CAP}))
        return FetchResult(out, complete=True)


class WorkableConnector(Connector):
    name = "workable"
    display_name = "Workable (company career feeds)"
    compliance_note = "Uses Workable's public widget API for a company's published jobs. No credentials."
    board_hint = "the company's Workable account name (apply.workable.com/<name>)"
    board_example = "huggingface"

    def fetch(self, board, since=None, lookback_days=None):
        data = self.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{board}", {"details": "true"})
        out = []
        for j in data.get("jobs", []):
            code = j.get("shortcode") or j.get("code")
            if not code:
                continue
            posted = _iso(j.get("published_on") or j.get("created_at"))
            loc = _join(j.get("city"), j.get("state"), j.get("country"))
            out.append(RawListing(
                source_name=self.name, board=board, source_job_id=str(code), title=(j.get("title") or "").strip(),
                company=data.get("name") or board, description=html_to_text(j.get("description")), location=loc,
                country=j.get("country"), remote_status="remote" if j.get("telecommuting") else norm_remote(None, loc),
                employment_type=norm_employment(j.get("employment_type")),
                posted_at=posted, posted_at_reliable=posted is not None,
                source_url=j.get("url") or j.get("shortlink") or "", application_url=j.get("application_url") or j.get("url"),
                company_career_url=f"https://apply.workable.com/{board}/",
                metadata={"department": j.get("department"), "experience": j.get("experience"), "function": j.get("function")}))
        return FetchResult(out, complete=True)


class RecruiteeConnector(Connector):
    name = "recruitee"
    display_name = "Recruitee (company career feeds)"
    compliance_note = "Uses the company's public careers-site API ({company}.recruitee.com/api/offers). No credentials."
    board_hint = "the company's Recruitee subdomain"
    board_example = "bunq"

    @staticmethod
    def _dt(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return _iso(s)

    def fetch(self, board, since=None, lookback_days=None):
        data = self.get_json(f"https://{board}.recruitee.com/api/offers/")
        out = []
        for o in data.get("offers", []):
            if o.get("status", "published") != "published":
                continue
            desc = html_to_text(o.get("description"))
            if o.get("requirements"):
                desc += "\n\nRequirements\n" + html_to_text(o["requirements"])
            posted = self._dt(o.get("published_at") or o.get("created_at"))
            remote = "remote" if o.get("remote") else "hybrid" if o.get("hybrid") else "onsite" if o.get("on_site") else "unknown"
            sal = o.get("salary") or {}
            salary = ({"min": sal.get("min"), "max": sal.get("max"), "currency": sal.get("currency"), "period": sal.get("period"), "basis": "gross"}
                      if sal.get("currency") and (sal.get("min") or sal.get("max")) else None)
            url = o.get("careers_url") or ""
            out.append(RawListing(
                source_name=self.name, board=board, source_job_id=str(o["id"]), title=(o.get("title") or "").strip(),
                company=o.get("company_name") or board, description=desc, location=o.get("location") or _join(o.get("city"), o.get("country")),
                country=o.get("country"), remote_status=remote, employment_type=norm_employment(o.get("employment_type_code")),
                salary=salary, posted_at=posted, posted_at_reliable=posted is not None, source_url=url,
                application_url=o.get("careers_apply_url") or url, company_career_url=f"https://{board}.recruitee.com",
                metadata={"department": o.get("department")}))
        return FetchResult(out, complete=True)


_COUNTRY_NAMES = {"switzerland": "ch", "schweiz": "ch", "suisse": "ch", "svizzera": "ch", "germany": "de", "deutschland": "de", "austria": "at",
                  "österreich": "at", "france": "fr", "italy": "it", "italia": "it", "netherlands": "nl", "belgium": "be",
                  "united kingdom": "gb", "uk": "gb", "united states": "us", "usa": "us"}
_ADZUNA_CCY = {"ch": "CHF", "de": "EUR", "at": "EUR", "fr": "EUR", "it": "EUR", "nl": "EUR", "be": "EUR", "gb": "GBP", "us": "USD"}


class AdzunaConnector(Connector):
    name = "adzuna"
    display_name = "Adzuna (job search aggregator, Switzerland)"
    requires_credentials = True
    is_search = True
    compliance_note = ("Official Adzuna API (free key). It returns only a SHORT snippet of each description and its dates are "
                       "aggregator dates, so the posted-age window is applied by Adzuna itself (max_days_old).")
    board_hint = "a search: what|where|country, e.g. python developer|Zürich (where and country are optional; country defaults to ch)"
    board_example = "software engineer|Zürich"
    board_pattern = r"^[^<>{}\[\]\\\x00-\x1f]{2,150}$"
    credentials_help = "Set ADZUNA_APP_ID and ADZUNA_APP_KEY (free at developer.adzuna.com)"
    PER_PAGE, MAX_PAGES = 50, 4

    @classmethod
    def configured(cls) -> bool:
        s = get_settings()
        return bool(s.adzuna_app_id and s.adzuna_app_key)

    def fetch(self, board, since=None, lookback_days=None):
        s = get_settings()
        if not self.configured():
            raise ConnectorUnavailable("Adzuna credentials not configured (set ADZUNA_APP_ID and ADZUNA_APP_KEY)")
        parts = [p.strip() for p in board.split("|")]
        what, where = parts[0], (parts[1] if len(parts) > 1 else "")
        country = (parts[2] if len(parts) > 2 and parts[2] else "ch").strip().lower()
        country = _COUNTRY_NAMES.get(country, country)
        if not country.isalpha() or len(country) != 2:
            raise ConnectorError("country must be a 2-letter code (e.g. ch) or a country name like Switzerland")
        out: list[RawListing] = []
        for page in range(1, self.MAX_PAGES + 1):
            params = {"app_id": s.adzuna_app_id, "app_key": s.adzuna_app_key, "results_per_page": self.PER_PAGE, "what": what,
                      "max_days_old": lookback_days or 30, "sort_by": "date"}
            if where:
                params["where"] = where
            data = self.get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}", params)
            results = data.get("results", [])
            for r in results:
                predicted = str(r.get("salary_is_predicted", "0")) == "1"
                sal = ({"min": r.get("salary_min"), "max": r.get("salary_max"), "currency": _ADZUNA_CCY.get(country), "period": "year", "basis": "gross"}
                       if (r.get("salary_min") or r.get("salary_max")) and not predicted and _ADZUNA_CCY.get(country) else None)
                loc = (r.get("location") or {}).get("display_name")
                created = _iso(r.get("created"))
                url = r.get("redirect_url") or ""
                out.append(RawListing(
                    source_name=self.name, board=board, source_job_id=str(r["id"]), title=html_to_text(r.get("title")),
                    company=((r.get("company") or {}).get("display_name") or "Unknown"), description=html_to_text(r.get("description")),
                    location=loc, country=country.upper(), remote_status=norm_remote(None, loc),
                    employment_type=norm_employment(f"{r.get('contract_time') or ''} {r.get('contract_type') or ''}"),
                    salary=sal, posted_at=created, posted_at_reliable=False,  # aggregator date: not treated as the original posting date
                    source_url=url, application_url=url,
                    metadata={"category": (r.get("category") or {}).get("label"), "description_truncated": True}))
            if len(results) < self.PER_PAGE:
                break
        return FetchResult(out, complete=False)  # a search is never a full enumeration: no closed-listing detection
