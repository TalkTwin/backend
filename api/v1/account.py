# account router (tag "account"): self-service for any active user, own data only.
# Other users' rows always 404 (no oracle). Normal users are bound by config
# caps and voice/avatar ownership; admins bypass caps even here.
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import ApiContext, get_api_context, get_current_user, get_db
from core.config import NORMAL_KEY_CONCURRENT_MAX, NORMAL_KEY_RATE_MAX
from core.security import hash_password, verify_password
from models import Avatar, Job, User, Voice
from models.api_key import ApiKey
from schemas import (
    AccountKeyCreate, ApiKeyCreateResponse, ApiKeyResponse,
    ChangePasswordRequest, UsageMe, UserResponse, UserSelfUpdate,
)
from services.audit import log_action
from services.keys import clean_id_list, issue_key

router = APIRouter(tags=["account"])


def _me(ctx: ApiContext, db: Session) -> User:
    user = db.get(User, ctx.user.id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/users/me", response_model=UserResponse, summary="My profile")
def get_my_profile(ctx: ApiContext = Depends(get_api_context), db: Session = Depends(get_db)):
    return _me(ctx, db)


@router.patch("/users/me", response_model=UserResponse, summary="Update my profile",
              description="Name/email only. Role, status and quotas can never change here.")
def update_my_profile(
    payload: UserSelfUpdate = Body(...),
    ctx: ApiContext = Depends(get_api_context),
    db: Session = Depends(get_db),
):
    user = _me(ctx, db)
    if payload.name is not None:
        clean = payload.name.strip()
        if not clean:
            raise HTTPException(status_code=422, detail="Name must not be empty")
        user.name = clean
    if payload.email is not None:
        user.email = str(payload.email).lower().strip()
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    return user


@router.post("/users/me/password", summary="Change my password", description="JWT only.")
def change_my_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.get(User, current_user.id)
    if not user.password_hash:
        raise HTTPException(status_code=400, detail="This account has no password set")
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password changed"}


def _owned_or_library(db: Session, ids: list[str] | None, kind: str, user_id: str) -> None:
    # allow-list rule: each id must exist and be yours or library, else 403/404
    if not ids:
        return
    model = Voice if kind == "voice" else Avatar
    for vid in ids:
        row = db.get(model, vid)
        if not row:
            raise HTTPException(status_code=404, detail=f"{kind} not found: {vid}")
        if row.owner_user_id != user_id and not row.is_library:
            raise HTTPException(status_code=403, detail=f"{kind} not yours or library: {vid}")


@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED,
             summary="Create my key", description="Raw key shown ONCE. Caps + ownership enforced for normal users.")
def create_my_key(
    payload: AccountKeyCreate = Body(...),
    ctx: ApiContext = Depends(get_api_context),
    db: Session = Depends(get_db),
):
    user = _me(ctx, db)
    if user.role != "admin":
        if payload.rate_limit_per_min > NORMAL_KEY_RATE_MAX:
            raise HTTPException(status_code=403, detail=f"rate_limit_per_min capped at {NORMAL_KEY_RATE_MAX}")
        if payload.max_concurrent_jobs > NORMAL_KEY_CONCURRENT_MAX:
            raise HTTPException(status_code=403, detail=f"max_concurrent_jobs capped at {NORMAL_KEY_CONCURRENT_MAX}")
    voices = clean_id_list(payload.allowed_voice_ids)
    avatars = clean_id_list(payload.allowed_avatar_ids)
    _owned_or_library(db, voices, "voice", user.id)
    _owned_or_library(db, avatars, "avatar", user.id)
    key, raw = issue_key(db, user, payload.name, payload.rate_limit_per_min,
                         payload.max_concurrent_jobs, voices, avatars, payload.expires_at)
    log_action(db, ApiContext(user=user, api_key=None), "key.create", "api_key", key.id)
    db.commit()
    db.refresh(key)
    return ApiKeyCreateResponse(**ApiKeyResponse.model_validate(key).model_dump(), raw_key=raw)


@router.get("/api-keys", response_model=list[ApiKeyResponse], summary="My keys")
def list_my_keys(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    ctx: ApiContext = Depends(get_api_context),
    db: Session = Depends(get_db),
):
    user = _me(ctx, db)
    return (db.query(ApiKey).filter(ApiKey.user_id == user.id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
            .offset((page - 1) * size).limit(size).all())


@router.delete("/api-keys/{key_id}", response_model=ApiKeyResponse, summary="Revoke my key")
def revoke_my_key(
    key_id: str = Path(description="My key id (key_...)"),
    ctx: ApiContext = Depends(get_api_context),
    db: Session = Depends(get_db),
):
    user = _me(ctx, db)
    key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_id == user.id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.is_active = False
    log_action(db, ApiContext(user=user, api_key=None), "key.revoke", "api_key", key.id)
    db.commit()
    db.refresh(key)
    return key


@router.get("/usage/me", response_model=UsageMe, summary="My usage")
def my_usage(ctx: ApiContext = Depends(get_api_context), db: Session = Depends(get_db)):
    user = _me(ctx, db)
    base = db.query(Job).filter(Job.user_id == user.id)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return UsageMe(
        user_id=user.id,
        jobs_total=base.count(),
        jobs_active=base.filter(Job.status.in_(["queued", "running"])).count(),
        jobs_failed=base.filter(Job.status == "failed").count(),
        jobs_today=base.filter(Job.created_at >= today).count(),
        keys_active=db.query(ApiKey).filter(ApiKey.user_id == user.id, ApiKey.is_active == True).count(),
    )
