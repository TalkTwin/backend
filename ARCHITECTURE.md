# TalkTwin Backend — Architecture & System Guide

> Generated from the live codebase + database (Oct 2026). If code and this doc
> disagree, **code wins** — update this file with it.

Stack: **FastAPI + PostgreSQL (psycopg2) + SQLAlchemy 2.0 + Alembic + JWT.**
56 operations across 8 docs groups. No web UI in this repo (API only).

---

## 1. Run it

```powershell
cd backend
.\.venv\Scripts\uvicorn.exe main:app --reload --port 8001
# docs: http://localhost:8001/docs   health: GET /health   metrics: GET /metrics
```

`.env` needs `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`
(plus `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES=60`).
First admin is seeded **outside the API** (no endpoint can grant admin):

```powershell
$env:ADMIN_EMAIL="you@x.com"; $env:ADMIN_PASSWORD="StrongPass123"
.\.venv\Scripts\python.exe scripts/create_admin.py   # creates OR promotes
```

Tests: `.\.venv\Scripts\python.exe -m pytest tests/ -q` (15 tests, real dev DB,
self-cleaning; run from `backend/` so imports resolve).

---

## 2. Request lifecycle (what happens per call)

```
Client → MetricsMiddleware → route → dependency (auth) → validation →
       → DB transaction (+ audit row) → BackgroundTasks → response
```

- `core/metrics.py:MetricsMiddleware` counts every request
  (`http_requests_total{method,route,status}`) with **route-template labels**
  (`/v1/voices/{voice_id}`, never raw ids). `/metrics` itself is excluded.
- Auth resolves in `api/deps.py`: `get_current_user` (JWT only),
  `get_api_context` (X-API-Key **or** JWT), `require_admin` (JWT + `role=admin`,
  re-read from DB every request so demote/disable bites instantly).
- Writes commit business row + audit row in **one transaction**.
- Slow work (embeddings, latents, job results) runs in `BackgroundTasks` via
  one swappable seam each (`services/job_worker.py:enqueue_job`, etc.).
- App `lifespan` (`main.py`) reaps stranded `running` jobs on boot.

---

## 3. Auth model (the whole access-control story)

| Credential | Header | Used on | Identity |
|---|---|---|---|
| JWT (register/login) | `Authorization: Bearer …` | everything (service + operator) | human user |
| API key (opaque `tt_…`) | `X-API-Key: …` | service routes only | machine + owner user |

- Passwords: bcrypt. API keys: `sha256` hex stored, **raw shown once** at
  create/rotate, never stored or returned again (`core/security.py`).
- Roles: `user` (default) / `admin`. Registration and self-update can never
  set a role (`extra="forbid"` + no role field); only the seed script and
  `PATCH /v1/admin/users/{id}` grant it.
- Admin router carries **one** `require_admin` dependency: 401 bad/missing
  token, 403 valid token but `role != admin`. API keys are rejected there
  (machine creds don't administrate).
- Account routes scope everything to the caller; other users' rows return
  **404** (no existence oracle).
- Safety rails: no self-disable/demote, last active admin protected (409),
  disable revokes all keys + cancels live jobs (voices/avatars stay — content
  deletion belongs to consent withdrawal), disabled users' keys die on the
  next request (active-flag checked per call).
- Normal users' own keys are capped (`NORMAL_KEY_RATE_MAX=60`,
  `NORMAL_KEY_CONCURRENT_MAX=2` in `core/config.py`); admins bypass.
  Key allow-lists may only name voices/avatars the user owns or
  `is_library=true`, else 403.

---

## 4. File structure (every file earns its place)

