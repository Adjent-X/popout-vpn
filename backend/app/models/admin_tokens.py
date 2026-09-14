from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.documents import AdminRole


class CreateRegistrationTokenRequest(BaseModel):
    role: AdminRole = AdminRole.ADMIN
    config_slot_limit: int | None = Field(default=None, ge=1, le=10_000)
    note: str | None = Field(default=None, max_length=200)
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 30)

    @model_validator(mode="after")
    def validate_slots_for_role(self) -> "CreateRegistrationTokenRequest":
        if self.role == AdminRole.SUB_ADMIN:
            if self.config_slot_limit is None:
                raise ValueError("config_slot_limit is required for sub-admin tokens")
        else:
            # Full admins are unlimited; ignore any accidental slot value
            self.config_slot_limit = None
        if self.note is not None:
            trimmed = self.note.strip()
            self.note = trimmed or None
        return self


class RegistrationTokenResponse(BaseModel):
    id: str
    token: str
    role: AdminRole
    config_slot_limit: int | None
    note: str | None
    used: bool
    used_by: str | None
    created_by: str | None
    expires_at: datetime
    created_at: datetime
