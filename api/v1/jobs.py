# jobs apis: tts, generate, status, history, cancel, download (doc 6.1-6.5)
# auth: JWT or API key. Key calls get per-key quotas + allow-lists; JWT calls get user quota.
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Path, Query, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import ApiContext, get_api_context, get_db
from core.config import STORAGE_DIR
from models.avatar import Avatar
from models.consent import Consent
from models.job import Job
from models.job import _new_job_id
from models.voice import Voice
from schemas import JobCreateGenerate, JobCreateTTS, JobResponse
from services.job_worker import enqueue_job

router = APIRouter(tags=["jobs"])

# JWT-call quota: admin-set user override, else default 2
# (key calls use their own max_concurrent_jobs)
MAX_ACTIVE_PER_USER = 2


def to_response(job: Job) -> JobResponse:
    url = f"/v1/jobs/{job.id}/download" if job.status == "completed" and job.result_key else None
    return JobResponse(
        id=job.id, type=job.type, status=job.status, text=job.text, language=job.language,
        voice_id=job.voice_id, avatar_id=job.avatar_id, result_url=url,
        duration_sec=job.duration_sec, ai_generated=job.ai_generated, moderation=job.moderation,
        error=job.error, created_at=job.created_at, started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _dump(resp: JobResponse) -> dict:
    return resp.model_dump(mode="json")


def _ready_voice(db: Session, voice_id: str) -> Voice:
    v = db.get(Voice, voice_id.strip())
    if not v:
        raise HTTPException(status_code=404, detail="Voice not found")
    if v.status != "ready":
        raise HTTPException(status_code=422, detail=f"Voice is {v.status}, not ready")
    c = db.get(Consent, v.consent_id)
    if not c or c.status != "active":
        raise HTTPException(status_code=422, detail="Voice consent is not active")
    return v


def _ready_avatar(db: Session, avatar_id: str) -> Avatar:
    a = db.get(Avatar, avatar_id.strip())
    if not a:
        raise HTTPException(status_code=404, detail="Avatar not found")
    if a.status != "ready":
        raise HTTPException(status_code=422, detail=f"Avatar is {a.status}, not ready")
    c = db.get(Consent, a.consent_id)
    if not c or c.status != "active":
        raise HTTPException(status_code=422, detail="Avatar consent is not active")
    return a


def _check_quota(db: Session, ctx: ApiContext) -> None:
    if ctx.api_key is not None:
        active = db.query(Job).filter(
            Job.api_key_id == ctx.api_key.id, Job.status.in_(["queued", "running"])).count()
        limit = ctx.api_key.max_concurrent_jobs
    else:
        active = db.query(Job).filter(
            Job.user_id == ctx.user.id, Job.status.in_(["queued", "running"])).count()
        limit = ctx.user.max_concurrent_jobs or MAX_ACTIVE_PER_USER
    if active >= limit:
        raise HTTPException(status_code=429, detail=f"Too many active jobs (max {limit}). Cancel or wait.")


def _check_allowed(ctx: ApiContext, voice_id: str | None, avatar_id: str | None) -> None:
    # per-key allow-lists (Sec 10.4): null = all; JWT calls unrestricted
    if ctx.api_key is None:
        return
    allowed_v = ctx.api_key.allowed_voice_ids
    if voice_id and allowed_v is not None and voice_id not in allowed_v:
        raise HTTPException(status_code=422, detail="Voice not allowed for this key")
    allowed_a = ctx.api_key.allowed_avatar_ids
    if avatar_id and allowed_a is not None and avatar_id not in allowed_a:
        raise HTTPException(status_code=422, detail="Avatar not allowed for this key")


def _find_replay(db: Session, user_id: str, key: str | None) -> Job | None:
    if not key:
        return None
    return db.query(Job).filter(Job.user_id == user_id, Job.idempotency_key == key).first()


def _insert(db: Session, job: Job) -> Job | None:
    # returns None on idempotency race (caller re-fetches the winner)
    db.add(job)
    try:
        db.commit()
        db.refresh(job)
        return job
    except IntegrityError:
        db.rollback()
        return None


# 6.1 text -> audio (async; 202 + job)
@router.post("/tts", status_code=status.HTTP_202_ACCEPTED,
             summary="Text to speech", description="Queue TTS. Poll GET /v1/jobs/{id} until completed, then download.")
def create_tts(
    background: BackgroundTasks,
    payload: JobCreateTTS = Body(..., description="Text, ready voice_id, language"),
    idempotency_key: str | None = Header(default=None, max_length=64, alias="Idempotency-Key",
                                         description="Optional retry key (same key = same job, no duplicate)"),
    db: Session = Depends(get_db),
    ctx: ApiContext = Depends(get_api_context),
):
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    lang = payload.language.strip().lower()
    voice = _ready_voice(db, payload.voice_id)
    _check_allowed(ctx, voice.id, None)
    if (old := _find_replay(db, ctx.user.id, idempotency_key)):
        return JSONResponse(status_code=200, content=_dump(to_response(old)))
    _check_quota(db, ctx)

    job = Job(id=_new_job_id(), user_id=ctx.user.id,
              api_key_id=ctx.api_key.id if ctx.api_key else None,
              type="tts", status="queued",
              text=text, language=lang, voice_id=voice.id, avatar_id=None,
              idempotency_key=idempotency_key, moderation=None, ai_generated=True)
    if not _insert(db, job):
        winner = _find_replay(db, ctx.user.id, idempotency_key)
        return JSONResponse(status_code=200, content=_dump(to_response(winner)))
    background.add_task(enqueue_job, job.id)
    return to_response(job)


# 6.2 text + face -> talking-head video (async; 202 + job)
@router.post("/generate", status_code=status.HTTP_202_ACCEPTED,
             summary="Generate video", description="Queue talking-head video. voice_id optional (silent avatar without it).")
def create_generate(
    background: BackgroundTasks,
    payload: JobCreateGenerate = Body(..., description="Text, ready avatar_id, optional voice_id/language"),
    idempotency_key: str | None = Header(default=None, max_length=64, alias="Idempotency-Key",
                                         description="Optional retry key (same key = same job, no duplicate)"),
    db: Session = Depends(get_db),
    ctx: ApiContext = Depends(get_api_context),
):
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    avatar = _ready_avatar(db, payload.avatar_id)
    voice = _ready_voice(db, payload.voice_id) if payload.voice_id else None
    lang = payload.language.strip().lower() if payload.language else None
    _check_allowed(ctx, voice.id if voice else None, avatar.id)
    if (old := _find_replay(db, ctx.user.id, idempotency_key)):
        return JSONResponse(status_code=200, content=_dump(to_response(old)))
    _check_quota(db, ctx)

    job = Job(id=_new_job_id(), user_id=ctx.user.id,
              api_key_id=ctx.api_key.id if ctx.api_key else None,
              type="generate", status="queued",
              text=text, language=lang, voice_id=voice.id if voice else None, avatar_id=avatar.id,
              idempotency_key=idempotency_key, moderation=None, ai_generated=True)
    if not _insert(db, job):
        winner = _find_replay(db, ctx.user.id, idempotency_key)
        return JSONResponse(status_code=200, content=_dump(to_response(winner)))
    background.add_task(enqueue_job, job.id)
    return to_response(job)


# 6.4 job history for the caller, newest first
@router.get("/jobs", response_model=list[JobResponse],
            summary="Job history", description="Your jobs, newest first. Others' jobs never appear.")
def list_jobs(
    page: int = Query(default=1, ge=1, description="Page number (from 1)"),
    size: int = Query(default=20, ge=1, le=100, description="Items per page (1-100)"),
    job_type: str | None = Query(default=None, alias="type", description="Filter: tts or generate", examples=["tts"]),
    job_status: str | None = Query(default=None, alias="status",
                                   description="Filter: queued, running, completed, failed or cancelled", examples=["completed"]),
    db: Session = Depends(get_db),
    ctx: ApiContext = Depends(get_api_context),
):
    q = db.query(Job).filter(Job.user_id == ctx.user.id)
    if job_type is not None:
        if job_type not in ("tts", "generate", "speak"):
            raise HTTPException(status_code=422, detail="Invalid type filter")
        q = q.filter(Job.type == job_type)
    if job_status is not None:
        if job_status not in ("queued", "running", "completed", "failed", "cancelled"):
            raise HTTPException(status_code=422, detail="Invalid status filter")
        q = q.filter(Job.status == job_status)
    return [to_response(j) for j in q.order_by(Job.created_at.desc(), Job.id.desc())
            .offset((page - 1) * size).limit(size).all()]


# 6.3 job status / result URL (what a client polls)
@router.get("/jobs/{job_id}", response_model=JobResponse,
            summary="Job status", description="Poll until completed, then use result_url to download.")
def get_job(
    job_id: str = Path(description="Job id (job_...)", examples=["job_abc123"]),
    db: Session = Depends(get_db),
    ctx: ApiContext = Depends(get_api_context),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == ctx.user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return to_response(job)


# result file (local disk now; presigned S3 URL later — contract via result_url stays)
@router.get("/jobs/{job_id}/download",
            summary="Download result", description="Audio/video file. 409 until the job completes.")
def download_job(
    job_id: str = Path(description="Job id (job_...)", examples=["job_abc123"]),
    db: Session = Depends(get_db),
    ctx: ApiContext = Depends(get_api_context),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == ctx.user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.result_key:
        raise HTTPException(status_code=409, detail=f"Result not ready (status={job.status})")
    path = STORAGE_DIR / job.result_key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Result file missing")
    media = "audio/mpeg" if job.type in ("tts", "speak") else "video/mp4"
    return FileResponse(path, media_type=media, filename=f"{job.id}{path.suffix}")


# 6.5 cancel a queued/running job
@router.post("/jobs/{job_id}/cancel", response_model=JobResponse,
             summary="Cancel job", description="Only queued/running jobs. Finished ones give 409.")
def cancel_job(
    job_id: str = Path(description="Job id (job_...)", examples=["job_abc123"]),
    db: Session = Depends(get_db),
    ctx: ApiContext = Depends(get_api_context),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == ctx.user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {job.status} job")
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return to_response(job)
