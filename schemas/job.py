from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


JobType = Literal["tts", "generate", "speak"]
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
JobModeration = Literal["passed", "flagged", "refused"]


# create: tts needs text + ready voice + language
class JobCreateTTS(BaseModel):
    text: str = Field(min_length=1, description="Text to speak", examples=["Namaste, welcome to TalkTwin"])
    voice_id: str = Field(min_length=1, max_length=32, description="Ready voice id (voi_...)", examples=["voi_abc123"])
    language: str = Field(min_length=2, max_length=4, description="Language code (e.g. en, hi)", examples=["hi"])


# create: generate needs text + ready avatar (voice/language optional)
class JobCreateGenerate(BaseModel):
    text: str = Field(min_length=1, description="Script for the avatar", examples=["Namaste, welcome to TalkTwin"])
    avatar_id: str = Field(min_length=1, max_length=32, description="Ready avatar id (avt_...)", examples=["avt_abc123"])
    voice_id: str | None = Field(default=None, max_length=32, description="Ready voice id, else silent avatar", examples=["voi_abc123"])
    language: str | None = Field(default=None, min_length=2, max_length=4, description="Language code (e.g. en, hi)", examples=["hi"])


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: JobType
    status: JobStatus
    text: str | None
    language: str | None
    voice_id: str | None
    avatar_id: str | None
    result_url: str | None = None
    duration_sec: float | None
    ai_generated: bool
    moderation: JobModeration | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
