import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Response, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.db import SessionLocal
from core.security import decode_access_token, hash_api_key
from models import ApiKey, User

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    authenticate_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authenticate_error

    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise authenticate_error

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise authenticate_error
    return user


@dataclass
class ApiContext:
    user: User
    api_key: ApiKey | None  # None = JWT call (human); set = key call (machine)


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    # JWT-only (keys are machine creds for service routes). Role + active are
    # re-read from the DB every request, so demotion/disable bites immediately.
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise unauthorized
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise unauthorized
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# in-memory sliding window per key_hash.
# TODO: Redis — this is per-process and lies under --workers > 1.
_rate_lock = threading.Lock()
_rate_hits: dict[str, deque] = {}


def _check_rate_limit(key: ApiKey, response: Response) -> None:
    now = time.monotonic()
    window = 60.0
    with _rate_lock:
        hits = _rate_hits.setdefault(key.key_hash, deque())
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= key.rate_limit_per_min:
            retry = max(1, int(hits[0] + window - now))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({key.rate_limit_per_min}/min)",
                headers={"Retry-After": str(retry)},
            )
        hits.append(now)
        # bound memory: drop idle keys (cap tracked keys)
        if len(_rate_hits) > 10000:
            _rate_hits.clear()
    response.headers["X-RateLimit-Limit"] = str(key.rate_limit_per_min)


def get_api_context(
    response: Response,
    api_key: str | None = Depends(_api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> ApiContext:
    key_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    if api_key:
        digest = hash_api_key(api_key.strip())
        key = db.query(ApiKey).filter(ApiKey.key_hash == digest).first()
        if not key or not key.is_active:
            raise key_error
        if key.expires_at and key.expires_at <= datetime.now(timezone.utc):
            raise key_error
        user = db.get(User, key.user_id)
        if not user or not user.is_active:
            raise key_error
        # throttle last_used_at: at most one write per 5 min (avoids hot-row writes)
        now = datetime.now(timezone.utc)
        if not key.last_used_at or (now - key.last_used_at).total_seconds() > 300:
            key.last_used_at = now
            db.commit()
        _check_rate_limit(key, response)
        return ApiContext(user=user, api_key=key)

    # no key header -> JWT path (same rules as get_current_user)
    authenticate_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authenticate_error
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise authenticate_error
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise authenticate_error
    return ApiContext(user=user, api_key=None)
