from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VoiceStatus = Literal["processing", "ready", "failed"]


# response model (doc 4.3: id, name, language, consent, status, library flag)
class VoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    language: str
    consent_id: str
    reference_clip_key: str
    embedding_key: str | None
    is_library: bool
    status: VoiceStatus
    created_at: datetime


# update model (doc 4.4: rename only — no description column exists)
class VoiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80, description="New voice name", examples=["Raju Final"])
    is_library: bool | None = Field(default=None, description="Mark as shared library voice")
