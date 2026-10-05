# avatars apis: register, list, get, update, delete (doc 5.1-5.5)
# auth: JWT for now (api_keys skipped) — switch to key context later
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Path, Query, UploadFile, status
from sqlalchemy.orm import Session

from api.deps import ApiContext, get_api_context, get_db
from core.config import ALLOWED_IMAGE_EXTS, MAX_IMAGE_MB
from core.db import SessionLocal
from core.storage import avatar_image_path, avatar_latents_path, delete_key, save_bytes
from models.avatar import _new_avatar_id
from models.avatar import Avatar
from models.consent import Consent
from schemas import AvatarResponse, AvatarUpdate
from services.audit import log_action

router = APIRouter(prefix="/avatars", tags=["avatars"])

MAX_BYTES = MAX_IMAGE_MB * 1024 * 1024


def _latents_stub(avatar_id: str) -> None:
    # Runs in BackgroundTasks with its own session (request session is closed).
    # TODO: replace with Celery workers/tasks.py real face-preprocessing
    # (detection/alignment/latents per avatar_id, Sec 12.3).
    db = SessionLocal()
    try:
        avatar = db.get(Avatar, avatar_id)
        if not avatar or avatar.status != "processing":
            return
        dest, rel = avatar_latents_path(avatar_id)
        try:
            save_bytes(dest, b"stub-latents")
            avatar.latents_key = rel
            avatar.status = "ready"
            db.commit()
        except OSError:
            db.rollback()
            avatar.status = "failed"
            db.commit()
    finally:
        db.close()


# 5.1 register an avatar from a face image -> 201 + avatar (processing)
@router.post("", response_model=AvatarResponse, status_code=status.HTTP_201_CREATED,
             summary="Register avatar", description="Upload a face image + consent_id. Returns processing, becomes ready in seconds.")
def create_avatar(
    background: BackgroundTasks,
    name: str = Form(min_length=1, max_length=80, description="Display name for this avatar", examples=["Amit Presenter"]),
    consent_id: str = Form(min_length=1, max_length=32, description="Active consent id from POST /v1/consents (cst_...)", examples=["cst_abc123"]),
    is_library: bool = Form(default=False, description="Mark as shared library avatar"),
    image: UploadFile = File(..., description="Face photo (jpg/png/gif/webp, max 10MB)"),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=422, detail="Name must not be empty")
    consent = consent_id.strip()
    if not consent:
        raise HTTPException(status_code=422, detail="consent_id must not be empty")
    c = db.get(Consent, consent)
    if not c:
        raise HTTPException(status_code=404, detail="Consent not found")
    if c.status != "active":
        raise HTTPException(status_code=422, detail="Consent is withdrawn")
    if c.scope not in ("avatar", "both"):
        raise HTTPException(status_code=422, detail="Consent scope does not cover avatar")

    filename = image.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported image type '{ext or '(none)'}'. Allowed: {sorted(ALLOWED_IMAGE_EXTS)}",
        )
    data = image.file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty image file")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Image too large (max {MAX_IMAGE_MB}MB)")

    avatar_id = _new_avatar_id()
    dest, rel = avatar_image_path(avatar_id, ext)
    try:
        save_bytes(dest, data)
    except OSError:
        raise HTTPException(status_code=500, detail="Failed to store image")

    avatar = Avatar(
        id=avatar_id,
        name=clean_name,
        consent_id=consent,
        owner_user_id=_ctx.user.id,
        image_key=rel,
        latents_key=None,
        is_library=is_library,
        status="processing",
    )
    db.add(avatar)
    try:
        db.commit()
        db.refresh(avatar)
    except Exception:
        db.rollback()
        delete_key(rel)
        raise HTTPException(status_code=500, detail="Failed to create avatar")

    background.add_task(_latents_stub, avatar_id)
    return avatar


# 5.2 list avatars (paginated + filters)
@router.get("", response_model=list[AvatarResponse],
            summary="List avatars", description="Your avatars, newest first. Used by the picker dropdown.")
def list_avatars(
    page: int = Query(default=1, ge=1, description="Page number (from 1)"),
    size: int = Query(default=20, ge=1, le=100, description="Items per page (1-100)"),
    is_library: bool | None = Query(default=None, description="Filter by library flag"),
    avatar_status: str | None = Query(default=None, alias="status", description="Filter: processing, ready or failed", examples=["ready"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    q = db.query(Avatar)
    # per-key allow-list (Sec 10.4): null = all; JWT calls see everything
    if _ctx.api_key is not None and _ctx.api_key.allowed_avatar_ids is not None:
        q = q.filter(Avatar.id.in_(_ctx.api_key.allowed_avatar_ids))
    if is_library is not None:
        q = q.filter(Avatar.is_library == is_library)
    if avatar_status is not None:
        if avatar_status not in ("processing", "ready", "failed"):
            raise HTTPException(status_code=422, detail="Invalid status filter")
        q = q.filter(Avatar.status == avatar_status)
    return (
        q.order_by(Avatar.created_at.desc(), Avatar.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


# 5.3 get one avatar
@router.get("/{avatar_id}", response_model=AvatarResponse,
            summary="Get one avatar", description="Details + status (processing -> ready). Poll this after registering.")
def get_avatar(
    avatar_id: str = Path(description="Avatar id (avt_...)", examples=["avt_abc123"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    avatar = db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return avatar


# 5.4 rename / flip library flag
@router.patch("/{avatar_id}", response_model=AvatarResponse,
              summary="Rename avatar", description="Change name or library flag. Image untouched.")
def update_avatar(
    avatar_id: str = Path(description="Avatar id (avt_...)", examples=["avt_abc123"]),
    payload: AvatarUpdate = Body(..., description="New name and/or library flag"),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    avatar = db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    if payload.name is not None:
        clean = payload.name.strip()
        if not clean:
            raise HTTPException(status_code=422, detail="Name must not be empty")
        avatar.name = clean
    if payload.is_library is not None:
        avatar.is_library = payload.is_library
    db.commit()
    db.refresh(avatar)
    return avatar


# 5.5 delete avatar + stored image/latents (hard delete, needed for consent-withdraw cascade)
@router.delete("/{avatar_id}",
               summary="Delete avatar", description="Permanently deletes avatar + its image files.")
def delete_avatar(
    avatar_id: str = Path(description="Avatar id (avt_...)", examples=["avt_abc123"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    avatar = db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    img_key, lat_key = avatar.image_key, avatar.latents_key
    db.delete(avatar)
    log_action(db, _ctx, "avatar.delete", "avatar", avatar_id)
    db.commit()
    delete_key(img_key)
    delete_key(lat_key)
    return {"message": "Avatar deleted", "id": avatar_id}
