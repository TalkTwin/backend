# Single seam for every audit write. Caller commits (same transaction as the
# action) — an unlogged governance event is a compliance hole, so the log
# row succeeds or the action fails with it. High-volume speak logging later
# goes best-effort background instead; this helper stays for sync events.
from sqlalchemy.orm import Session

from api.deps import ApiContext
from models.audit_log import AuditLog


def log_action(
    db: Session,
    ctx: ApiContext,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: str = "success",
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> AuditLog:
    # rows reference, never contain: ids + outcome + safe snapshots only.
    # Callers must never put secrets, hashes or raw keys into before/after.
    row = AuditLog(
        user_id=ctx.user.id,
        api_key_id=ctx.api_key.id if ctx.api_key else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        before=before,
        after=after,
        reason=reason,
    )
    db.add(row)
    return row
