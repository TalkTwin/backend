from pydantic import BaseModel, ConfigDict


class UsageMe(BaseModel):
    user_id: str
    jobs_total: int
    jobs_active: int
    jobs_failed: int
    jobs_today: int
    keys_active: int


class StatsOverview(BaseModel):
    users_total: int
    users_active: int
    admins_active: int
    jobs_total: int
    jobs_today: int
    jobs_active: int
    jobs_failed: int


class ReasonInput(BaseModel):
    reason: str


class LibraryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_library: bool
