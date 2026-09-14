from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.documents import ThemePreference


class UpdateThemeRequest(BaseModel):
    theme: ThemePreference


class UpdateCredentialsRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_email: EmailStr | None = None
    new_password: str | None = Field(default=None, min_length=12, max_length=128)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateCredentialsRequest":
        if self.new_email is None and self.new_password is None:
            raise ValueError("Provide a new email and/or a new password")
        return self
