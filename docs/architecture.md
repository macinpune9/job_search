# Architecture

```
Next.js (App Router, Tailwind)  ──REST/JSON, bearer token──▶  FastAPI (app/main.py)
                                                                │
                      routers/  auth users resumes searches jobs applications misc
                                                                │
                      services/ ingest · matching · resume_parser · resume_gen · versions
                                applications · engine · reports · scheduler · keywords
                      connectors/ base · boards (Greenhouse, Lever, Ashby)   ◀── plugin registry
                                                                │
                      SQLAlchemy 2 ──▶ SQLite (dev) / PostgreSQL     Storage (Fernet-encrypted files)
scheduler process (python -m app.scheduler | Celery beat) ──▶ same services, DB-backed locks
```

## Repository layout
```
backend/app/  config db models security deps ratelimit main scheduler worker
  routers/    auth users resumes searches jobs applications misc
  services/   textutil ingest matching resume_parser resume_gen versions keywords
              applications engine reports scheduler
  connectors/ base boards __init__ (registry)
backend/alembic/  migrations      backend/tests/  83 tests
frontend/app/(app)/  dashboard profile resumes preferences jobs ready history reports automation integrations settings
frontend/components/ lib/  ui kit + API client
```

## Key design decisions

**Facts come from one place.** `Resume.structured_profile` (parsed, then corrected by the user) is the only source of
candidate facts. `resume_gen.generate` can only *copy and reorder* from it. `resume_gen.validate` is a separate check run on
every generated **and user-edited** version: unsupported skills, roles, dates, degrees, certifications, numbers, and any
job-description term not present in the source resume are errors that block approval. This also defends against prompt
injection: job text is data, never instructions, and the deterministic generator has nothing to inject into. If an LLM provider
is added later, its output must pass the same validator before it can be stored as `passed`.

**Identity and dedup** (`services/ingest.py`). Per-source identity is `(source_name, source_job_id)` (unique), then normalized
URL. Across sources a job merges only when company+title+location **and** description fingerprint agree
(`Job.canonical_identity` unique). Same loose key with different text creates a *separate* job flagged `needs_dedup_review`.

**Dates.** `posted_at` is only ever an original publication date from the source (`posted_at_reliable`). Modified dates are
stored separately and never promoted. Unknown dates follow the profile policy (include-flagged / exclude).

**Incremental search.** Every run re-reads each board in full (these APIs have no `since`), upserts, then evaluates only
jobs not already matched for that profile as "new". The lookback window applies every run, so late-indexed older postings
are still found, and old jobs are never re-reported (`JobMatch.first_run_id`). Closed-job detection runs only when a source
reports a *complete* enumeration. Cursors/health are stored per `source:board`.

**Matching.** Hard filters (exclusions, required keywords, AND/OR mode, employment type, work mode, date window, optionally
strict salary/location) exclude with a recorded reason. Soft factors produce an explained 0–100 score renormalised over the
factors that had data. Salary is compared only when currency, period and gross/net basis are comparable (periods are
annualised; there is no FX conversion).

**Application integrity** (`services/applications.py`). `UNIQUE(user_id, job_id)` + get-or-create; submission is claimed with an
atomic `UPDATE … WHERE status IN (ready, failed) AND approved_at IS NOT NULL`; only the winner calls the submitter. An
unknown outcome (exception or unconfirmed response) becomes `submission_confirmation_pending` and is **never auto-retried**.
Worker crashes are recovered the same way. Only a confirming submitter result, or an explicit user attestation (recorded as
such), produces `submitted`. Resume/cover-letter versions are immutable; edits create new versions and a used version is locked.
`ApplicationEvent` is append-only.

**Scheduling.** `RunLock` table (insert-or-steal-if-expired) gives per-profile mutual exclusion across processes. A tick
recovers stale runs/applications, selects due profiles, and runs each with retries (`retry_base * 2^n`, `MAX_TASK_RETRIES`),
then dead-letters. One failing source never aborts the others.

**Automation levels.** `discovery_only` → nothing prepared; `prepare_for_review` (default); `fill_and_request_approval`
(reserved; behaves as prepare); `auto_submit_authorized` requires an explicit consent timestamp (revoked on leaving the mode),
is blocked while paused, and can only act through registered submitters.

## Career snapshot, CV parsing and flexible matching
- `resume_parser.py`: section headings (incl. interests/languages/personal so their lines never leak into Skills), labelled `Company/Role/Period`
  project blocks, and a fallback that builds entries from any date range when a CV has no Experience heading. `skillvocab.is_plausible_skill`
  drops school, places, hobbies, spoken languages, contact details, dates and sentences.
- `insights.py`: evidence-ranked picks (3 roles / 5 technical / 3 behavioural / 5 tools). Proficiency is *estimated* from years of use, recency and
  number of mentions. Roles come from job titles, else titles in the profile summary, else the strongest skill cluster (labelled as inferred).
  AI results are accepted only with a verbatim quote from the CV/LinkedIn text; unsupported items are dropped and the list is topped up from rules.
- `ai_structure.py`: optional AI reading of odd layouts; PII redacted before sending; every role, bullet, skill, degree and certificate must be
  supported by the CV text; identity fields always come from the rule parser.
- `matching.py`: `strictness` = `flexible` (default) or `strict`. Flexible turns employment type / work mode / location mismatches into lower
  scores; criteria a job does not state are skipped, so the score is the percentage of *stated* criteria met.

## AI layer (optional)
`services/llm.py` (provider interface + Claude adapter with structured outputs, minimised facts, injection-framed prompts),
`ai_match.py` (blend AI fit with rules; budget; cache), `ai_resume.py` (tailor -> deterministic validate -> AI audit -> retry ->
rules-based fallback). Rules always run first and own hard filters; AI only refines scores and proposes reworded text.
Still heuristic and not AI: resume parsing (`resume_parser.py`).
