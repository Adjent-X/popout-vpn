from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from pydantic.functional_validators import BeforeValidator


def _validate_object_id(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if ObjectId.is_valid(value):
        return ObjectId(value)
    raise ValueError("Invalid ObjectId")


PyObjectId = Annotated[ObjectId, BeforeValidator(_validate_object_id)]


class MongoModel(BaseModel):
    """Base for MongoDB documents. Serializes ObjectId as str in JSON."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    @field_serializer("*", mode="wrap")
    def _serialize_object_ids(self, value: Any, handler: Any) -> Any:
        result = handler(value)
        if isinstance(result, ObjectId):
            return str(result)
        return result


class AdminRole(StrEnum):
    ADMIN = "admin"
    SUB_ADMIN = "sub_admin"


class ThemePreference(StrEnum):
    DARK = "dark"
    LIGHT = "light"


class ClientConfigStatus(StrEnum):
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AdminDocument(MongoModel):
    """Mongo collection: admins"""

    id: PyObjectId | None = Field(default=None, alias="_id")
    email: str
    hashed_password: str
    role: AdminRole = AdminRole.ADMIN
    theme: ThemePreference = ThemePreference.DARK
    # Max non-revoked VPN configs for sub-admins; None = unlimited (full admins)
    config_slot_limit: int | None = None
    locked: bool = False
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    created_at: datetime


class ClientConfigDocument(MongoModel):
    """Mongo collection: client_configs"""

    id: PyObjectId | None = Field(default=None, alias="_id")
    label: str
    client_name: str  # easy-rsa CN / issued cert basename
    owner_admin_id: PyObjectId
    created_at: datetime
    expires_at: datetime
    status: ClientConfigStatus = ClientConfigStatus.ACTIVE
    cert_serial: str
    revoked_at: datetime | None = None
    # Connection / IP telemetry (filled by metrics collector)
    vpn_ip: str | None = None
    last_wan_ip: str | None = None
    last_connected_at: datetime | None = None
    is_online: bool = False
    # None = inherit global site setting
    wan_ip_logging_enabled: bool | None = None
    # Full-admin only: route this client's 10.8.0.x via warp-routing ipset
    warp_routing_enabled: bool = False


class RegistrationTokenDocument(MongoModel):
    """Mongo collection: registration_tokens"""

    id: PyObjectId | None = Field(default=None, alias="_id")
    token: str
    role: AdminRole = AdminRole.ADMIN
    config_slot_limit: int | None = None
    note: str | None = None
    created_by: PyObjectId | None = None
    used: bool = False
    used_by: PyObjectId | None = None
    expires_at: datetime
    created_at: datetime
