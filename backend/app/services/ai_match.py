"""AI job-fit scoring layered on top of the rules-based match.

Rules (matching.evaluate) always run first and own the HARD filters: a job excluded by a hard filter is never sent to the
model. For the rest, the model's 0-100 fit score is blended with the rules score. Results are cached per
(resume facts, job text, model), and each run has a call budget, so cost is bounded and repeat runs are free.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Job, JobMatch, Resume, SearchProfile, SearchRun
from .llm import LLMAuthError, LLMClient, LLMError, facts_for_ai
from .matching import MatchResult
from .textutil import sha

log = logging.getLogger("jobpilot.ai")


def facts_hash(structured: dict) -> str:
    return sha(json.dumps(facts_for_ai(structured), sort_keys=True, ensure_ascii=False))


def ai_key(fhash: str, job: Job) -> str:
    return sha(fhash, job.normalized_description_hash, job.title, get_settings().ai_model)


def has_hard_exclusion(exclusions: list[dict]) -> bool:
    return any(e.get("type") == "hard" for e in exclusions or [])


def apply_ai(mr: MatchResult, ai: dict, sp: SearchProfile) -> None:
    """Blend a (cached or fresh) AI fit result into a rules-based MatchResult, in place."""
    w = get_settings().ai_blend_weight
    fit = max(0, min(100, int(ai["fit_score"])))
    mr.factors = [f for f in mr.factors if f.get("name") != "ai_fit"]
    detail = f"AI fit {fit}/100. {ai.get('reasoning', '')}".strip()
    if ai.get("matched"):
        detail += " Strengths: " + "; ".join(ai["matched"]) + "."
    if ai.get("gaps"):
        detail += " Gaps: " + "; ".join(ai["gaps"]) + "."
    mr.factors.append({"name": "ai_fit", "kind": "soft", "weight": round(w * 100), "earned": round(w * fit, 1), "detail": detail})
    mr.score = round((1 - w) * mr.score + w * fit, 1)
    hard = [e for e in mr.exclusions if e.get("type") == "hard"]
    mr.exclusions = hard
    mr.qualified = not hard and mr.score >= sp.min_match_score
    if not hard and not mr.qualified:
        mr.exclusions.append({"code": "below_min_score", "type": "threshold", "detail": f"{mr.score} < {sp.min_match_score}"})


def ai_pass(db: Session, sp: SearchProfile, resume: Resume, llm: LLMClient, run: SearchRun, stats, new_match_ids: list[int],
            errors: list[str]) -> None:
    """Call the model for jobs that passed every hard filter and have no valid cached result, within the run budget."""
    s = get_settings()
    structured = resume.structured_profile or {}
    facts, fh = facts_for_ai(structured), facts_hash(structured)
    rows = db.execute(select(JobMatch, Job).join(Job, Job.id == JobMatch.job_id).where(
        JobMatch.search_profile_id == sp.id, JobMatch.evaluated_at >= run.started_at, Job.status == "open")).all()
    todo = [(m, j) for m, j in rows
            if not has_hard_exclusion(m.exclusion_reasons) and (m.rules_score or 0) >= s.ai_min_rules_score
            and not (m.ai_analysis and m.ai_analysis.get("key") == ai_key(fh, j))]
    todo.sort(key=lambda mj: -(mj[0].rules_score or 0))
    calls = 0
    for m, j in todo:
        if calls >= s.ai_max_fit_calls_per_run:
            stats["ai_skipped_budget"] += 1
            continue
        try:
            r = llm.fit(facts, j.title, j.company_name, j.description)
        except LLMAuthError as e:
            errors.append(f"AI: {e}")
            stats["ai_errors"] += 1
            break
        except LLMError as e:
            stats["ai_errors"] += 1
            log.warning("AI fit failed for job %s: %s", j.id, e)
            continue
        calls += 1
        m.ai_analysis = {"key": ai_key(fh, j), "fit_score": r.fit_score, "matched": r.matched, "gaps": r.gaps,
                         "reasoning": r.reasoning, "model": llm.model}
        was_q = m.qualified
        mr = MatchResult(score=m.rules_score or 0.0, factors=list(m.matching_factors or []), exclusions=[], qualified=False)
        apply_ai(mr, m.ai_analysis, sp)
        m.match_score, m.matching_factors, m.exclusion_reasons, m.qualified = mr.score, mr.factors, mr.exclusions, mr.qualified
        if m.qualified and not was_q:
            stats["qualified_new"] += 1
            m.first_run_id = run.id
            if m.id not in new_match_ids:
                new_match_ids.append(m.id)
        elif was_q and not m.qualified and m.first_run_id == run.id:
            stats["qualified_new"] -= 1
    stats["ai_fit_calls"] += calls
