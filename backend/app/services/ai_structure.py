"""Optional AI structuring of a CV for layouts the rules cannot follow (opt-in).

Privacy: email addresses, phone numbers, links and the first line (usually the name) are removed from the text before it is sent.
Safety: nothing the model returns is trusted. Every role, bullet, skill, degree and certificate must be found in the CV text
(token overlap), otherwise it is dropped. Contact details and the name always come from the rule-based parser.
"""
from __future__ import annotations

import re

from .llm import LLMClient
from .resume_parser import EMAIL, PHONE, _norm_date, parse_structured
from .skillvocab import is_plausible_skill, norm
from .textutil import tokens

_URL = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(?:com|ch|org|net)/\S*|linkedin\.com\S*)", re.I)


def redact_for_ai(text: str) -> str:
    lines = text.splitlines()
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is not None and len(lines[first].split()) <= 4 and not re.search(r"\d|@", lines[first]):
        lines[first] = ""                                   # the candidate's name
    t = "\n".join(lines)
    return PHONE.sub("[phone]", _URL.sub("[link]", EMAIL.sub("[email]", t)))


def _supported(item: str, hay_tokens: set[str], threshold: float = 0.75) -> bool:
    toks = tokens(item)
    return bool(toks) and len(toks & hay_tokens) / len(toks) >= threshold


def structure_with_ai(llm: LLMClient, text: str) -> tuple[dict, dict]:
    """Returns (structured_profile, report). Raises LLMError on provider failure (caller decides the fallback)."""
    base = parse_structured(text)                           # name/email/phone + fallback values
    ai = llm.structure_cv(redact_for_ai(text))
    hay = tokens(text)
    flat = norm(text)
    dropped = {"roles": 0, "bullets": 0, "skills": 0, "other": 0}

    exp = []
    for r in ai.experience:
        company, title = r.company.strip(), r.title.strip()
        if not ((company and norm(company) in flat) or (title and norm(title) in flat)):
            dropped["roles"] += 1                           # neither the company nor the title exists in the CV: invented
            continue
        bullets = []
        for b in r.bullets:
            if b.strip() and _supported(b, hay):
                bullets.append(b.strip())
            else:
                dropped["bullets"] += 1
        exp.append({"title": title if (not title or norm(title) in flat) else "", "company": company if norm(company) in flat else "",
                    "start": _norm_date(r.start), "end": _norm_date(r.end), "bullets": bullets[:40]})

    skills = []
    for s in ai.skills:
        if is_plausible_skill(s) and norm(s) in flat and norm(s) not in {norm(x) for x in skills}:
            skills.append(s.strip())
        else:
            dropped["skills"] += 1
    edu = [{"text": e.text.strip(), "degree": None, "year": (re.search(r"(19|20)\d{2}", e.text) or [None])[0]}
           for e in ai.education if e.text.strip() and _supported(e.text, hay)]
    certs = [c.strip() for c in ai.certifications if c.strip() and _supported(c, hay)]
    dropped["other"] = (len(ai.education) - len(edu)) + (len(ai.certifications) - len(certs))

    out = {**base, "experience": exp or base["experience"], "skills": skills or base["skills"],
           "education": edu or base["education"], "certifications": certs or base["certifications"],
           "summary": (ai.summary.strip() if ai.summary.strip() and _supported(ai.summary, hay) else base["summary"])[:1500], "parsed_by": "ai"}
    return out, {"roles": len(exp), "skills": len(skills), "dropped": dropped}
