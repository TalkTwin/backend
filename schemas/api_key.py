from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# account self-service create: owner forced to caller, caps enforced in route
class AccountKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="Label to tell keys apart", examples=["my-laptop"])
    rate_limit_per_min: int = Field(default=60, ge=1, description="Requests per minute (capped for normal users)")
    max_concurrent_jobs: int = Field(default=2, ge=1, description="Max queued+running jobs (capped for normal users)")
    allowed_voice_ids: list[str] | None = Field(default=None, description="Voice ids you own or library (null = all)")
    allowed_avatar_ids: list[str] | None = Field(default=None, description="Avatar ids you own or library (null = all)")
    expires_at: datetime | None = Field(default=None, description="Optional expiry; omit for never")


# create: returns raw key ONCE (never stored, never returned again)
class ApiKeyCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=32, description="Owner user id (usr_...)", examples=["usr_abc123"])
    name: str = Field(min_length=1, max_length=80, description="Label to tell keys apart", examples=["studio-server"])
    rate_limit_per_min: int = Field(default=60, ge=1, le=10000, description="Requests per minute for this key")
    max_concurrent_jobs: int = Field(default=2, ge=1, le=20, description="Max queued+running jobs for this key")
    allowed_voice_ids: list[str] | None = Field(default=None, description="Voice ids this key may drive (null = all)", examples=[["voi_abc123"]])
    allowed_avatar_ids: list[str] | None = Field(default=None, description="Avatar ids this key may drive (null = all)")
    expires_at: datetime | None = Field(default=None, description="Optional expiry; omit for never")


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    key_prefix: str
    rate_limit_per_min: int
    max_concurrent_jobs: int
    allowed_voice_ids: list[str] | None
    allowed_avatar_ids: list[str] | None
    is_active: bool
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyCreateResponse(ApiKeyResponse):
    raw_key: str = Field(description="Full key — shown ONCE. Store it now, it is never returned again.")


# update: all optional (doc 2.5 — change limits/allow-lists without reissuing)
class ApiKeyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80, description="New label", examples=["worker-2"])
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=10000, description="New per-minute limit")
    max_concurrent_jobs: int | None = Field(default=None, ge=1, le=20, description="New concurrent-job cap")
    allowed_voice_ids: list[str] | None = Field(default=None, description="New voice allow-list (null = all)")
    allowed_avatar_ids: list[str] | None = Field(default=None, description="New avatar allow-list (null = all)")
    is_active: bool | None = Field(default=None, description="false = revoke without deleting history")
