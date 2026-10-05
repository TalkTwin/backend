# admin router (tag "admin"): platform administration. ONE require_admin
# dependency on the whole router — every route below is admin-only.
# Safety: no self-disable/demote, last-admin protected, disable revokes keys +
# cancels jobs, every write audited (reason required for disable/enable/rotate).
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import ApiContext, get_db, require_admin
from core.security import generate_api_key, hash_password
from models import AuditLog, Avatar, Job, User, Voice
from models.api_key import ApiKey
from schemas import (
    AdminUserCreate, AdminUserResponse, AdminUserUpdate, ApiKeyCreate, ApiKeyCreateResponse,
    ApiKeyResponse, ApiKeyUpdate, AuditLogResponse, AvatarResponse, JobResponse,
    LibraryPatch, ReasonInput, StatsOverview, VoiceResponse,
)
from services.audit import log_action
from services.keys import clean_id_list, issue_key

router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(require_admin)])


def _actor(admin: User, db: Session) -> ApiContext:
    return ApiContext(user=db.get(User, admin.id), api_key=None)


def _need_reason(payload: ReasonInput | None) -> str:
    reason = (payload.reason if payload else "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="reason is required")
    return reason[:500]


def _get_user_or_404(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _guard_self(actor: ApiContext, target: User, what: str) -> None:
    if actor.user.id == target.id:
        raise HTTPException(status_code=403, detail=f"cannot {what} yourself")


def _guard_last_admin(db: Session, target: User) -> None:
    if target.role != "admin" or not target.is_active:
        return
    remaining = db.query(User).filter(
        User.role == "admin", User.is_active == True, User.id != target.id).count()
    if remaining < 1:
        raise HTTPException(status_code=409, detail="last active admin is protected")


def _deactivate_side_effects(db: Session, user: User) -> None:
    # disable = revoke all keys + cancel live jobs. Voices/avatars stay
    # (consent withdrawal is the separate content-deletion flow).
    db.query(ApiKey).filter(ApiKey.user_id == user.id).update({"is_active": False})
    now = datetime.now(timezone.utc)
    db.query(Job).filter(Job.user_id == user.id,
                         Job.status.in_(["queued", "running"])).update(
        {"status": "cancelled", "finished_at": now})


def _public_snapshot(user: User) -> dict:
    return {"role": user.role, "is_active": user.is_active,
            "rate_limit_per_min": user.rate_limit_per_min,
            "max_concurrent_jobs": user.max_concurrent_jobs}


# ---------- users ----------

@router.get("/users", response_model=list[AdminUserResponse], summary="List users")
def admin_list_users(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    role: str | None = Query(default=None, description="Filter: user or admin"),
    is_active: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if role is not None:
        if role not in ("user", "admin"):
            raise HTTPException(status_code=422, detail="Invalid role filter")
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active == is_active)
    return (q.order_by(User.created_at, User.id)
            .offset((page - 1) * size).limit(size).all())


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED,
             summary="Create user", description="Admin creates any user, optionally admin.")
def admin_create_user(
    payload: AdminUserCreate = Body(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    email = str(payload.email).lower().strip()
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name must not be empty")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(name=name, email=email, password_hash=hash_password(payload.password),
                role=payload.role, is_active=True)
    db.add(user)
    try:
        db.flush()
        log_action(db, _actor(admin, db), "user.create", "user", user.id,
                   outcome="success", after=_public_snapshot(user))
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    return user


@router.get("/users/{user_id}", response_model=AdminUserResponse, summary="Get one user")
def admin_get_user(user_id: str = Path(...), db: Session = Depends(get_db)):
    return _get_user_or_404(db, user_id)


@router.patch("/users/{user_id}", response_model=AdminUserResponse, summary="Update user",
              description="Name/email/role/quotas. Status changes go through disable/enable (reason-gated).")
def admin_update_user(
    user_id: str = Path(...),
    payload: AdminUserUpdate = Body(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = _get_user_or_404(db, user_id)
    actor = _actor(admin, db)
    if payload.is_active is not None:
        raise HTTPException(status_code=422, detail="use disable/enable endpoints for status changes")
    before = _public_snapshot(user)
    if payload.name is not None:
        clean = payload.name.strip()
        if not clean:
            raise HTTPException(status_code=422, detail="Name must not be empty")
        user.name = clean
    if payload.email is not None:
        user.email = str(payload.email).lower().strip()
    if payload.role is not None and payload.role != user.role:
        _guard_self(actor, user, "demote")
        if payload.role == "user":
            _guard_last_admin(db, user)
        user.role = payload.role
    if payload.rate_limit_per_min is not None:
        user.rate_limit_per_min = payload.rate_limit_per_min
    if payload.max_concurrent_jobs is not None:
        user.max_concurrent_jobs = payload.max_concurrent_jobs
    try:
        db.flush()
        log_action(db, actor, "user.update", "user", user.id,
                   outcome="success", before=before, after=_public_snapshot(user))
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    return user


@router.post("/users/{user_id}/disable", response_model=AdminUserResponse,
             summary="Disable user", description="Reason required. Revokes keys, cancels live jobs.")
def admin_disable_user(
    user_id: str = Path(...),
    payload: ReasonInput | None = Body(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    reason = _need_reason(payload)
    user = _get_user_or_404(db, user_id)
    actor = _actor(admin, db)
    _guard_self(actor, user, "disable")
    _guard_last_admin(db, user)
    before = _public_snapshot(user)
    user.is_active = False
    _deactivate_side_effects(db, user)
    log_action(db, actor, "user.disable", "user", user.id,
               outcome="success", before=before, after=_public_snapshot(user), reason=reason)
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/enable", response_model=AdminUserResponse,
             summary="Enable user", description="Reason required. Keys stay revoked — reissue them.")
def admin_enable_user(
    user_id: str = Path(...),
    payload: ReasonInput | None = Body(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    reason = _need_reason(payload)
    user = _get_user_or_404(db, user_id)
    actor = _actor(admin, db)
    before = _public_snapshot(user)
    user.is_active = True
    log_action(db, actor, "user.enable", "user", user.id,
               outcome="success", before=before, after=_public_snapshot(user), reason=reason)
    db.commit()
    db.refresh(user)
    return user


# ---------- api keys ----------

@router.get("/api-keys", response_model=list[ApiKeyResponse], summary="List all keys")
def admin_list_keys(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user_id: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(ApiKey)
    if user_id is not None:
        q = q.filter(ApiKey.user_id == user_id.strip())
    if is_active is not None:
        q = q.filter(ApiKey.is_active == is_active)
    return (q.order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
            .offset((page - 1) * size).limit(size).all())


@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED,
             summary="Issue key for anyone", description="No caps for admins. Raw shown ONCE.")
def admin_create_key(
    payload: ApiKeyCreate = Body(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    owner = db.get(User, payload.user_id.strip())
    if not owner:
        raise HTTPException(status_code=404, detail="User not found")
    if not owner.is_active:
        raise HTTPException(status_code=422, detail="User is not active")
    key, raw = issue_key(db, owner, payload.name, payload.rate_limit_per_min,
                         payload.max_concurrent_jobs, clean_id_list(payload.allowed_voice_ids),
                         clean_id_list(payload.allowed_avatar_ids), payload.expires_at)
    log_action(db, _actor(admin, db), "key.create", "api_key", key.id)
    db.commit()
    db.refresh(key)
    return ApiKeyCreateResponse(**ApiKeyResponse.model_validate(key).model_dump(), raw_key=raw)


@router.patch("/api-keys/{key_id}", response_model=ApiKeyResponse, summary="Update any key")
def admin_update_key(
    key_id: str = Path(...),
    payload: ApiKeyUpdate = Body(..., description="Fields to change (all optional)"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    key = db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    actor = _actor(admin, db)
    before = {"name": key.name, "rate_limit_per_min": key.rate_limit_per_min,
              "max_concurrent_jobs": key.max_concurrent_jobs, "is_active": key.is_active}
    if payload.name is not None:
        clean = payload.name.strip()
        if not clean:
            raise HTTPException(status_code=422, detail="name must not be empty")
        key.name = clean
    if payload.rate_limit_per_min is not None:
        key.rate_limit_per_min = payload.rate_limit_per_min
    if payload.max_concurrent_jobs is not None:
        key.max_concurrent_jobs = payload.max_concurrent_jobs
    if payload.allowed_voice_ids is not None:
        key.allowed_voice_ids = clean_id_list(payload.allowed_voice_ids)
    if payload.allowed_avatar_ids is not None:
        key.allowed_avatar_ids = clean_id_list(payload.allowed_avatar_ids)
    if payload.is_active is not None:
        key.is_active = payload.is_active
    try:
        db.flush()
        log_action(db, actor, "key.update", "api_key", key.id, outcome="success",
                   before=before, after={"name": key.name, "rate_limit_per_min": key.rate_limit_per_min,
                                         "max_concurrent_jobs": key.max_concurrent_jobs, "is_active": key.is_active})
        db.commit()
        db.refresh(key)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Key name already used for this user")
    return key


@router.post("/api-keys/{key_id}/rotate", response_model=ApiKeyCreateResponse,
             summary="Rotate key", description="Reason required. New raw shown ONCE; old stops working instantly.")
def admin_rotate_key(
    key_id: str = Path(...),
    payload: ReasonInput | None = Body(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    reason = _need_reason(payload)
    key = db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    actor = _actor(admin, db)
    before = {"key_prefix": key.key_prefix}
    raw, prefix, digest = generate_api_key()
    key.key_prefix = prefix
    key.key_hash = digest
    after = {"key_prefix": prefix}
    log_action(db, actor, "key.rotate", "api_key", key.id,
               outcome="success", before=before, after=after, reason=reason)
    db.commit()
    db.refresh(key)
    return ApiKeyCreateResponse(**ApiKeyResponse.model_validate(key).model_dump(), raw_key=raw)


@router.delete("/api-keys/{key_id}", response_model=ApiKeyResponse, summary="Revoke key")
def admin_revoke_key(
    key_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    key = db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.is_active = False
    log_action(db, _actor(admin, db), "key.revoke", "api_key", key.id)
    db.commit()
    db.refresh(key)
    return key


# ---------- audit ----------

@router.get("/audit-logs", response_model=list[AuditLogResponse], summary="Search audit trail")
def admin_list_audit(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    api_key_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    since: datetime | None = Query(default=None, description="Only rows at/after this time (ISO)"),
    until: datetime | None = Query(default=None, description="Only rows at/before this time (ISO)"),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if api_key_id is not None:
        q = q.filter(AuditLog.api_key_id == api_key_id.strip())
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id.strip())
    if action is not None:
        q = q.filter(AuditLog.action == action.strip())
    if resource_type is not None:
        q = q.filter(AuditLog.resource_type == resource_type.strip().lower())
    if outcome is not None:
        if outcome not in ("success", "refused", "error"):
            raise HTTPException(status_code=422, detail="Invalid outcome filter")
        q = q.filter(AuditLog.outcome == outcome)
    if since is not None:
        q = q.filter(AuditLog.created_at >= since)
    if until is not None:
        q = q.filter(AuditLog.created_at <= until)
    return (q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * size).limit(size).all())


@router.get("/audit-logs/{log_id}", response_model=AuditLogResponse, summary="Get one audit entry")
def admin_get_audit(log_id: str = Path(...), db: Session = Depends(get_db)):
    row = db.get(AuditLog, log_id)
    if not row:
        raise HTTPException(status_code=404, detail="Audit entry not found")
    return row


# ---------- jobs ----------

@router.get("/jobs", response_model=list[dict], summary="All jobs",
            description="Every user's jobs. Detail shape matches GET /v1/jobs/{id}.")
def admin_list_jobs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user_id: str | None = Query(default=None),
    job_type: str | None = Query(default=None, alias="type"),
    job_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    from api.v1.jobs import to_response as _to_resp, _dump as _dump_resp
    q = db.query(Job)
    if user_id is not None:
        q = q.filter(Job.user_id == user_id.strip())
    if job_type is not None:
        if job_type not in ("tts", "generate", "speak"):
            raise HTTPException(status_code=422, detail="Invalid type filter")
        q = q.filter(Job.type == job_type)
    if job_status is not None:
        if job_status not in ("queued", "running", "completed", "failed", "cancelled"):
            raise HTTPException(status_code=422, detail="Invalid status filter")
        q = q.filter(Job.status == job_status)
    return [_dump_resp(_to_resp(j)) for j in q.order_by(Job.created_at.desc(), Job.id.desc())
            .offset((page - 1) * size).limit(size).all()]


@router.get("/jobs/{job_id}", summary="Get any job")
def admin_get_job(job_id: str = Path(...), db: Session = Depends(get_db)):
    from api.v1.jobs import to_response as _to_resp, _dump as _dump_resp
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _dump_resp(_to_resp(job))


@router.post("/jobs/{job_id}/cancel", summary="Cancel any job")
def admin_cancel_job(
    job_id: str = Path(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from datetime import timezone as _tz
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {job.status} job")
    job.status = "cancelled"
    job.finished_at = datetime.now(_tz.utc)
    log_action(db, _actor(admin, db), "job.cancel", "job", job.id)
    db.commit()
    from api.v1.jobs import to_response as _to_resp, _dump as _dump_resp
    return _dump_resp(_to_resp(job))


# ---------- content ----------

@router.get("/voices", response_model=list[VoiceResponse], summary="All voices")
def admin_list_voices(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    is_library: bool | None = Query(default=None),
    voice_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    q = db.query(Voice)
    if is_library is not None:
        q = q.filter(Voice.is_library == is_library)
    if voice_status is not None:
        if voice_status not in ("processing", "ready", "failed"):
            raise HTTPException(status_code=422, detail="Invalid status filter")
        q = q.filter(Voice.status == voice_status)
    return (q.order_by(Voice.created_at.desc(), Voice.id.desc())
            .offset((page - 1) * size).limit(size).all())


@router.get("/avatars", response_model=list[AvatarResponse], summary="All avatars")
def admin_list_avatars(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    is_library: bool | None = Query(default=None),
    avatar_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    q = db.query(Avatar)
    if is_library is not None:
        q = q.filter(Avatar.is_library == is_library)
    if avatar_status is not None:
        if avatar_status not in ("processing", "ready", "failed"):
            raise HTTPException(status_code=422, detail="Invalid status filter")
        q = q.filter(Avatar.status == avatar_status)
    return (q.order_by(Avatar.created_at.desc(), Avatar.id.desc())
            .offset((page - 1) * size).limit(size).all())


@router.patch("/voices/{voice_id}", response_model=VoiceResponse, summary="Toggle library voice")
def admin_patch_voice(
    voice_id: str = Path(...),
    payload: LibraryPatch = Body(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    voice = db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")
    before = {"is_library": voice.is_library}
    voice.is_library = payload.is_library
    db.flush()
    log_action(db, _actor(admin, db), "voice.update", "voice", voice.id,
               outcome="success", before=before, after={"is_library": voice.is_library})
    db.commit()
    db.refresh(voice)
    return voice


@router.patch("/avatars/{avatar_id}", response_model=AvatarResponse, summary="Toggle library avatar")
def admin_patch_avatar(
    avatar_id: str = Path(...),
    payload: LibraryPatch = Body(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    avatar = db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    before = {"is_library": avatar.is_library}
    avatar.is_library = payload.is_library
    db.flush()
    log_action(db, _actor(admin, db), "avatar.update", "avatar", avatar.id,
               outcome="success", before=before, after={"is_library": avatar.is_library})
    db.commit()
    db.refresh(avatar)
    return avatar


# ---------- stats ----------

@router.get("/stats/overview", response_model=StatsOverview, summary="Platform stats")
def admin_stats(db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return StatsOverview(
        users_total=db.query(User).count(),
        users_active=db.query(User).filter(User.is_active == True).count(),
        admins_active=db.query(User).filter(User.role == "admin", User.is_active == True).count(),
        jobs_total=db.query(Job).count(),
        jobs_today=db.query(Job).filter(Job.created_at >= today).count(),
        jobs_active=db.query(Job).filter(Job.status.in_(["queued", "running"])).count(),
        jobs_failed=db.query(Job).filter(Job.status == "failed").count(),
    )
