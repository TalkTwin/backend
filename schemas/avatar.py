from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AvatarStatus = Literal["processing", "ready", "failed"]


# response model (doc 5.3: id, name, consent, status, library flag)
class AvatarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    consent_id: str
    image_key: str
    latents_key: str | None
    is_library: bool
    status: AvatarStatus
    created_at: datetime


# update model (doc 5.4: rename only — no description column exists)
class AvatarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80, description="New avatar name", examples=["Amit Final"])
    is_library: bool | None = Field(default=None, description="Mark as shared library avatar")
