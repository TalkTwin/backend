from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


UserRole = Literal["user", "admin"]


# pydantic models for users (doc section 1: no POST, only response + update)

# response model (doc 1.2: id, name, email, is_active)
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime


# admin view (quotas included; still never password_hash)
class AdminUserResponse(UserResponse):
    rate_limit_per_min: int | None
    max_concurrent_jobs: int | None


# self update (account): name/email only — role/is_active/quotas impossible
class UserSelfUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = Field(default=None, max_length=255)


# admin create (admin router only — the one place role can be granted)
class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=6, max_length=128)
    role: UserRole = "user"


# admin update: role/is_active/quotas allowed here and nowhere else
class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = Field(default=None, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=10000)
    max_concurrent_jobs: int | None = Field(default=None, ge=1, le=20)
