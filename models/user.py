import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


USER_ROLES = ("user", "admin")


def _new_user_id() -> str:
    return "usr_" + secrets.token_hex(14)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_user_id)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user", nullable=False)
    # admin-settable quota overrides (null = system defaults); never settable by self
    rate_limit_per_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_concurrent_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )