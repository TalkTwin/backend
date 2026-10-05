# Shared issuance core: account (own keys, caps) and admin (any user, no caps)
# both funnel here so hashing/raw-once can never drift apart.
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.security import generate_api_key
from models.api_key import ApiKey
from models.user import User


def issue_key(
    db: Session,
    owner: User,
    name: str,
    rate_limit_per_min: int,
    max_concurrent_jobs: int,
    allowed_voice_ids: list[str] | None,
    allowed_avatar_ids: list[str] | None,
    expires_at: datetime | None,
) -> tuple[ApiKey, str]:
    clean = name.strip()
    if not clean:
        raise HTTPException(status_code=422, detail="name must not be empty")
    raw, prefix, digest = generate_api_key()
    key = ApiKey(user_id=owner.id, name=clean, key_prefix=prefix, key_hash=digest,
                 rate_limit_per_min=rate_limit_per_min,
                 max_concurrent_jobs=max_concurrent_jobs,
                 allowed_voice_ids=allowed_voice_ids, allowed_avatar_ids=allowed_avatar_ids,
                 is_active=True, expires_at=expires_at)
    db.add(key)
    try:
        db.flush()  # surface dup-name before the caller adds audit rows
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Key name already used for this user")
    return key, raw


def clean_id_list(items: list[str] | None) -> list[str] | None:
    if items is None:
        return None
    return list(dict.fromkeys(i.strip() for i in items if i.strip()))
