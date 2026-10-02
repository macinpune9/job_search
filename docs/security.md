# Security & privacy

## Implemented (and tested unless noted)
- Passwords: argon2id; strong-password rule; generic login errors; password reset/verification tokens are random, hashed at rest, single-use, expiring. Reset requests don't reveal whether an account exists.
- Google sign-in: PKCE + cookie-bound state, verified-email required, unverified local passwords wiped on linking (tested with a mock).
- Sessions: signed JWT (default 8 h) with server-side revocation on logout. Download-link tokens use a different `purpose` and cannot be used as sessions.
- Isolation: every query is scoped to the user; other users' ids return 404 (tested across resumes, versions, profiles, jobs, applications, runs).
- Files: type + magic-byte validation, size cap, zip-bomb guard, encrypted/corrupt/empty detection, path-safe storage keys, **Fernet encryption at rest**, downloads only via 5-minute signed links, `Cache-Control: no-store`.
- Rate limiting (in-process), security headers, CSV formula-injection neutralisation.
- Logs/audit: no passwords, tokens, resume text or contact data (tested). Audit events carry ids/statuses only.
- Untrusted job text: HTML stripped (scripts/styles removed), stored verbatim as data, never executed; generator/validator cannot be steered by it (tested).
- Account deletion (cascades rows and removes stored files) and JSON data export.

## Not implemented / your responsibility
- TLS: terminate HTTPS at your reverse proxy; the app does not.
- Key management: `SECRET_KEY` also derives the file-encryption key; rotating it makes existing files unreadable (add re-encryption before rotating). Use a secret manager in production.
- Malware scanning: no scanner hook yet. Recommended: run ClamAV (e.g. `clamd`) and scan in `routers/resumes.py::upload_resume` before storing.
- Tokens are kept in browser `localStorage` (XSS-exposed). For hardening serve API and web from one origin and move to an httpOnly, SameSite cookie + CSRF token.
- Rate limiter is per-process: front with a gateway/Redis limiter when running several API replicas.
- Retention: the `data_retention_days` setting is stored but **no purge job exists yet**.
- Third-party AI (Anthropic): off by default; per-user opt-in with a stored consent time and an in-app disclosure. Name/email/phone/links are never sent. The API key lives only in server config. Job text is delimited as untrusted data, the model has no tools, and outputs are schema-validated, clamped and fact-checked (tested with a stub client and a scripted attacker model; **not** tested against the live model).
