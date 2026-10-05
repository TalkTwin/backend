# voices apis: register, list, get, update, delete (doc 4.1-4.5)
# auth: JWT for now (api_keys skipped) — switch to key context later
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Path, Query, UploadFile, status
from sqlalchemy.orm import Session

from api.deps import ApiContext, get_api_context, get_db
from core.config import ALLOWED_AUDIO_EXTS, MAX_AUDIO_MB
from core.db import SessionLocal
from core.storage import delete_key, save_bytes, voice_clip_path, voice_embedding_path
from models.consent import Consent
from models.voice import _new_voice_id
from models.voice import Voice
from schemas import VoiceResponse, VoiceUpdate
from services.audit import log_action

router = APIRouter(prefix="/voices", tags=["voices"])

MAX_BYTES = MAX_AUDIO_MB * 1024 * 1024


def _embedding_stub(voice_id: str) -> None:
    # Runs in BackgroundTasks with its own session (request session is closed).
    # TODO: replace with Celery workers/tasks.py real speaker-embedding (Sec 12.3).
    db = SessionLocal()
    try:
        voice = db.get(Voice, voice_id)
        if not voice or voice.status != "processing":
            return
        dest, rel = voice_embedding_path(voice_id)
        try:
            save_bytes(dest, b"stub-embedding")
            voice.embedding_key = rel
            voice.status = "ready"
            db.commit()
        except OSError:
            db.rollback()
            voice.status = "failed"
            db.commit()
    finally:
        db.close()


# 4.1 register/clone a voice from a reference clip -> 201 + voice (processing)
@router.post("", response_model=VoiceResponse, status_code=status.HTTP_201_CREATED,
             summary="Clone voice", description="Step 2: upload a clip + consent_id. Returns processing, becomes ready in seconds.")
def create_voice(
    background: BackgroundTasks,
    name: str = Form(min_length=1, max_length=80, description="Display name for this voice", examples=["Raju Hindi voice"]),
    language: str = Form(min_length=2, max_length=4, description="2-4 letter language code (e.g. en, hi, mr)", examples=["hi"]),
    consent_id: str = Form(min_length=1, max_length=32, description="Active consent id from POST /v1/consents (cst_...)", examples=["cst_abc123"]),
    is_library: bool = Form(default=False, description="Mark as shared library voice"),
    reference_audio: UploadFile = File(..., description="Short voice clip, up to 30s (wav/mp3/m4a/ogg/flac/webm, max 10MB)"),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=422, detail="Name must not be empty")
    lang = language.strip().lower()
    if not 2 <= len(lang) <= 4:
        raise HTTPException(status_code=422, detail="Language must be 2-4 chars (e.g. en, hi)")
    consent = consent_id.strip()
    if not consent:
        raise HTTPException(status_code=422, detail="consent_id must not be empty")
    c = db.get(Consent, consent)
    if not c:
        raise HTTPException(status_code=404, detail="Consent not found")
    if c.status != "active":
        raise HTTPException(status_code=422, detail="Consent is withdrawn")
    if c.scope not in ("voice", "both"):
        raise HTTPException(status_code=422, detail="Consent scope does not cover voice")

    filename = reference_audio.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported audio type '{ext or '(none)'}'. Allowed: {sorted(ALLOWED_AUDIO_EXTS)}",
        )
    data = reference_audio.file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty audio file")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Audio too large (max {MAX_AUDIO_MB}MB)")

    voice_id = _new_voice_id()
    dest, rel = voice_clip_path(voice_id, ext)
    try:
        save_bytes(dest, data)
    except OSError:
        raise HTTPException(status_code=500, detail="Failed to store audio")

    voice = Voice(
        id=voice_id,
        name=clean_name,
        language=lang,
        consent_id=consent,
        owner_user_id=_ctx.user.id,
        reference_clip_key=rel,
        embedding_key=None,
        is_library=is_library,
        status="processing",
    )
    db.add(voice)
    try:
        db.commit()
        db.refresh(voice)
    except Exception:
        db.rollback()
        delete_key(rel)
        raise HTTPException(status_code=500, detail="Failed to create voice")

    background.add_task(_embedding_stub, voice_id)
    return voice


# 4.2 list voices (paginated + filters)
@router.get("", response_model=list[VoiceResponse],
            summary="List voices", description="Your voices, newest first. Used by the picker dropdown.")
def list_voices(
    page: int = Query(default=1, ge=1, description="Page number (from 1)"),
    size: int = Query(default=20, ge=1, le=100, description="Items per page (1-100)"),
    language: str | None = Query(default=None, max_length=4, description="Filter by language code (e.g. hi)", examples=["hi"]),
    is_library: bool | None = Query(default=None, description="Filter by library flag"),
    voice_status: str | None = Query(default=None, alias="status", description="Filter: processing, ready or failed", examples=["ready"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    q = db.query(Voice)
    # per-key allow-list (Sec 10.4): null = all; JWT calls see everything
    if _ctx.api_key is not None and _ctx.api_key.allowed_voice_ids is not None:
        q = q.filter(Voice.id.in_(_ctx.api_key.allowed_voice_ids))
    if language is not None:
        q = q.filter(Voice.language == language.strip().lower())
    if is_library is not None:
        q = q.filter(Voice.is_library == is_library)
    if voice_status is not None:
        if voice_status not in ("processing", "ready", "failed"):
            raise HTTPException(status_code=422, detail="Invalid status filter")
        q = q.filter(Voice.status == voice_status)
    return (
        q.order_by(Voice.created_at.desc(), Voice.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


# 4.3 get one voice
@router.get("/{voice_id}", response_model=VoiceResponse,
            summary="Get one voice", description="Details + status (processing -> ready). Poll this after cloning.")
def get_voice(
    voice_id: str = Path(description="Voice id (voi_...)", examples=["voi_abc123"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    voice = db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")
    return voice


# 4.4 rename / flip library flag
@router.patch("/{voice_id}", response_model=VoiceResponse,
              summary="Rename voice", description="Change name or library flag. Audio untouched.")
def update_voice(
    voice_id: str = Path(description="Voice id (voi_...)", examples=["voi_abc123"]),
    payload: VoiceUpdate = Body(..., description="New name and/or library flag"),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    voice = db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")
    if payload.name is not None:
        clean = payload.name.strip()
        if not clean:
            raise HTTPException(status_code=422, detail="Name must not be empty")
        voice.name = clean
    if payload.is_library is not None:
        voice.is_library = payload.is_library
    db.commit()
    db.refresh(voice)
    return voice


# 4.5 delete voice + stored audio/embedding (hard delete, needed for consent-withdraw cascade)
@router.delete("/{voice_id}",
               summary="Delete voice", description="Permanently deletes voice + its audio files.")
def delete_voice(
    voice_id: str = Path(description="Voice id (voi_...)", examples=["voi_abc123"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    voice = db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")
    ref_key, emb_key = voice.reference_clip_key, voice.embedding_key
    db.delete(voice)
    log_action(db, _ctx, "voice.delete", "voice", voice_id)
    db.commit()
    delete_key(ref_key)
    delete_key(emb_key)
    return {"message": "Voice deleted", "id": voice_id}
