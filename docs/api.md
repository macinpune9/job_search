# API

Interactive OpenAPI docs: `http://localhost:8000/docs` (schema at `/openapi.json`).
Auth: `Authorization: Bearer <token>` from `POST /api/auth/login`. All routes except `/api/auth/*`, `/health` and
`/api/files/{token}` (short-lived signed link) require it. Every record is scoped to the authenticated user; accessing
another user's id returns **404**.

**Errors** always use `{"error": {"code": "...", "message": "...", "details": ...}}` (401/403/404/409/413/415/422/429/500).
**Rate limits:** auth POSTs 10/min/IP, everything else 300/min/IP (in-process; configurable). 429 includes `Retry-After`.
**Long-running work:** `POST /api/search-profiles/{id}/run` → `202 {task_id, poll}`; poll `GET /api/search-runs/{task_id}`
until `status != running` (completion also produces a notification + report).

| Area | Endpoints |
|---|---|
| Auth | `GET /api/auth/providers` `GET /api/auth/google/login` `GET /api/auth/google/callback` (browser redirects, not JSON) · `POST /api/auth/register` `login` `logout` `verify-email` `request-password-reset` `reset-password` |
| User | `GET/PATCH/DELETE /api/users/me` · `GET /api/users/me/export` · `GET/PATCH /api/profiles/me` · `POST /api/profiles/linkedin/import` |
| Resumes | `POST/GET /api/resumes` · `GET/PATCH/DELETE /api/resumes/{id}` · `…/download-link` · `…/versions` · `GET /api/resume-versions/{id}` · `…/download-link?fmt=docx\|pdf` · `POST …/edit` |
| Career snapshot | `GET /api/resumes/{id}/insights?ai=&refresh=` · `POST /api/insights/apply` (roles, skills, tools -> search profile) · `POST /api/resumes/{id}/reparse?ai=` |
| Search | `GET/POST /api/search-profiles` · `GET/PATCH/DELETE …/{id}` · `POST …/{id}/run` · `POST …/{id}/keyword-preview` · `GET /api/keywords/suggest?resume_id=` · `GET /api/search-runs[/{id}]` · `GET /api/sources` |
| Jobs | `GET /api/jobs` (q, qualified, min_score, status, source, remote, sort, page) · `GET /api/jobs/{id}` · `GET …/match` · `POST …/prepare-application` |
| Applications | `GET /api/applications` · `GET …/export.csv` · `GET/PATCH …/{id}` · `POST …/{id}/approve` · `POST …/{id}/submit` |
| Other | `GET /api/dashboard` · `GET /api/reports/daily` · `GET /api/notifications` · `POST /api/notifications/{id}/read` · `GET /api/integrations` · `GET/PATCH /api/automation-settings` · `GET /health` |

Notes: `PATCH /api/applications/{id}` accepts `status` (only whitelisted user transitions), `notes`, `follow_up_date`,
`resume_version_id` (before submission only). Marking `submitted` is recorded as a *user attestation*.
`PATCH /api/automation-settings` with `mode=auto_submit_authorized` requires `consent_to_auto_submit: true`.
