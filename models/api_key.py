import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy import JSON
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


def _new_key_id() -> str:
    return "key_" + secrets.token_hex(14)


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_api_keys_user_name"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_key_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    # sha256 hex of the raw key; raw is shown once at creation, never stored
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rate_limit_per_min: Mapped[int] = mapped_column(
        Integer, default=60, server_default="60", nullable=False
    )
    max_concurrent_jobs: Mapped[int] = mapped_column(
        Integer, default=2, server_default="2", nullable=False
    )
    # null = all voices/avatars allowed
    allowed_voice_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allowed_avatar_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sql_text("true"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
