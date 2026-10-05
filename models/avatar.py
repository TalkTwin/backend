import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


AVATAR_STATUSES = ("processing", "ready", "failed")


def _new_avatar_id() -> str:
    return "avt_" + secrets.token_hex(14)


class Avatar(Base):
    __tablename__ = "avatars"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_avatar_id)
    name: Mapped[str] = mapped_column(String(80))
    # FK -> consents.id enforced at API layer (active + scope avatar/both check)
    consent_id: Mapped[str] = mapped_column(String(32), index=True)
    # creator owner (null = legacy row: usable only if is_library)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    image_key: Mapped[str] = mapped_column(String(255))
    latents_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_library: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default="processing", server_default="processing", nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
