"""API key scopes, policy, and request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ApiScope = Literal[
    "configs:create",
    "configs:revoke",
    "configs:logs",
    "analytics:read",
    "settings:write",
]

ALL_API_SCOPES: tuple[ApiScope, ...] = (
    "configs:create",
    "configs:revoke",
    "configs:logs",
    "analytics:read",
    "settings:write",
)

# Sub-admins never get settings:write even if listed on a key
FULL_ADMIN_ONLY_SCOPES: frozenset[str] = frozenset({"settings:write"})


class ApiKeyPolicy(BaseModel):
    """Full-admin controllable defaults for who may use which API features."""

    sub_admin_scopes: list[ApiScope] = Field(
        default_factory=lambda: [
            "configs:create",
            "configs:revoke",
            "configs:logs",
            "analytics:read",
        ]
    )
    admin_scopes: list[ApiScope] = Field(
        default_factory=lambda: list(ALL_API_SCOPES)
    )
    default_rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    max_rate_limit_per_minute: int = Field(default=600, ge=1, le=10_000)
    # Floor for analytics polling via API keys (must be ≥ 2.5s)
    analytics_min_interval_seconds: float = Field(default=2.5, ge=2.5, le=3600)
    max_keys_per_admin: int = Field(default=10, ge=1, le=100)

    @field_validator("sub_admin_scopes", "admin_scopes")
    @classmethod
    def unique_scopes(cls, value: list[ApiScope]) -> list[ApiScope]:
        seen: list[ApiScope] = []
        for s in value:
            if s not in seen:
                seen.append(s)
        return seen


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scopes: list[ApiScope] = Field(min_length=1)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    analytics_min_interval_seconds: float | None = Field(
        default=None, ge=2.5, le=3600
    )
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyPublic(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    rate_limit_per_minute: int
    analytics_min_interval_seconds: float
    enabled: bool
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None


class CreateApiKeyResponse(ApiKeyPublic):
    """Includes raw key once at creation time."""

    api_key: str


class ApiKeyPolicyUpdate(BaseModel):
    sub_admin_scopes: list[ApiScope] | None = None
    admin_scopes: list[ApiScope] | None = None
    default_rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    max_rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    analytics_min_interval_seconds: float | None = Field(
        default=None, ge=2.5, le=3600
    )
    max_keys_per_admin: int | None = Field(default=None, ge=1, le=100)
