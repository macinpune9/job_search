"""Editable keyword suggestions derived from the user's own documented resume (nothing is auto-required)."""
from __future__ import annotations

import re

TITLE_SYNONYMS = {
    "software engineer": ["software developer", "programmer"],
    "software developer": ["software engineer"],
    "data scientist": ["machine learning scientist", "applied scientist"],
    "data analyst": ["business analyst", "analytics specialist"],
    "product manager": ["product owner"],
    "project manager": ["program manager", "delivery manager"],
    "devops engineer": ["site reliability engineer", "platform engineer"],
    "frontend developer": ["front-end developer", "ui engineer"],
    "backend developer": ["back-end developer", "server-side engineer"],
    "accountant": ["accounting specialist", "finance associate"],
}
SENIORITY = ["junior", "senior", "lead", "staff", "principal", "head", "manager", "director"]


def suggest(structured: dict) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    def add(term, kind, **kw):
        t = (term or "").strip()
        if t and t.lower() not in seen and len(t) <= 60:
            seen.add(t.lower())
            out.append({"term": t, "kind": kind, "required": False, "excluded": False, "synonyms": kw.get("synonyms", []),
                        "weight": kw.get("weight", 1.0), "source": kw.get("source", "resume")})

    for i, e in enumerate(structured.get("experience", [])):
        title = e.get("title", "")
        base = re.sub(r"\b(senior|junior|lead|staff|principal|sr\.?|jr\.?)\b", "", title, flags=re.I).strip(" ,-")
        syn = TITLE_SYNONYMS.get(base.lower(), [])
        add(title, "title", synonyms=syn, weight=2.0 if i == 0 else 1.0, source="current/previous role" if i else "most recent role")
        for s in SENIORITY:
            if re.search(rf"\b{s}\b", title, re.I):
                add(s, "seniority", weight=0.5)
    for s in structured.get("skills", []):
        add(s, "skill")
    for c in structured.get("certifications", []):
        add(c, "certification", weight=1.5)
    return out
