# consents apis: register, get, list, withdraw (doc 3.1-3.4)
# Digital checkbox agreement — no document upload. Sec 26 enforced via
# active-status + scope checks on voice/avatar creation and cascade on withdraw.
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from api.deps import ApiContext, get_api_context, get_db
from core.storage import delete_key
from models.avatar import Avatar
from models.voice import Voice
from models.consent import Consent
from schemas import ConsentResponse
from schemas.consent import ConsentCreate
from services.audit import log_action

router = APIRouter(prefix="/consents", tags=["consents"])


# 3.1 register a digital consent (plain JSON, checkbox-style)
@router.post("", response_model=ConsentResponse, status_code=status.HTTP_201_CREATED,
             summary="Add consent", description="Step 1 for voices: record who agreed. Returns cst_... id.")
def create_consent(
    payload: ConsentCreate,
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    subject = payload.subject_name.strip()
    if not subject:
        raise HTTPException(status_code=422, detail="subject_name must not be empty")
    uses = [u.strip() for u in payload.permitted_uses if u.strip()]
    if not uses:
        raise HTTPException(status_code=422, detail="permitted_uses must not be empty")
    if any(len(u) > 64 for u in uses):
        raise HTTPException(status_code=422, detail="permitted_uses items max 64 chars")
    if payload.valid_until is not None and payload.valid_until <= payload.signed_at:
        raise HTTPException(status_code=422, detail="valid_until must be after signed_at")

    consent = Consent(
        subject_name=subject,
        scope=payload.scope,
        permitted_uses=list(dict.fromkeys(uses)),
        status="active",
        signed_at=payload.signed_at,
        valid_until=payload.valid_until,
        withdrawn_at=None,
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return consent


# 3.3 list consents (picker UI / review)
@router.get("", response_model=list[ConsentResponse],
            summary="List consents", description="All agreements, newest first. Filter by scope/status.")
def list_consents(
    page: int = Query(default=1, ge=1, description="Page number (from 1)"),
    size: int = Query(default=20, ge=1, le=100, description="Items per page (1-100)"),
    scope: str | None = Query(default=None, description="Filter: voice, avatar or both", examples=["voice"]),
    consent_status: str | None = Query(default=None, alias="status", description="Filter: active or withdrawn", examples=["active"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    q = db.query(Consent)
    if scope is not None:
        sc = scope.strip().lower()
        if sc not in ("voice", "avatar", "both"):
            raise HTTPException(status_code=422, detail="Invalid scope filter")
        q = q.filter(Consent.scope == sc)
    if consent_status is not None:
        if consent_status not in ("active", "withdrawn"):
            raise HTTPException(status_code=422, detail="Invalid status filter")
        q = q.filter(Consent.status == consent_status)
    return (
        q.order_by(Consent.created_at.desc(), Consent.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


# 3.2 read one consent (voices/avatars verify this before proceeding)
@router.get("/{consent_id}", response_model=ConsentResponse,
            summary="Get one consent", description="Check a consent exists, is active and covers the scope.")
def get_consent(
    consent_id: str = Path(description="Consent id (cst_...)", examples=["cst_abc123"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    consent = db.get(Consent, consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")
    return consent


# 3.4 withdraw consent -> status=withdrawn + delete linked voices (avatars TODO)
@router.post("/{consent_id}/withdraw", response_model=ConsentResponse,
             summary="Withdraw consent", description="Marks withdrawn + permanently deletes its voices and avatars (law requirement).")
def withdraw_consent(
    consent_id: str = Path(description="Consent id (cst_...)", examples=["cst_abc123"]),
    db: Session = Depends(get_db),
    _ctx: ApiContext = Depends(get_api_context),
):
    consent = db.get(Consent, consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")
    if consent.status == "withdrawn":
        return consent  # idempotent for retries

    # cascade: hard-delete linked voices + avatars and their files (Sec 26: deletion on withdrawal)
    linked = db.query(Voice).filter(Voice.consent_id == consent.id).all()
    file_keys: list[str | None] = []
    for v in linked:
        file_keys.append(v.reference_clip_key)
        file_keys.append(v.embedding_key)
        db.delete(v)
    for a in db.query(Avatar).filter(Avatar.consent_id == consent.id).all():
        file_keys.append(a.image_key)
        file_keys.append(a.latents_key)
        db.delete(a)

    consent.status = "withdrawn"
    consent.withdrawn_at = datetime.now(timezone.utc)
    log_action(db, _ctx, "consent.withdraw", "consent", consent.id)
    db.commit()
    db.refresh(consent)
    for k in file_keys:
        delete_key(k)
    return consent