```
backend/
├── main.py                  # app, lifespan reaper, openapi_tags order,
│                            # /health (DB ping), /metrics (Prometheus)
├── core/
│   ├── config.py            # .env → DB/JWT/storage/caps settings
│   ├── db.py                # engine + SessionLocal + Base
│   ├── security.py          # bcrypt, JWT, API-key mint/hash (sha256)
│   ├── storage.py           # DB-key ↔ disk-path builders + save/delete
│   │                        # (voices/avatars/jobs; MinIO swaps this file)
│   ├── languages.py         # THE 13-language list (single source of truth)
│   └── metrics.py           # Prometheus registry + middleware
├── api/
│   ├── deps.py              # get_db, get_current_user, get_api_context,
│   │                        # require_admin, ApiContext, rate limiter
│   └── v1/
│       ├── router.py        # include order = docs order
│       ├── auth.py          # tag user: register/login/logout/change-pw/me
│       ├── account.py       # tag account: users/me*, my keys, usage/me
│       ├── admin.py         # tag admin: users/keys/audit/jobs/content/stats
│       ├── consents.py      # checkbox agreements + withdraw cascade
│       ├── voices.py        # voice CRUD + embedding stub
│       ├── avatars.py       # avatar CRUD + latents stub
│       ├── jobs.py          # tts/generate/history/cancel/download
│       └── infra.py         # GET /v1/languages
├── models/                  # SQLAlchemy tables (§6). user/voice/consent/
│                            # avatar/job/api_key/audit_log
├── schemas/                 # Pydantic contracts (request/response per route;
│                            # Self vs Admin models block mass assignment)
├── services/
│   ├── job_worker.py        # fake async engine behind enqueue_job()
│   ├── audit.py             # log_action() — the single audit seam
│   └── keys.py              # shared key-issuance core (no drift)
├── migrations/versions/     # 10 Alembic revisions (§7)
├── scripts/
│   ├── create_admin.py      # env-based admin seed/promote
│   └── create_key.py        # first API key bootstrap (prints raw once)
├── storage/                 # local media (git-ignored): voices/{id}/,
│                            # avatars/{id}/, jobs/{id}/
└── tests/test_access_control.py  # 15 pytest access-control tests
```

---

## 5. API map (by docs group)

- **user** — `POST /v1/auth/register|login|logout|change-password`,
  `GET|PATCH /v1/me`. Open except change-password/me (JWT).
- **account** (own data only) — `GET|PATCH /v1/users/me`,
  `POST /v1/users/me/password` (JWT-only), `POST|GET /v1/api-keys`,
  `DELETE /v1/api-keys/{key_id}`, `GET /v1/usage/me`.
- **admin** (`require_admin` on whole router) — users
  (`GET|POST /v1/admin/users`, `GET|PATCH /{id}`, `POST /{id}/disable|enable`
  with required reason); api-keys (`GET|POST`, `PATCH|DELETE /{id}`,
  `POST /{id}/rotate` with reason, raw once); audit
  (`GET /v1/admin/audit-logs` + filters, `GET /{log_id}`); jobs
  (`GET /` + `/{id}`, `POST /{id}/cancel`); content
  (`GET /v1/admin/voices|avatars`, `PATCH /{id}` library toggle only);
  `GET /v1/admin/stats/overview`.
- **consents** — `POST /v1/consents` (plain JSON, checkbox agreement),
  `GET /` + `/{id}`, `POST /{id}/withdraw` (flips status, **hard-deletes**
  linked voices/avatars + files, idempotent).
- **voices** — `POST /v1/voices` (multipart clip + `consent_id` → 201
  `processing`), `GET /` (language/library/status filters),
  `GET|PATCH|DELETE /{id}` (hard delete + files).
- **avatars** — same shape with face image (`jpg/png/gif/webp`, 10 MB).
- **jobs** — `POST /v1/tts` (text+voice+language), `POST /v1/generate`
  (text+avatar, voice optional), `GET /v1/jobs` (own only),
  `GET /{id}` (poll; `result_url` on completion),
  `GET /{id}/download` (409 until completed), `POST /{id}/cancel`
  (409 unless queued/running). `Idempotency-Key` header replays the same job
  (200) instead of duplicating. Quota: per-key cap or per-user
  (override ?? 2), else 429.
- **infra** — `GET /v1/languages` (open), `GET /health`, `GET /metrics`.

Legacy `/v1/me` + `/v1/auth/*` predate the account router and are kept
working; the account paths are canonical for new clients.

---

## 6. Database (7 tables; FKs do the integrity work)

Conventions: PKs are prefixed strings (`usr_|cst_|voi_|avt_|job_|key_|log_` +
28 hex = 32 chars); `created_at` everywhere; soft-disable beats hard-delete
except consent-governed content.

