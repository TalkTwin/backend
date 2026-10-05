from datetime import datetime, timedelta, timezone

import hashlib
import secrets

import bcrypt
import jwt

from core.config import ACCESS_TOKEN_EXPIRE_MINUTES, SECRET_KEY

ALGORITHM = "HS256"
API_KEY_PREFIX = "tt_"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def hash_api_key(raw: str) -> str:
    # fast sha256 (not bcrypt): 256-bit keys need no slow hash, and equality
    # lookup stays indexed. Raw is never stored — only this digest.
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    # returns (raw_key, prefix, hash). Show raw ONCE at creation, store hash only.
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:12], hash_api_key(raw)