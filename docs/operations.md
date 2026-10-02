# Operations

- **Health:** `GET /health` (also checks DB). Compose healthchecks use it.
- **Logs:** structured-ish text to stdout (`jobpilot.*` loggers). Request bodies/headers are never logged.
- **Processes:** API (`uvicorn`), scheduler (`python -m app.scheduler`). Run **one** scheduler per deployment unless you also
  rely on the DB locks (safe, but redundant). Optional Celery worker+beat in `app/worker.py` (untested).
- **Retries/dead letters:** failed scheduled runs retry with backoff, then land in `dead_letters` and notify the user.
  Inspect: `SELECT * FROM dead_letters ORDER BY id DESC;`
- **Stuck work:** stale `running` search runs are failed automatically after `LOCK_TTL_SECONDS`; applications stuck
  `application_in_progress` for 30 min become `submission_confirmation_pending` (needs human verification, never auto-retried).
- **Backups (not automated):** PostgreSQL: `pg_dump -Fc jobpilot > backup.dump` daily + test restores; back up `STORAGE_DIR`
  (files are encrypted; you also need `SECRET_KEY` to read them). SQLite dev DB: copy `jobpilot.db` while the app is stopped.
- **Upgrades:** `alembic upgrade head` before starting the new version. CI runs `alembic check` to catch missing migrations.
- **Sandbox safety:** keep `SANDBOX_MODE=true` unless a real, authorized `Submitter` is registered. With it `false` and no real
  submitter, every application is a manual package.
- **SQLite caveat:** writers are serialised (`BEGIN IMMEDIATE`); leaked open sessions block everyone. Use PostgreSQL beyond a single user.
