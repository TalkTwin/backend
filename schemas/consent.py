from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ConsentScope = Literal["voice", "avatar", "both"]
ConsentStatus = Literal["active", "withdrawn"]


# create model (digital checkbox agreement — no document upload)
class ConsentCreate(BaseModel):
    subject_name: str = Field(min_length=1, max_length=120, description="Real person who agreed (voice owner, not you)", examples=["Amit Sharma"])
    scope: ConsentScope = Field(description="What the agreement covers", examples=["voice"])
    permitted_uses: list[str] = Field(min_length=1, max_length=20, description='Allowed uses, e.g. ["tts"]', examples=[["tts"]])
    signed_at: datetime = Field(description="When the person agreed (ISO datetime)")
    valid_until: datetime | None = Field(default=None, description="Optional expiry; omit for no expiry")


# response model (doc 3.2: full consent record)
class ConsentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_name: str
    scope: ConsentScope
    permitted_uses: list[str]
    status: ConsentStatus
    signed_at: datetime
    valid_until: datetime | None
    withdrawn_at: datetime | None
    created_at: datetime
