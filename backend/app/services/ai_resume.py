"""AI resume tailoring, fenced in by deterministic checks.

The model proposes only: a summary, a skill ordering, and reworded bullets per role INDEX. Titles, companies and dates are
copied from the source resume by code, so they cannot be altered. The proposal is then (1) run through resume_gen.validate
(unsupported skills/numbers/credentials/terms are errors), (2) audited by a second model pass for changed meaning, and only
a proposal that passes both is used. After one retry with the errors as feedback, we fall back to the rules-based version.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..models import Job
from . import resume_gen
from .llm import LLMAuthError, LLMClient, LLMError, Tailored, facts_for_ai

log = logging.getLogger("jobpilot.ai")


def _same(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def merge(src: dict, t: Tailored) -> dict:
    content = {k: (list(v) if isinstance(v, list) else v) for k, v in src.items()}
    summary = (t.summary or "").strip()[:600]
    if summary:
        content["summary"] = summary
    src_skills = list(src.get("skills", []))
    lookup = {s.lower(): s for s in src_skills}
    ordered: list[str] = []
    for s in t.skills:
        canon = lookup.get(s.strip().lower())
        if canon and canon not in ordered:
            ordered.append(canon)
        elif not canon:
            ordered.append(s.strip())  # unsupported on purpose: validate() will flag it
    content["skills"] = ordered + [s for s in src_skills if s not in ordered]
    by_index = {r.index: r for r in t.roles}
    exp = []
    for i, e in enumerate(src.get("experience", [])):
        r = by_index.get(i)
        bullets = [b.strip() for b in (r.bullets if r else []) if b and b.strip()]
        exp.append({**e, "bullets": bullets or list(e.get("bullets", []))})  # role metadata always from source
    content["experience"] = exp
    return content


def _audit_view(src: dict, content: dict) -> dict:
    return {"summary": content.get("summary", ""), "skills": content.get("skills", []),
            "roles": [{"index": i, "title": e.get("title"), "original_bullets": e.get("bullets", []),
                       "rewritten_bullets": content["experience"][i]["bullets"]}
                      for i, e in enumerate(src.get("experience", []))]}


def tailor_with_ai(llm: LLMClient, src: dict, job: Job) -> tuple[dict | None, dict]:
    """Returns (content or None, meta). None means: use the rules-based resume instead."""
    facts = facts_for_ai(src)
    job_text = f"{job.title}\n{job.description}"
    feedback: list[str] | None = None
    meta: dict = {"used": False, "model": llm.model, "attempts": 0}
    for attempt in (1, 2):
        meta["attempts"] = attempt
        try:
            proposal = llm.tailor(facts, job.title, job.company_name, job.description, feedback)
        except LLMAuthError:
            meta["fallback_reason"] = "AI credentials were rejected"
            return None, meta
        except LLMError as e:
            meta["fallback_reason"] = str(e)
            return None, meta
        content = merge(src, proposal)
        result = resume_gen.validate(content, src, job_text)
        problems = [f"{i['code']}: {i['detail']}" for i in result["issues"] if i["severity"] == "error"]
        verified = False
        if not problems and get_settings().ai_verify_tailoring:
            try:
                verdict = llm.verify(facts, _audit_view(src, content))
                problems += [f"unsupported_claim: {c.statement} ({c.reason})" for c in verdict.unsupported_claims]
                verified = not verdict.unsupported_claims
            except LLMError as e:  # cannot confirm -> do not use
                problems.append(f"verification unavailable: {e}")
        if not problems:
            rewrites = [{"role": f"{e.get('title')} @ {e.get('company')}", "before": e.get("bullets", []),
                         "after": content["experience"][i]["bullets"]}
                        for i, e in enumerate(src.get("experience", []))
                        if [b.strip().lower() for b in e.get("bullets", [])] != [b.strip().lower() for b in content["experience"][i]["bullets"]]]
            result["ai_verified"] = verified
            meta.update(used=True, verified=verified, rewrites=rewrites, validation=result,
                        summary_changed=not _same(content.get("summary", ""), src.get("summary", "")))
            return content, meta
        feedback = problems
        log.info("AI tailoring attempt %s rejected for job %s: %d problem(s)", attempt, job.id, len(problems))
    meta["fallback_reason"] = "AI draft failed the fact-check twice; used the rules-based resume"
    meta["rejected_problems"] = (feedback or [])[:10]
    return None, meta
