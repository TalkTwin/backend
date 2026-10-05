import secrets
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


CONSENT_SCOPES = ("voice", "avatar", "both")
CONSENT_STATUSES = ("active", "withdrawn")


def _new_consent_id() -> str:
    return "cst_" + secrets.token_hex(14)


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_consent_id)
    subject_name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(16), index=True)
    permitted_uses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", nullable=False, index=True
    )
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
