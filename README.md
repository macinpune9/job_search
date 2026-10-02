# JobPilot

Job discovery, honest ATS resume tailoring, and application tracking. FastAPI + SQLAlchemy backend, Next.js frontend,
a lock-protected scheduler that runs every 24 hours with no browser open.

**Principles:** the uploaded resume is the only source of facts (generated resumes can only *select and reorder* them and
are independently validated); nothing is marked "submitted" without confirmation; a job can never be applied to twice;
no scraping of sites that forbid it; automation defaults to review-before-submit.

> **Status: working foundation, not a finished product.** Read [Known limitations](#known-limitations) before relying on it.
> The only submission mechanism is a clearly-labelled **sandbox test double**; real employer submission is not implemented.

## Quick start (no Docker needed)

Requires Python 3.12+ and Node 20+.

```bash
# 1. backend
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env                                   # then edit SECRET_KEY
alembic upgrade head                                      # creates the SQLite dev DB (./jobpilot.db)
uvicorn app.main:app --port 8000                          # API + OpenAPI docs at http://localhost:8000/docs

# 2. scheduler (separate terminal, same venv + env) — runs searches on each user's interval (default 24h)
python -m app.scheduler

# 3. frontend (separate terminal)
cd frontend
cp .env.example .env.local
npm install
npm run dev                                               # http://localhost:3000
```

Register at `/register`, upload a resume (Resume Manager), then **Job Search Preferences → add a source** (e.g. Greenhouse
board `gitlab`, Lever site `spotify`, Ashby board `ramp`; no credentials needed) → *Save first, then run search now*.

### Docker (written, **not yet run**)
`docker compose up --build` starts Postgres, Redis, API (runs migrations), scheduler and web. See the note at the top of
`docker-compose.yml`: it was authored on a machine without Docker and has never been executed.

## Environment variables
See [`.env.example`](.env.example) (every variable is commented). Essentials:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs session tokens **and derives the file-encryption key**. Required when `ENV=production`. |
| `DATABASE_URL` | `sqlite:///./jobpilot.db` (dev) or `postgresql+psycopg://…` |
| `STORAGE_DIR` | Encrypted document storage |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Optional Google sign-in; see [docs/integrations.md](docs/integrations.md#google-sign-in-oauth-20--openid-connect) |
| `SANDBOX_MODE` | `true` = only the test-double submitter exists; nothing is ever sent to an employer |
| `SCHEDULER_POLL_SECONDS` | How often the scheduler checks for due profiles |
| `NEXT_PUBLIC_API_URL` | Frontend → API base URL |

## Migrations
```bash
cd backend
alembic upgrade head                                  # apply
alembic revision --autogenerate -m "describe change"  # after editing app/models.py
alembic check                                         # CI: fails if models and migrations drift
```

## Job sources and AI providers
- **Sources:** Greenhouse, Lever, Ashby public job-board APIs. All three were exercised against the live APIs (see
  verification below). Add more via the connector interface: [docs/integrations.md](docs/integrations.md).
- **AI:** `LLM_PROVIDER=rules` is the only provider: deterministic, local, no data leaves your server. There is no LLM
  integration yet; the interface boundary is described in [docs/architecture.md](docs/architecture.md).

## Enabling the 24-hour scheduler
It is a separate process (`python -m app.scheduler`, or the `scheduler` service in compose). Each tick it finds active
users' active search profiles whose last run is older than their interval (Automation Settings, default 24 h), takes a
database lock per profile, runs the search with bounded exponential-backoff retries, and writes a report + notifications.
Failures after the retry budget go to the `dead_letters` table and raise a "needs attention" notification.
Optional Celery deployment (needs Redis): `celery -A app.worker worker -B` (**untested**).

## Tests
```bash
cd backend && pytest -q                      # 93 tests
cd frontend && npm run lint && npm run build # type-check + production build
```
All HTTP to job boards is mocked in the test-suite (`tests/conftest.py::FakeWeb`); live connectors were checked separately.

## Documentation
[Architecture](docs/architecture.md) · [API](docs/api.md) · [Integrations](docs/integrations.md) ·
[Security & privacy](docs/security.md) · [Operations](docs/operations.md)

## Verification record (what was actually run)
- Backend: **93 passed** (incl. 10 Google OAuth tests with a mocked Google; resume parsing/integrity, search/dedup/incremental, applications/concurrency, scheduler/locks/retries, security).
- Live connectors: Greenhouse (`gitlab`: 204 jobs, `anthropic`: 638), Lever (`spotify`: 80), Ashby (`ramp`: 158), each with reliable posted dates.
- Live end-to-end through the real API: GitLab+Spotify → 284 listings, 20 qualified, 4 applications prepared; a second run created 0 duplicates.
- Browser (production build): register → login → dashboard; jobs table; application review page; approve → submit (sandbox) → "Submitted"; reports, resumes, preferences pages render with live data.
- Alembic: `upgrade head`, `check` (no drift), `downgrade base` on SQLite.
- Frontend: `tsc --noEmit` and `next build` clean.

## Known limitations
Real, material gaps, by priority:
1. **No real application submission.** Tier 1 needs employer/ATS-issued API credentials, and none is implemented. The only
   submitter is the sandbox test double. Tier 2 (browser form filling) is not built. Everything else becomes a manual package.
2. **No LLM.** Tailoring is deterministic reordering of existing content with strict validation. It will not rewrite
   wording, and the resume parser is heuristic (unusual layouts parse imperfectly; users correct it in the UI).
3. **Not verified on PostgreSQL, Redis, Docker or Celery.** SQLite + in-process scheduler only. SQLite uses
   `BEGIN IMMEDIATE`, which serialises writers: fine for dev/small use, use Postgres for real multi-user load.
4. **Source coverage is three public ATS board APIs.** No aggregator or generic career-page connector yet; board names are entered by the user.
5. **Frontend has no automated tests**; it was checked by hand in a browser. File upload and several form-save paths were verified via API, not by clicking.
6. Google OAuth is only tested against a mock (no real Google credentials were available). Not implemented: other OAuth providers, malware scanning hook, SMTP email (console only), data-retention purge job (setting is stored),
   report delivery-hour scheduling (reports are created at run time), automated backups (see operations doc),
   Redis-backed rate limiter (in-process only), httpOnly-cookie sessions (token is in `localStorage`).
7. Dedup is conservative: same company/title/location with a different description is flagged `needs_dedup_review`, not merged,
   and there is no UI to resolve the flag yet.

## Acceptance criteria — honest status
| # | Criterion | Status |
|---|---|---|
| 1 | Register / log in | ✅ tests + browser |
| 2 | Upload resume, inspect extracted data | ✅ tests (PDF/DOCX/bad files); UI renders it; upload clicked via API only |
| 3 | LinkedIn URL + editable keywords | ✅ API tests; UI renders, not click-tested. No automatic LinkedIn import (by design) |
| 4 | Configure preferences | ✅ API tests; form renders, save path not click-tested |
| 5 | Real jobs from ≥1 source | ✅ live Greenhouse/Lever/Ashby |
| 6 | 30-day window on first search | ✅ tests + live |
| 7 | Repeat runs deduplicate | ✅ tests + live |
| 8 | Filtering per saved profile | ✅ tests |
| 9 | Original description + source links | ✅ tests + browser |
| 10 | Tailored resume w/o unsupported facts | ✅ validator tests incl. prompt-injection; reorder-only |
| 11 | Inspect and approve resume | ✅ browser |
| 12 | Supported apps submitted via authorized mechanisms | ❌ **sandbox only; no real integration** |
| 13 | Manual-application package | ✅ tests + browser |
| 14 | Confirmed apps in history w/ right version + date | ✅ tests; browser shows the submitted state |
| 15 | Retries/concurrency can't double-submit | ✅ 8-thread test on SQLite |
| 16 | 24h scheduler independent of browser | 🟡 tested with a simulated clock and a live loop smoke-test; not observed across a real 24 h |
| 17 | Daily report of new jobs + actions | ✅ tests + browser |
| 18 | Failures / unavailable sources visible | ✅ tests |
| 19 | No cross-user access | ✅ tests |
| 20 | Starts from docs on a clean machine | 🟡 the non-Docker path was followed on a fresh machine; Docker path untested |
