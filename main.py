from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from sqlalchemy import text

from api.v1.router import api_router
from core.db import engine
from core.metrics import MetricsMiddleware, exposition


@asynccontextmanager
async def lifespan(app: FastAPI):
    # a restart strands in-flight BackgroundTasks — fail them honestly
    from services.job_worker import reap_stale_running
    reap_stale_running()
    yield


app = FastAPI(
    title="TalkTwin API",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "user", "description": "1. Signup, login, own profile (start here)"},
        {"name": "account", "description": "2. My profile, my keys, my usage (any active user, own data only)"},
        {"name": "admin", "description": "3. Platform administration (admin role only)"},
        {"name": "consents", "description": "3. Digital voice agreements (needed before voices)"},
        {"name": "voices", "description": "4. Clone voices from audio clips (needs a consent_id)"},
        {"name": "avatars", "description": "5. Register avatars from face photos (needs a consent_id)"},
        {"name": "jobs", "description": "6. TTS + video jobs: queue, poll status, download result"},
        {"name": "infra", "description": "7. Languages list (see /health and /metrics at root)"},
    ],
)
app.include_router(api_router)
app.add_middleware(MetricsMiddleware)


# 9.1 liveness/readiness (DOC Sec 15) — checks API + DB connection
@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


# 9.2 prometheus metrics (DOC Sec 15) — open, scraped without auth
@app.get("/metrics", include_in_schema=False)
def metrics():
    body, content_type = exposition()
    return Response(content=body, media_type=content_type)





