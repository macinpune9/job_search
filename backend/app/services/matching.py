"""Job <-> search-profile matching.

HARD filters exclude a job (with a recorded reason). SOFT preferences only affect the score.
Components without data are left out and the score is renormalised over what could be assessed,
so unknown data never silently counts for or against a job.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..db import utcnow
from ..models import Job, SearchProfile
from .skillvocab import is_plausible_skill
from .textutil import contains_term, norm_company, norm_title, tokens

PERIOD_TO_ANNUAL = {"year": 1, "annual": 1, "yearly": 1, "month": 12, "monthly": 12, "week": 52,
                    "weekly": 52, "day": 260, "daily": 260, "hour": 2080, "hourly": 2080}
SENIORITY = ["intern", "junior", "associate", "mid", "senior", "staff", "lead", "principal", "manager", "director"]
WEIGHTS = {"title": 30, "keywords": 35, "skills": 15, "location": 10, "salary": 5, "seniority": 5, "employment": 5, "work_mode": 5}


@dataclass
class MatchResult:
    score: float = 0.0
    factors: list[dict] = field(default_factory=list)
    exclusions: list[dict] = field(default_factory=list)
    qualified: bool = False


def _annual(amount, period) -> float | None:
    f = PERIOD_TO_ANNUAL.get((period or "").lower().replace("per-", ""))
    return amount * f if amount is not None and f else None


def compare_salary(job_sal: dict | None, prefs: dict) -> dict:
    """Returns {status: comparable|not_comparable|unknown, ok: bool|None, detail}."""
    want = prefs.get("min")
    if not job_sal or want is None:
        return {"status": "unknown", "ok": None, "detail": "salary not provided by job or preferences"}
    jc, pc = (job_sal.get("currency") or "").upper(), (prefs.get("currency") or "").upper()
    if not jc or not pc or jc != pc:
        return {"status": "not_comparable", "ok": None, "detail": f"currency differs or unknown ({jc or '?'} vs {pc or '?'})"}
    jb, pb = job_sal.get("basis"), prefs.get("basis")
    if jb and pb and jb != pb:
        return {"status": "not_comparable", "ok": None, "detail": "gross/net basis differs"}
    top = job_sal.get("max") if job_sal.get("max") is not None else job_sal.get("min")
    top_a, want_a = _annual(top, job_sal.get("period")), _annual(want, prefs.get("period", "year"))
    if top_a is None or want_a is None:
        return {"status": "not_comparable", "ok": None, "detail": "pay period unknown"}
    return {"status": "comparable", "ok": top_a >= want_a,
            "detail": f"job max ≈ {top_a:,.0f}/yr vs minimum {want_a:,.0f}/yr ({jc})"}


def years_required(text: str) -> int | None:
    m = re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", text.lower())
    return max(int(x) for x in m) if m else None


def candidate_years(structured: dict | None) -> float | None:
    if not structured:
        return None
    total, seen = 0.0, False
    for e in structured.get("experience", []):
        s, en = _ym(e.get("start")), _ym(e.get("end"), present=True)
        if s and en and en >= s:
            total += (en - s) / 12
            seen = True
    return total if seen else None


def _ym(v, present=False):
    if not v:
        return None
    if str(v).strip().lower() in ("present", "current", "now"):
        return utcnow().year * 12 + utcnow().month
    m = re.match(r"(\d{4})(?:-(\d{1,2}))?", str(v))
    return int(m.group(1)) * 12 + (int(m.group(2)) if m.group(2) else 6) if m else None


def _term_hit(text: str, kw: dict) -> bool:
    return any(contains_term(text, t) for t in [kw["term"], *kw.get("synonyms", [])])


def evaluate(job: Job, sp: SearchProfile, resume_structured: dict | None = None, now: datetime | None = None) -> MatchResult:
    now = now or utcnow()
    res = MatchResult()
    text = f"{job.title}\n{job.description}"
    ex = sp.exclusions or {}
    kws = [k for k in (sp.keywords or []) if k.get("term")]

    def exclude(code, detail):
        res.exclusions.append({"code": code, "detail": detail, "type": "hard"})

    # ---------------- hard filters ----------------
    jc = norm_company(job.company_name)
    for c in ex.get("companies", []):
        if norm_company(c) and norm_company(c) == jc:
            exclude("excluded_company", c)
    for k in [k["term"] for k in kws if k.get("excluded")] + list(ex.get("keywords", [])):
        if contains_term(text, k):
            exclude("excluded_keyword", k)
    for r in ex.get("roles", []):
        if contains_term(job.title, r):
            exclude("excluded_role", r)
    for ind in ex.get("industries", []):
        if contains_term(text, ind):
            exclude("excluded_industry", ind)

    strict = (sp.strictness or "flexible") == "strict"   # flexible: preferences only lower the score; strict: they exclude
    active = [k for k in kws if not k.get("excluded")]
    hits = {k["term"]: _term_hit(text, k) for k in active}
    required = [k["term"] for k in active if k.get("required")]
    missing = [t for t in required if not hits[t]]
    if missing:  # one reason per job (not per keyword), so run statistics count jobs
        exclude("missing_required_keyword", f"{len(missing)} of {len(required)} required keywords missing: " + ", ".join(missing))
    if strict and sp.match_mode == "and" and active and not all(hits.values()):
        exclude("and_mode_missing_keywords", ", ".join(t for t, h in hits.items() if not h))
    if strict and sp.match_mode == "or" and active and not any(hits.values()):
        exclude("or_mode_no_keyword_found", "none of the keywords appear")

    emp_frac = mode_frac = None
    if sp.employment_types:
        if job.employment_type:
            emp_ok = job.employment_type in sp.employment_types
            if not emp_ok and strict:
                exclude("employment_type", job.employment_type)
            emp_frac = 1.0 if emp_ok else 0.0
        else:
            res.factors.append({"name": "employment_type", "kind": "soft", "detail": "not stated on the listing; not counted against it"})

    if sp.remote_preferences and job.remote_status != "unknown":
        mode_ok = job.remote_status in sp.remote_preferences
        if not mode_ok and strict:
            exclude("work_mode", f"job is {job.remote_status}")
        mode_frac = 1.0 if mode_ok else 0.0

    window_start = now - timedelta(days=sp.date_lookback_days)
    if job.posted_at and job.posted_at_reliable:
        if job.posted_at < window_start:
            exclude("posted_outside_window", job.posted_at.date().isoformat())
    else:
        if sp.unknown_date_policy == "exclude":
            exclude("posted_date_unknown", "policy excludes jobs without a reliable posted date")
        else:
            res.factors.append({"name": "posted_date", "kind": "soft",
                                "detail": "publication date unknown; included per policy (modified date not used)"})

    lp = sp.location_preferences or {}
    sal = compare_salary(job.salary_information, sp.salary_preferences or {})
    if sal["status"] == "comparable" and sal["ok"] is False and (sp.salary_preferences or {}).get("strict"):
        exclude("salary_below_minimum", sal["detail"])

    loc_known = bool(job.location) and job.remote_status != "remote"
    wanted_places = [p for p in (lp.get("city"), lp.get("region"), lp.get("country")) if p]
    loc_ok = None
    if job.remote_status == "remote" and "remote" in (sp.remote_preferences or ["remote"]):
        loc_ok = True
    elif loc_known and wanted_places:
        loc_ok = any(contains_term(job.location, p) for p in wanted_places)
        if not loc_ok and lp.get("strict"):
            exclude("location", job.location)

    # ---------------- scoring ----------------
    comp: dict[str, tuple[float, str] | None] = {}
    titles = [t for t in (sp.role_preferences or {}).get("target_titles", []) + (sp.role_preferences or {}).get("alternative_titles", [])]
    titles += [k["term"] for k in active if k.get("kind") == "title"]
    if titles:
        jt = tokens(norm_title(job.title))
        best, bt = 0.0, ""
        for t in titles:
            tt = tokens(norm_title(t))
            if tt:
                r = len(tt & jt) / len(tt)
                if r > best:
                    best, bt = r, t
        comp["title"] = (best, f"closest target title '{bt}' ({best:.0%} of words)")
    scored = [k for k in active if k.get("kind") != "title"]
    if scored:
        tot = sum(float(k.get("weight", 1)) for k in scored) or 1
        got = sum(float(k.get("weight", 1)) for k in scored if hits[k["term"]])
        matched = [k["term"] for k in scored if hits[k["term"]]]
        comp["keywords"] = (got / tot, f"{len(matched)}/{len(scored)} keywords found: {', '.join(matched) or 'none'}")
    skills = [s for s in (resume_structured or {}).get("skills", []) if is_plausible_skill(s)]
    if skills:
        found = [s for s in skills if contains_term(text, s)]
        comp["skills"] = (min(1.0, len(found) / min(8, len(skills))), f"{len(found)} of your documented skills appear: {', '.join(found[:8]) or 'none'}")
    if loc_ok is not None:
        comp["location"] = (1.0 if loc_ok else 0.0, f"{job.location or job.remote_status}")
    if not strict and emp_frac is not None:   # flexible: a mismatch costs score instead of excluding the job
        comp["employment"] = (emp_frac, f"job is {job.employment_type}; you want {', '.join(sp.employment_types)}")
    if not strict and mode_frac is not None:
        comp["work_mode"] = (mode_frac, f"job is {job.remote_status}; you want {', '.join(sp.remote_preferences)}")
    if sal["status"] == "comparable":
        comp["salary"] = (1.0 if sal["ok"] else 0.0, sal["detail"])
    elif sal["status"] == "not_comparable":
        res.factors.append({"name": "salary", "kind": "soft", "detail": f"not compared: {sal['detail']}"})
    want_sen = (sp.role_preferences or {}).get("seniority")
    if want_sen:
        comp["seniority"] = (1.0 if contains_term(job.title, want_sen) or
                             not any(contains_term(job.title, s) for s in SENIORITY) else 0.0,
                             f"wanted '{want_sen}', title '{job.title}'")

    need, cy = years_required(job.description), candidate_years(resume_structured)
    if need and cy is not None and cy + 0.5 < need:
        res.factors.append({"name": "experience", "kind": "soft",
                            "detail": f"listing asks ~{need} years, resume documents ~{cy:.1f}"})

    if comp:
        met = sum(1 for f_, _ in comp.values() if f_ >= 0.5)
        res.factors.append({"name": "criteria_met", "kind": "summary", "detail": f"{met} of {len(comp)} of your criteria are met (criteria the job does not state are not counted)"})
    total_w = sum(WEIGHTS[k] for k in comp)
    earned = 0.0
    for k, (frac, detail) in comp.items():
        e = WEIGHTS[k] * frac
        earned += e
        res.factors.append({"name": k, "kind": "soft", "weight": WEIGHTS[k], "earned": round(e, 1), "detail": detail})
    res.score = round(100 * earned / total_w, 1) if total_w else 50.0
    if not total_w:
        res.factors.append({"name": "score", "kind": "soft", "detail": "no scoring criteria configured; neutral score"})
    res.qualified = not res.exclusions and res.score >= sp.min_match_score
    if not res.exclusions and res.score < sp.min_match_score:
        res.exclusions.append({"code": "below_min_score", "type": "threshold",
                               "detail": f"{res.score} < {sp.min_match_score}"})
    return res
