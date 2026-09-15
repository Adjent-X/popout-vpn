from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.documents import ClientConfigStatus


ExpiryPreset = Literal[7, 30, 90, 365]


class ActiveSession(BaseModel):
    """One live OpenVPN session (duplicate-cn may have many per CN)."""

    vpn_ip: str | None = None
    wan_ip: str | None = None
    connected_since: datetime | None = None
    bytes_received: int = 0
    bytes_sent: int = 0


class CreateConfigRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    expiry_days: ExpiryPreset | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_one_expiry(self) -> "CreateConfigRequest":
        if self.expiry_days is None and self.expires_at is None:
            raise ValueError("Provide expiry_days or expires_at")
        if self.expiry_days is not None and self.expires_at is not None:
            raise ValueError("Provide only one of expiry_days or expires_at")
        return self


class UpdateExpiryRequest(BaseModel):
    expires_at: datetime


class ClientConfigResponse(BaseModel):
    id: str
    label: str
    client_name: str
    owner_admin_id: str
    created_at: datetime
    expires_at: datetime
    status: ClientConfigStatus
    cert_serial: str
    revoked_at: datetime | None = None
    vpn_ip: str | None = None
    last_wan_ip: str | None = None
    last_connected_at: datetime | None = None
    is_online: bool = False
    wan_ip_logging_enabled: bool | None = None
    warp_routing_enabled: bool = False
    session_count: int = 0
    active_sessions: list[ActiveSession] = Field(default_factory=list)


class CreateConfigResponse(ClientConfigResponse):
    ovpn: str
    wg_conf: str | None = None


class UpdateWanLoggingRequest(BaseModel):
    """None = inherit site default; True/False = force."""

    wan_ip_logging_enabled: bool | None = None


class UpdateWarpRoutingRequest(BaseModel):
    warp_routing_enabled: bool


class OrphanPkiClient(BaseModel):
    """CLI / installer client present on disk but missing from the panel DB."""

    client_name: str
    cert_serial: str
    revoked: bool
    has_key: bool
    vpn_ip: str | None = None


class ImportConfigsRequest(BaseModel):
    """Import existing PKI clients into the panel. Empty list = import all orphans."""

    client_names: list[str] = Field(default_factory=list)
    expiry_days: int = Field(default=3650, ge=1, le=3650)


class ImportConfigsResponse(BaseModel):
    imported: list[ClientConfigResponse]
    skipped: list[str]
    errors: dict[str, str] = Field(default_factory=dict)
