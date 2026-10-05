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

Full depth: see `ARCHITECTURE.md`.
