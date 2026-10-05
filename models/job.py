import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy import func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


JOB_TYPES = ("tts", "generate", "speak")
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled")
JOB_MODERATIONS = ("passed", "flagged", "refused")


def _new_job_id() -> str:
    return "job_" + secrets.token_hex(14)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index(
            "uq_jobs_user_idem",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sql_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_job_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # real FK once api_keys exists (SET NULL keeps job history on key delete)
    api_key_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued", nullable=False, index=True
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(4), nullable=True)
    voice_id: Mapped[str | None] = mapped_column(
        ForeignKey("voices.id", ondelete="SET NULL"), nullable=True
    )
    avatar_id: Mapped[str | None] = mapped_column(
        ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_generated: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sql_text("true"), nullable=False
    )
    moderation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
