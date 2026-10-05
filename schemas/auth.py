from pydantic import BaseModel, ConfigDict, EmailStr, Field


# register request (open signup — anyone with network access can create a user)
class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120, description="Your display name", examples=["Aryan"])
    email: EmailStr = Field(max_length=255, description="Login email (stored lowercase)", examples=["aryan@example.com"])
    password: str = Field(min_length=6, max_length=128, description="Min 6 chars", examples=["StrongPass123"])


# login request
class LoginRequest(BaseModel):
    email: EmailStr = Field(description="Registered email (any case)", examples=["aryan@example.com"])
    password: str = Field(description="Account password", examples=["StrongPass123"])


# login response
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# change password request
class ChangePasswordRequest(BaseModel):
    old_password: str = Field(description="Current password")
    new_password: str = Field(min_length=6, max_length=128, description="New password, min 6 chars")


# me update (name only)
class MeUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120, description="New display name", examples=["Aryan K"])
