# TalkTwin Backend

Async text-to-speech + talking-head video API. FastAPI + PostgreSQL + SQLAlchemy 2.0 + Alembic + JWT.

## Quickstart

```powershell
cd backend
.\.venv\Scripts\python.exe -m venv .venv; .\.venv\Scripts\pip.exe install -r requirements.txt
# .env: DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD, SECRET_KEY
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe main:app --reload --port 8001
# docs: http://localhost:8001/docs
```

First admin (no endpoint can grant admin — seed it):

```powershell
$env:ADMIN_EMAIL="you@x.com"; $env:ADMIN_PASSWORD="StrongPass123"
.\.venv\Scripts\python.exe scripts/create_admin.py
```

Tests: `.\.venv\Scripts\python.exe -m pytest tests/ -q`

## Auth in 30 seconds

| Credential | Header | Where |
|---|---|---|
| JWT (`POST /v1/auth/login`) | `Authorization: Bearer …` | everywhere |
| API key (raw shown once) | `X-API-Key: …` | service routes only |

Roles: `user` (default) / `admin`. Docs groups: `user` → `account` (own data)
→ `admin` (role-gated) → `consents` → `voices` → `avatars` → `jobs` → `infra`.

Typical flow: register → login → Authorize in `/docs` →
`POST /v1/consents` (get `cst_…`) → `POST /v1/voices` or `/v1/avatars`
(upload file, poll `GET /{id}` till `ready`) →
`POST /v1/tts` or `/v1/generate` (202, poll `GET /v1/jobs/{id}`,
download `result_url`).

## Layout

- `main.py` — app, startup reaper, `/health`, `/metrics`
- `core/` — config, db, security (bcrypt/JWT/sha256 keys), storage
  (DB-key ↔ disk-path; MinIO swaps this file), languages, metrics
- `api/deps.py` — `get_current_user`, `get_api_context`, `require_admin`
- `api/v1/` — `auth, account, admin, consents, voices, avatars, jobs, infra`
- `models/` — `users, api_keys, consents, voices, avatars, jobs, audit_logs`
- `schemas/` — per-route contracts (Self vs Admin models block escalation)
- `services/` — `job_worker` (async seam), `audit` (single log seam),
  `keys` (issuance core)
- `migrations/versions/` — 10 linear Alembic revisions
- `scripts/` — `create_admin.py` (env seed/promote), `create_key.py`
  (first API key, raw printed once)
- `storage/` — local media, git-ignored

## Data model (FKs enforce it)

`users ──┬──< api_keys ──< audit_logs` (+ `api_keys ──< jobs`,
`users ──< jobs`, all `SET NULL` except user cascade).
`consents ──< voices|avatars` (logical `consent_id`; withdraw hard-deletes
linked rows + files). `voices|avatars ──< jobs` (`SET NULL` keeps history).
`audit_logs` is append-only: actor + target + before/after + reason.

## Rules that matter

- Consent must exist, be `active`, and cover the scope — else 422.
- Key allow-lists name only owned-or-library voices/avatars (403 otherwise);
  normal users' keys are capped (`NORMAL_KEY_RATE_MAX=60`,
  `NORMAL_KEY_CONCURRENT_MAX=2`).
- Quota: per-key cap or per-user override, else 429; `Idempotency-Key`
  replays the same job instead of duplicating.
- Admin rails: no self-disable/demote, last admin protected, disable revokes
  keys + cancels jobs, every admin write audited (reason required for
  disable/enable/rotate). Disabled users' keys die on next request.
- `embedding.npy` / `latents.npy` / `result.mp3|mp4` are **stubs**;
  real models + Celery + S3 are the next infra jump.

Full depth: see `ARCHITECTURE.md` (design notes, not pushed).
