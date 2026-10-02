# Integration setup

## Job sources (implemented, no credentials needed)
| Source | Endpoint used | `board` value | Posted date |
|---|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true` | board token, e.g. `gitlab` (from `boards.greenhouse.io/<token>`) | `first_published` (reliable); `updated_at` kept only as modified |
| Lever | `api.lever.co/v0/postings/{board}?mode=json` (paged) | site name, e.g. `spotify` | `createdAt` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{board}` | job-board name, e.g. `ramp` | `publishedAt` |

Add boards in **Job Search Preferences → Job sources**. These are public, documented, read-only endpoints. The connectors
send an identifying `User-Agent` (`USER_AGENT` setting), retry 429/5xx with exponential backoff (honouring `Retry-After`),
and never bypass authentication or bot controls. The **Integrations** page shows each source's last success/error.

Verified live on 2026-10-02: Greenhouse `gitlab`/`anthropic`, Lever `spotify`, Ashby `ramp`. The Ashby response mapping
(salary, workplace type) was only checked for shape, not exhaustively. Company names for Lever/Ashby default to the board
name because those APIs don't return one.

## Adding a connector
1. Subclass `app.connectors.base.Connector`; set `name`, `display_name`, `compliance_note`, `requires_credentials`.
2. Implement `fetch(board, since=None) -> FetchResult(listings, complete, cursor)` returning `RawListing`s.
   Set `posted_at` **only** to an original publication date, and `posted_at_reliable` accordingly. Use `self.get_json` for
   retries/backoff. Raise `ConnectorUnavailable` if credentials/config are missing (it is reported to the user, not hidden).
   Set `complete=True` only if you enumerated the whole board (this enables closed-listing detection).
3. Register it in `app/connectors/__init__.py::REGISTRY`.
4. Test with `httpx.MockTransport` like `tests/conftest.py::FakeWeb`.
Check the site's terms and robots rules first; do not add connectors that need CAPTCHA/anti-bot circumvention.

## Application submission
Interface: `app.services.applications.Submitter` (`supports(job)`, `submit(package, idempotency_key) -> SubmissionResult`),
registered with `register_submitter`. Return `confirmed=True` only with proof the employer accepted it.
- **Implemented:** `SandboxSubmitter`, a test double that returns a fake `SANDBOX-…` reference and contacts nobody.
  Active only while `SANDBOX_MODE=true`.
- **Not implemented:** employer-authorized APIs (e.g. Greenhouse Job Board *application* endpoint needs the employer's
  API key; Lever/Ashby likewise). If you obtain such credentials from an employer, implement a `Submitter` for it.
  Browser form-filling (Tier 2) is not built. Until then, applications use the manual package.

## Google sign-in (OAuth 2.0 / OpenID Connect)
1. Google Cloud Console → APIs & Services → **OAuth consent screen** (configure it), then **Credentials → Create credentials → OAuth client ID → Web application**.
2. **Authorized redirect URI:** exactly `http://localhost:8000/api/auth/google/callback` (in production use your API's HTTPS URL).
3. Put the client ID/secret in `backend/.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` / `FRONTEND_URL` if not on localhost. Restart the API.
4. The "Continue with Google" button appears on the login/register pages automatically once both values are set.

Behaviour: authorization-code flow with PKCE (S256) and a state value bound to an httpOnly cookie. Only Google-**verified**
emails are accepted. A new Google user gets an account with no password. If the email matches an existing account it is
linked; if that account's email was never verified, its password is **removed** (prevents pre-registration takeover). The
session token reaches the SPA in the URL fragment. Scopes: `openid email profile`. Tested with a mocked Google (10 tests);
**not yet exercised against real Google** (needs your credentials).

## LinkedIn
No scraping or automatic import. Users save their profile URL and paste profile text (or LinkedIn's official data-export
content) at `POST /api/profiles/linkedin/import`; the app diffs it against the resume. If you obtain official LinkedIn API
access, add an importer that feeds the same `linkedin_data` structure.

## AI providers
Only `LLM_PROVIDER=rules` exists (local, deterministic). See `docs/architecture.md` for where a model would plug in and the
validation gate it must pass.

## Email
`reports.send_email` logs only. Replace with SMTP/provider code and set `email_notifications` per user.
