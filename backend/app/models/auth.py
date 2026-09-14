from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.documents import ThemePreference


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    registration_token: str = Field(min_length=16, max_length=256)
    turnstile_token: str = Field(default="", max_length=2048)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    turnstile_token: str = Field(default="", max_length=2048)
    keep_signed_in: bool = False


class AdminPublic(BaseModel):
    id: str
    email: EmailStr
    role: str
    theme: ThemePreference
    config_slot_limit: int | None = None
    config_slots_used: int = 0
    locked: bool = False
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    admin: AdminPublic


class UpdateAdminAccountRequest(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)
    config_slot_limit: int | None = Field(default=None, ge=1, le=10_000)
    clear_slot_limit: bool = False
    locked: bool | None = None