- **users** — `id, name(120), email(255, unique), password_hash?, role(user|
  admin, default user), rate_limit_per_min?, max_concurrent_jobs?`
  (admin-set quota overrides), `is_active, created_at`.
- **api_keys** — `id, user_id→users CASCADE, name(80)` + unique
  `(user_id,name)`, `key_prefix(16)`, `key_hash(64, unique)`,
  `rate_limit_per_min=60, max_concurrent_jobs=2`,
  `allowed_voice/avatar_ids JSON?` (`null` = all), `is_active`,
  `expires_at?, created_at, last_used_at?` (throttled to 1 write / 5 min).
- **consents** — `id, subject_name(120)` (the **voice owner**, not the
  uploader), `scope(voice|avatar|both)`, `permitted_uses JSON`,
  `status(active|withdrawn)`, `signed_at, valid_until?, withdrawn_at?,
  created_at`. No file upload: digital checkbox agreement.
- **voices** — `id, name(80), language(4, free-form until list enforced),
  consent_id(32, plain string — API-enforced, no DB FK),
  owner_user_id?→users SET NULL (null = legacy: usable only if library),
  reference_clip_key(255), embedding_key?, is_library,
  status(processing|ready|failed), created_at`.
- **avatars** — same shape: `image_key`, `latents_key?`, no language.
- **jobs** — `id, user_id→users CASCADE, api_key_id?→api_keys SET NULL,
  type(tts|generate|speak), status(queued|running|completed|failed|cancelled),
  text?, language?, voice_id?→voices SET NULL, avatar_id?→avatars SET NULL,
  idempotency_key(64)?` + partial unique `(user_id,key)` where not null,
  `result_key?, duration_sec?, ai_generated=true, moderation?,
  error?, created_at/started_at?/finished_at?`. SET NULL keeps history when
  voices/avatars/keys vanish.
- **audit_logs** (append-only, no PATCH/DELETE) — `id,
  user_id→users CASCADE` (= **actor**), `api_key_id?→api_keys SET NULL`,
  `action(64)` (`key.create|revoke|rotate, user.create|update|disable|enable,
  consent.withdraw, voice|avatar.delete|update, job.cancel`),
  `resource_type?/resource_id?` (= target), `outcome(success|refused|error)`,
  `before?/after? JSON` (safe snapshots, never secrets/hashes),
  `reason?` (required for disable/enable/rotate), `created_at`.
  Same-transaction writes: unlogged action = failed action.

Relationship sketch:

```
users ──┬──< api_keys ──< audit_logs
        │        │
        │        └──< jobs (SET NULL)
        └──< jobs (CASCADE)   voices/avatars ──< jobs (SET NULL)

consents ──< voices ──┐ (consent_id is logical, enforced in API)
         └──< avatars ─┘ withdraw ⇒ hard-delete linked rows + files
```

---

## 7. Migrations (10, linear, all applied)

`c9815 create users → 917995 password_hash → 2d237df voices → 18c38d consents
→ be5a85 drop consent document_key (file uploads removed) → ba6330 avatars
→ 116802 jobs → ec88e1 api_keys (+jobs.api_key_id FK) → 7ee841 audit_logs
→ 85d29d roles/quotas/ownership/audit-detail (head).`

---

## 8. Known stubs & limits (honest list)

- `embedding.npy` / `latents.npy` / `result.mp3|mp4` are **placeholder bytes**
  (`_embedding_stub`, `_latents_stub`, `job_worker._run`); real models +
  Celery + broker pending (`workers/` empty).
- Local disk storage; S3/MinIO presigned URLs pending (`result_url` is a
  local route today).
- No moderation service (`moderation` stays null; `speak`/`stream` unbuilt).
- In-memory per-key rate limiter (per-process; Redis TODO).
- `language` codes free-form (13-list in `core/languages.py` awaits confirmation).
- `POST /v1/auth/register` is **open** — gate before exposing publicly.
- No `role` separation was the old design; roles now exist (`user/admin`).

## 9. Roadmap

`speak` + moderation gate → `/v1/stream` (stretch) → real models/Celery/S3 →
DB-level `consent_id` FKs → language enforcement → retention/archival for
`audit_logs`/`jobs`.
