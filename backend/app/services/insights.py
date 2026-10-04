"""Career snapshot: the BEST few roles, skills and tools from a CV (+ optional LinkedIn text), instead of everything.

Rules-first (works offline, no data leaves the server); the AI path (opt-in) refines it and must back every suggestion with a
verbatim quote from the CV/LinkedIn text, otherwise the item is dropped.

Selection: 2-3 roles, 5 technical skills, 2-3 behavioural skills, 5 tools (with an *estimated* proficiency from years of use).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .matching import _ym
from .skillvocab import (BEHAV_ALIAS, BEHAVIOURAL, TECH_ALIAS, TECHNICAL, TOOL_ALIAS, TOOLS, classify, is_plausible_skill, norm)
from .textutil import contains_term, fold, norm_title, tokens

N_ROLES, N_TECH, N_BEHAV, N_TOOLS = 3, 5, 3, 5
LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]
LEVEL_WEIGHT = {"Beginner": 0.6, "Intermediate": 1.0, "Advanced": 1.5, "Expert": 2.0}

TITLE_SYN = {
    "software test engineer": ["QA Engineer", "Test Engineer", "Software Tester"],
    "software test automation engineer": ["Test Automation Engineer", "QA Automation Engineer", "SDET"],
    "test automation engineer": ["QA Automation Engineer", "Software Test Automation Engineer", "SDET"],
    "qa automation engineer": ["Test Automation Engineer", "SDET", "QA Engineer"], "qa test automation engineer": ["Test Automation Engineer", "QA Automation Engineer", "SDET"],
    "automation engineer": ["Test Automation Engineer", "QA Automation Engineer"], "qa analyst": ["Test Analyst", "QA Engineer"],
    "qa engineer": ["Test Engineer", "Quality Assurance Engineer"], "test engineer": ["QA Engineer", "Software Test Engineer"],
    "test analyst": ["QA Analyst", "Test Engineer"], "test manager": ["QA Manager", "Test Lead"],
    "software engineer": ["Software Developer", "Backend Engineer"], "software developer": ["Software Engineer"],
    "backend developer": ["Backend Engineer", "Software Engineer"], "frontend developer": ["Frontend Engineer", "UI Engineer"],
    "full stack developer": ["Full Stack Engineer", "Software Engineer"], "devops engineer": ["Site Reliability Engineer", "Platform Engineer"],
    "data analyst": ["Business Analyst", "Analytics Specialist"], "data scientist": ["Machine Learning Engineer", "Applied Scientist"],
    "data engineer": ["Analytics Engineer", "ETL Developer"], "business analyst": ["Data Analyst", "Requirements Engineer"],
    "project manager": ["Program Manager", "Delivery Manager"], "product manager": ["Product Owner"], "accountant": ["Finance Associate", "Accounting Specialist"],
}
_SENIORITY = re.compile(r"\b(junior|jr\.?|senior|sr\.?|lead|staff|principal|head of|intern|trainee|graduate|associate)\b", re.I)


def _clean_title(t: str) -> str:
    t = re.sub(r"\((?:[mwfdx]\s*/\s*){1,3}[mwfdx]\)|\b\d{2}\s*-\s*\d{2}\s*%", "", t or "", flags=re.I)
    t = re.split(r"\s[-–|@]\s", t)[0]
    return re.sub(r"\s+", " ", t).strip(" ,-")


def _family(title: str) -> str:
    return norm_title(_SENIORITY.sub("", title))


def _recency(end_ym: int | None, now_ym: int) -> float:
    if end_ym is None or end_ym >= now_ym - 6:
        return 1.0
    return 0.85 ** ((now_ym - end_ym) / 12)


def _union_months(spans: list[tuple[int, int]]) -> int:
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(spans):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    return total + (cur_e - cur_s if cur_e is not None else 0)


def _roles(structured: dict, linkedin: dict | None) -> list[dict]:
    now = datetime.now(timezone.utc)
    now_ym = now.year * 12 + now.month
    out, seen = [], set()
    for src, exps in (("cv", structured.get("experience", [])), ("linkedin", (linkedin or {}).get("experience", []))):
        for e in exps:
            key = (norm(e.get("company") or ""), norm_title(e.get("title") or ""))
            if key in seen or not (e.get("title") or e.get("bullets")):
                continue
            seen.add(key)
            s, en = _ym(e.get("start")), _ym(e.get("end"), present=True) or (now_ym if _ym(e.get("start")) else None)
            out.append({"title": e.get("title") or "", "company": e.get("company") or "", "start": s, "end": en, "src": src,
                        "bullets": [b for b in e.get("bullets", []) if b], "text": fold(" ".join([e.get("title") or "", *e.get("bullets", [])])).lower()})
    out.sort(key=lambda r: (-(r["end"] or 0), -(r["start"] or 0)))
    return out


def _aliases(kind: str, canon: str) -> list[str]:
    table = {"tool": TOOLS, "technical": TECHNICAL}[kind]
    return list(dict.fromkeys([canon.lower(), *table[canon]]))


def _level(years: float, last_used_years_ago: float, mentions: int = 3) -> str:
    i = 0 if years < 1 else 1 if years < 3 else 2 if years < 6 else 3
    if last_used_years_ago > 3:
        i -= 1
    if mentions < 2:      # one passing mention is not evidence of deep expertise
        i = min(i, 1)
    elif mentions < 3:
        i = min(i, 2)
    return LEVELS[max(0, i)]


def _score_term(kind: str, canon: str, roles: list[dict], listed: bool, cert_text: str, li_skills: set[str], now_ym: int) -> dict | None:
    aliases = _aliases(kind, canon)
    score, hit_roles, mentions = 0.0, [], 0
    for r in roles:
        n = sum(1 for a in aliases if contains_term(r["text"], a))
        if n:
            hit_roles.append(r)
            mentions += sum(r["text"].count(a) for a in aliases if len(a) > 2) or n
            score += min(n, 3) * _recency(r["end"], now_ym)
    if listed:
        score += 1.0
    if any(contains_term(cert_text, a) for a in aliases):
        score += 0.5
    if any(norm(a) in li_skills for a in aliases):
        score += 0.75
    if score <= 0:
        return None
    if listed and hit_roles:
        mentions += 1        # named in the skills list AND used in real work
    spans = [(r["start"], r["end"]) for r in hit_roles if r["start"] and r["end"] and r["end"] >= r["start"]]
    years = _union_months(spans) / 12 if spans else 0.0
    last_end = max((r["end"] for r in hit_roles if r["end"]), default=None)
    ago = (now_ym - last_end) / 12 if last_end else 0
    if hit_roles:
        level = _level(years, ago, mentions)
        ev = (f"~{years:.0f} yr{'s' if round(years) != 1 else ''} across {len(hit_roles)} role{'s' if len(hit_roles) != 1 else ''}"
              if years >= 1 else f"used in {len(hit_roles)} role{'s' if len(hit_roles) != 1 else ''}")
        if ago > 1:
            ev += f", last used {round(ago)} yrs ago"
    else:
        level, ev = "Intermediate", "listed on your CV (no project evidence; adjust if needed)"
    return {"name": canon, "proficiency": level, "evidence": ev, "years": round(years, 1), "score": round(score, 2)}


def _behavioural(roles: list[dict], summary_text: str, listed: set[str], now_ym: int) -> list[dict]:
    out = []
    for canon, (aliases, verbs) in BEHAVIOURAL.items():
        score, bullets = 0.0, 0
        for r in roles:
            hits = sum(1 for b in r["bullets"] if any(re.search(rf"(?<![a-z]){re.escape(v)}", fold(b).lower()) for v in verbs))
            if hits:
                bullets += hits
                score += min(hits, 3) * _recency(r["end"], now_ym)
        explicit = any(contains_term(summary_text, a) for a in aliases) or canon in listed
        if explicit:
            score += 1.5
        if bullets >= 1 or explicit:
            out.append({"name": canon, "evidence": ("stated on your CV" if explicit and not bullets else f"shown in {bullets} achievement{'s' if bullets != 1 else ''}"),
                        "score": round(score + (0.5 if bullets >= 2 else 0), 2)})
    return sorted(out, key=lambda x: (-x["score"], x["name"]))


_TITLE_TAIL = r"(?:Engineer|Tester|Analyst|Developer|Consultant|Manager|Lead|Architect|Specialist|Administrator|Designer|Scientist|Officer|Coordinator|Technician)"
_TITLE_RE = re.compile(rf"\b((?:[A-Z][\w/&+.\-]*\s+){{1,5}}{_TITLE_TAIL})\b")


def _titles_from_text(text: str) -> list[str]:
    """Job-title phrases mentioned in free text (profile summary), most frequent first."""
    counts: dict[str, int] = {}
    for m in _TITLE_RE.finditer(text or ""):
        t = _clean_title(m.group(1))
        if 2 <= len(t.split()) <= 6:
            counts[t] = counts.get(t, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))]


_AUTOMATION = {"Test automation", "Selenium", "Cucumber", "Tosca", "UFT", "Appium", "Cypress", "Playwright", "Robot Framework", "BDD / TDD"}
ROLE_GROUPS = [
    ("testing", {"Test automation", "Manual testing", "Regression testing", "Smoke testing", "Functional testing", "Test design", "Test management",
                 "Defect management", "UAT", "Performance testing", "Security testing", "BDD / TDD", "Selenium", "Postman", "SoapUI", "Tosca", "UFT",
                 "TestRail", "Cucumber", "Appium", "Cypress", "Playwright", "JMeter", "Robot Framework", "Quality assurance", "Unit testing",
                 "Integration testing"}, ["Software Test Engineer", "Test Automation Engineer", "QA Engineer"]),
    ("software", {"Java", "Python", "JavaScript", "TypeScript", "C#", "C++", "Go", "Kotlin", "Spring", "React", "Angular", "Node.js", "Django", "Flask",
                  "FastAPI", ".NET", "Microservices", "REST APIs"}, ["Software Engineer", "Backend Engineer"]),
    ("data", {"SQL", "ETL", "Data analysis", "Data modeling", "Power BI", "Tableau", "Data engineering", "Data validation", "Looker", "Snowflake",
              "Spark", "Airflow"}, ["Data Analyst", "Data Engineer"]),
    ("devops", {"DevOps", "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins", "CI/CD", "AWS", "Azure", "Google Cloud", "Linux"},
     ["DevOps Engineer", "Platform Engineer"]),
    ("management", {"Project management", "Product management", "Business analysis", "Requirements engineering"}, ["Project Manager", "Business Analyst"]),
]


def _roles_from_skills(tech: list[dict], tools: list[dict]) -> list[dict]:
    """Last resort (CV states no job title anywhere): infer realistic titles from the strongest skill cluster."""
    items = tech + tools
    scored = sorted(((sum(i["score"] for i in items if i["name"] in names), sum(1 for i in items if i["name"] in names), key, names, titles)
                     for key, names, titles in ROLE_GROUPS), key=lambda x: (-x[0], x[2]))
    best = scored[0] if scored and (scored[0][0] >= 2 or scored[0][1] >= 2) else None   # strong score, or at least two skills in the cluster
    if not best:
        return []
    titles = list(best[4])
    if best[2] == "testing" and any(i["name"] in _AUTOMATION for i in items):
        titles = ["Test Automation Engineer", "Software Test Engineer", "QA Engineer"]
    out = [{"title": t, "reason": "Inferred from your strongest skills (no job title found on your CV); change it if it is wrong"} for t in titles[:N_ROLES]]
    if len(out) < N_ROLES and len(scored) > 1 and scored[1][1] >= 2:
        out.append({"title": scored[1][4][0], "reason": "Second-strongest skill area on your CV"})
    return out[:N_ROLES]


def _suggest_roles(roles: list[dict], summary: str = "") -> list[dict]:
    titles = [_clean_title(r["title"]) for r in roles if r["title"].strip()]
    from_summary = False
    if not titles:  # CVs whose project blocks carry no job title: use titles mentioned in the profile summary
        titles, from_summary = _titles_from_text(summary)[:3], True
    picked: list[dict] = []
    seen_fam: list[str] = []

    def add(title, reason):
        fam = _family(title)
        if title and len(picked) < N_ROLES and all(len(set(fam.split()) & set(s.split())) / max(1, len(set(fam.split()))) < 0.7 for s in seen_fam):
            picked.append({"title": title, "reason": reason})
            seen_fam.append(fam)

    if titles:
        add(titles[0], "Mentioned in your profile summary" if from_summary else "Your most recent role")
        for t in titles[1:]:
            if len(picked) >= 2:
                break
            add(t, "Also mentioned in your profile summary" if from_summary else "A previous role you can build on")
        syn = TITLE_SYN.get(_family(titles[0]), [])
        for s in syn:
            add(s, f"Equivalent title that other employers use for “{titles[0]}”")
    return picked


def compute(structured: dict, linkedin: dict | None = None) -> dict:
    now = datetime.now(timezone.utc)
    now_ym = now.year * 12 + now.month
    roles = _roles(structured, linkedin)
    raw_skills = list(structured.get("skills", [])) + [s for s in (linkedin or {}).get("skills", []) if isinstance(s, str)]
    listed_ok = [s for s in raw_skills if is_plausible_skill(s)]
    dropped = len(raw_skills) - len(listed_ok)   # school, places, hobbies, spoken languages, sentences...
    listed = {classify(s)[1] or norm(s) for s in listed_ok}
    li_skills = {norm(s) for s in (linkedin or {}).get("skills", []) if isinstance(s, str)}
    cert_text = fold(" ".join(structured.get("certifications", []) + structured.get("achievements", []))).lower()
    summary_text = fold((structured.get("summary") or "") + " " + ((linkedin or {}).get("summary") or "")).lower()

    tools, tech = [], []
    for canon in TOOLS:
        s = _score_term("tool", canon, roles, canon in listed, cert_text, li_skills, now_ym)
        if s:
            tools.append(s)
    for canon in TECHNICAL:
        s = _score_term("technical", canon, roles, canon in listed, cert_text, li_skills, now_ym)
        if s:
            tech.append(s)
    # free-form listed skills we do not know: keep only if the CV shows them in real work
    known = {t["name"].lower() for t in tools + tech}
    for s in listed_ok:
        kind, canon = classify(s)
        if kind or norm(s) in known or canon:
            continue
        hit = [r for r in roles if contains_term(r["text"], s)]
        if hit:
            tech.append({"name": s.strip(), "proficiency": _level(_union_months([(r["start"], r["end"]) for r in hit if r["start"] and r["end"]]) / 12, 0),
                         "evidence": f"used in {len(hit)} role{'s' if len(hit) != 1 else ''}", "years": 0.0, "score": round(1.0 + 0.5 * len(hit), 2)})
    rank = lambda xs: sorted(xs, key=lambda x: (-x["score"], x["name"]))  # noqa: E731
    tools, tech, behav = rank(tools), rank(tech), _behavioural(roles, summary_text, listed, now_ym)
    spans = [(r["start"], r["end"]) for r in roles if r["start"] and r["end"] and r["end"] >= r["start"]]
    role_sugg = _suggest_roles(roles, (structured.get("summary") or "") + " " + ((linkedin or {}).get("summary") or "")) \
        or _roles_from_skills(tech[:N_TECH], tools[:N_TOOLS])
    sen = None
    if role_sugg:
        m = _SENIORITY.search(role_sugg[0]["title"])
        sen = m.group(1).lower().rstrip(".").replace("sr", "senior").replace("jr", "junior") if m else None
    return {
        "source": "rules", "used_linkedin": bool(linkedin and (linkedin.get("skills") or linkedin.get("experience"))),
        "total_years": round(_union_months(spans) / 12, 1), "seniority": sen, "ignored_items": dropped,
        "roles": role_sugg,
        "technical_skills": tech[:N_TECH], "tools": tools[:N_TOOLS], "behavioural_skills": behav[:N_BEHAV],
        "extras": {"technical": tech[N_TECH:N_TECH + 6], "tools": tools[N_TOOLS:N_TOOLS + 6], "behavioural": behav[N_BEHAV:N_BEHAV + 3]},
    }


# ---------------- AI path: every item must be quoted from the CV ----------------
def source_text(structured: dict, linkedin: dict | None) -> str:
    parts = [structured.get("summary") or "", *structured.get("skills", []), *structured.get("certifications", []), *structured.get("achievements", [])]
    for e in structured.get("experience", []):
        parts += [e.get("title") or "", e.get("company") or "", *e.get("bullets", [])]
    if linkedin:
        parts += [linkedin.get("summary") or "", *[s for s in linkedin.get("skills", []) if isinstance(s, str)]]
        for e in linkedin.get("experience", []):
            parts += [e.get("title") or "", e.get("company") or "", *e.get("bullets", [])]
    return norm(" \n ".join(p for p in parts if p))


def _name_in_text(name: str, hay: str) -> bool:
    kind, canon = classify(name)
    aliases = [name] + (_aliases(kind, canon) if kind in ("tool", "technical") else [])
    return any(contains_term(hay, a) for a in aliases)


def merge_ai(rules: dict, ai, hay: str) -> dict:
    """Accept AI suggestions only when backed by a verbatim quote (and, for tools/technical, when the name occurs in the text)."""
    dropped = 0
    rules_level = {t["name"].lower(): t for t in rules["tools"] + rules["technical_skills"] + sum(rules["extras"].values(), [])}

    def ok(item, needs_name):
        nonlocal dropped
        ev = norm(item.evidence)
        name_in = _name_in_text(item.name, hay)
        if len(ev) < 6 or ev not in hay or (needs_name and not name_in) or not item.name.strip() or len(item.name) > 40:
            dropped += 1
            return None
        lvl = item.proficiency.strip().title()
        if lvl not in LEVELS:
            lvl = rules_level.get(item.name.lower(), {}).get("proficiency", "Intermediate")
        return {"name": item.name.strip(), "proficiency": lvl, "evidence": item.evidence.strip()[:140], "years": rules_level.get(item.name.lower(), {}).get("years", 0.0)}

    def take(items, needs_name, limit, fallback):
        got, names = [], set()
        for it in items:
            r = ok(it, needs_name)
            if r and r["name"].lower() not in names:
                got.append(r)
                names.add(r["name"].lower())
        for f in fallback:  # top up from rules if the AI returned too few valid items
            if len(got) >= limit:
                break
            if f["name"].lower() not in names:
                got.append(f)
                names.add(f["name"].lower())
        return got[:limit]

    roles = [{"title": r.title.strip()[:70], "reason": r.reason.strip()[:160]} for r in ai.roles if r.title.strip()][:N_ROLES]
    seen = {_family(r["title"]) for r in roles}
    for r in rules["roles"]:
        if len(roles) >= 2 and len(roles) >= len(ai.roles):
            break
        if _family(r["title"]) not in seen and len(roles) < N_ROLES:
            roles.append(r)
    out = dict(rules)
    out.update(source="ai", roles=roles,
               technical_skills=take(ai.technical_skills, True, N_TECH, rules["technical_skills"]),
               tools=take(ai.tools, True, N_TOOLS, rules["tools"]),
               behavioural_skills=take(ai.behavioural_skills, False, N_BEHAV, rules["behavioural_skills"]), ai_dropped=dropped)
    return out


# ---------------- turn a (possibly edited) selection into search-profile settings ----------------
def selection_to_profile(roles: list[str], technical: list[str], behavioural: list[str], tools: list[dict]) -> dict:
    def syn(name: str) -> list[str]:
        kind, canon = classify(name)
        table = {"tool": TOOLS, "technical": TECHNICAL, "behavioural": {k: v[0] for k, v in BEHAVIOURAL.items()}}.get(kind or "", {})
        return [a for a in table.get(canon, []) if norm(a) != norm(name)][:6]

    kws = []
    for i, r in enumerate(roles[:N_ROLES]):
        kws.append({"term": r, "kind": "title", "required": False, "excluded": False, "synonyms": [], "weight": 2.0 if i == 0 else 1.5})
    for t in technical:
        kws.append({"term": t, "kind": "skill", "required": False, "excluded": False, "synonyms": syn(t), "weight": 1.5})
    for t in tools:
        kws.append({"term": t["name"], "kind": "tool", "required": False, "excluded": False, "synonyms": syn(t["name"]),
                    "weight": LEVEL_WEIGHT.get(str(t.get("proficiency", "")).title(), 1.0)})
    for b in behavioural:
        kws.append({"term": b, "kind": "behavioural", "required": False, "excluded": False, "synonyms": syn(b), "weight": 0.4})
    alt = []
    for r in roles[:2]:
        alt += [s for s in TITLE_SYN.get(_family(r), []) if norm(s) not in {norm(x) for x in roles + alt}]
    return {"keywords": kws, "target_titles": roles[:N_ROLES], "alternative_titles": alt[:5]}
