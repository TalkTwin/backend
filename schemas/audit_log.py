from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


AuditOutcome = Literal["success", "refused", "error"]


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    api_key_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: AuditOutcome
    before: dict | None
    after: dict | None
    reason: str | None
    created_at: datetime
