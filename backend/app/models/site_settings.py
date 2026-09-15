from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_HEX = r"^#[0-9A-Fa-f]{6}$"
OvpnBindMode = Literal["lport", "nobind"]
OvpnRemoteMode = Literal["single", "remote_random"]
MAX_OVPN_REMOTE_RANDOM_PORTS = 4096


def _validate_hex(value: str) -> str:
    import re

    if not re.match(_HEX, value):
        raise ValueError("Color must be a hex value like #1e3a8a")
    return value.lower()


class SiteSettingsData(BaseModel):
    """Effective global site settings (env defaults + Mongo overrides)."""

    turnstile_enabled: bool = True
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""
    brand_name: str = "Popout"
    brand_product: str = "VPN"
    site_title: str = "Popout VPN Admin"
    brand_color_bg: str = "#0a0e14"
    brand_color_primary: str = "#1e3a8a"
    brand_color_accent: str = "#06b6d4"
    brand_color_accent_bright: str = "#67e8f9"

    # OpenVPN client-common style template (used when building .ovpn files)
    ovpn_remote_host: str = "vpn.example.com"
    ovpn_remote_mode: OvpnRemoteMode = "single"
    ovpn_remote_port: int = 1194
    ovpn_remote_port_min: int = 45000
    ovpn_remote_port_max: int = 45099
    ovpn_proto: str = "tcp4"
    ovpn_tun_mtu: int | None = 1400
    ovpn_mssfix: int | None = 1360
    ovpn_tcp_nodelay: bool = True
    ovpn_bind_mode: OvpnBindMode = "lport"
    ovpn_lport: int = 1
    ovpn_auth: str = "SHA512"
    ovpn_verb: int = 3
    ovpn_extra: str = ""

    # Connection security / WAN IP logging
    wan_ip_logging_enabled: bool = True
    unique_wan_ip_limit: int = 3
    unique_wan_ip_window_hours: int = 24
    # Analytics UI poll interval (seconds)
    analytics_refresh_seconds: float = 10.0

    # Attack monitor / pcap capture (full-admin)
    attack_pcap_retention_days: int = 7
    attack_pcap_packet_count: int = 4500
    attack_pcap_bpf: str = ""
    attack_discord_webhook_url: str = ""
    attack_discord_embed_json: str = ""
    attack_discord_max_attach_bytes: int = 8 * 1024 * 1024

    # Panel + utility zip backups (/root/backups)
    backup_interval_minutes: int = 30
    backup_keep_count: int = 3

    # Public Cloudflare hostname gate (in-app access code; VPN host stays ungated)
    public_gate_enabled: bool = False
    public_gate_password_hash: str = ""

    # Shared cert mode: one .ovpn / CN used by many simultaneous clients
    duplicate_cn_mode: bool = False

    # Per-client CAKE shaping on tun0 (10.8.0.0/24) — queue, don't hard-drop
    client_shape_enabled: bool = True
    client_shape_down_mbit: int = 23
    client_shape_up_mbit: int = 23

    # First-party API keys — role scopes & rate limits (full-admin policy)
    api_key_policy: dict | None = None

    # Cloudflare WAF sync (full-admin) — edge allowlist for /api/v1 API keys
    cloudflare_api_token: str = ""
    cloudflare_zone_id: str = ""
    cloudflare_waf_sync_enabled: bool = False
    cloudflare_waf_hosts: str = ""
    cloudflare_waf_last_sync: str | None = None

    updated_at: datetime | None = None


class SiteSettingsAdminResponse(BaseModel):
    turnstile_enabled: bool
    turnstile_site_key: str
    turnstile_secret_configured: bool
    brand_name: str
    brand_product: str
    site_title: str
    brand_color_bg: str
    brand_color_primary: str
    brand_color_accent: str
    brand_color_accent_bright: str
    ovpn_remote_host: str
    ovpn_remote_mode: OvpnRemoteMode
    ovpn_remote_port: int
    ovpn_remote_port_min: int
    ovpn_remote_port_max: int
    ovpn_proto: str
    ovpn_tun_mtu: int | None
    ovpn_mssfix: int | None
    ovpn_tcp_nodelay: bool
    ovpn_bind_mode: OvpnBindMode
    ovpn_lport: int
    ovpn_auth: str
    ovpn_verb: int
    ovpn_extra: str
    wan_ip_logging_enabled: bool
    unique_wan_ip_limit: int
    unique_wan_ip_window_hours: int
    analytics_refresh_seconds: float
    attack_pcap_retention_days: int
    attack_pcap_packet_count: int
    attack_pcap_bpf: str
    attack_discord_webhook_url: str
    attack_discord_embed_json: str
    attack_discord_max_attach_bytes: int
    backup_interval_minutes: int
    backup_keep_count: int
    public_gate_enabled: bool
    public_gate_password_configured: bool
    public_gate_username: str = ""
    duplicate_cn_mode: bool = False
    duplicate_cn_detected: bool = False
    client_shape_enabled: bool = True
    client_shape_down_mbit: int = 23
    client_shape_up_mbit: int = 23
    client_shape_live_down: str | None = None
    client_shape_live_up: str | None = None
    client_config_preview: str
    cloudflare_api_token_configured: bool = False
    cloudflare_zone_id: str = ""
    cloudflare_waf_sync_enabled: bool = False
    cloudflare_waf_hosts: str = ""
    cloudflare_waf_last_sync: str | None = None
    updated_at: datetime | None = None
    source: str = Field(description="'database' or 'environment'")


class UpdateSiteSettingsRequest(BaseModel):
    turnstile_enabled: bool | None = None
    turnstile_site_key: str | None = Field(default=None, max_length=256)
    turnstile_secret_key: str | None = Field(default=None, max_length=256)
    brand_name: str | None = Field(default=None, min_length=1, max_length=64)
    brand_product: str | None = Field(default=None, min_length=1, max_length=64)
    site_title: str | None = Field(default=None, min_length=1, max_length=128)
    brand_color_bg: str | None = None
    brand_color_primary: str | None = None
    brand_color_accent: str | None = None
    brand_color_accent_bright: str | None = None

    ovpn_remote_host: str | None = Field(default=None, min_length=1, max_length=255)
    ovpn_remote_mode: OvpnRemoteMode | None = None
    ovpn_remote_port: int | None = Field(default=None, ge=1, le=65535)
    ovpn_remote_port_min: int | None = Field(default=None, ge=1, le=65535)
    ovpn_remote_port_max: int | None = Field(default=None, ge=1, le=65535)
    ovpn_proto: str | None = Field(default=None, max_length=32)
    ovpn_tun_mtu: int | None = Field(default=None, ge=0, le=9000)
    ovpn_mssfix: int | None = Field(default=None, ge=0, le=9000)
    ovpn_tcp_nodelay: bool | None = None
    ovpn_bind_mode: OvpnBindMode | None = None
    ovpn_lport: int | None = Field(default=None, ge=0, le=65535)
    ovpn_auth: str | None = Field(default=None, max_length=64)
    ovpn_verb: int | None = Field(default=None, ge=0, le=11)
    ovpn_extra: str | None = Field(default=None, max_length=8000)

    wan_ip_logging_enabled: bool | None = None
    unique_wan_ip_limit: int | None = Field(default=None, ge=1, le=1000)
    unique_wan_ip_window_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    analytics_refresh_seconds: float | None = Field(default=None)
    attack_pcap_retention_days: int | None = Field(default=None, ge=1, le=365)
    attack_pcap_packet_count: int | None = Field(default=None, ge=100, le=1_000_000)
    attack_pcap_bpf: str | None = Field(default=None, max_length=512)
    attack_discord_webhook_url: str | None = Field(default=None, max_length=512)
    attack_discord_embed_json: str | None = Field(default=None, max_length=20000)
    attack_discord_max_attach_bytes: int | None = Field(
        default=None, ge=0, le=25 * 1024 * 1024
    )
    backup_interval_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    backup_keep_count: int | None = Field(default=None, ge=1, le=50)

    public_gate_enabled: bool | None = None
    public_gate_password: str | None = Field(default=None, max_length=128)
    duplicate_cn_mode: bool | None = None

    client_shape_enabled: bool | None = None
    client_shape_down_mbit: int | None = Field(default=None, ge=1, le=10000)
    client_shape_up_mbit: int | None = Field(default=None, ge=1, le=10000)

    cloudflare_api_token: str | None = Field(default=None, max_length=255)
    cloudflare_zone_id: str | None = Field(default=None, max_length=64)
    cloudflare_waf_sync_enabled: bool | None = None
    cloudflare_waf_hosts: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def ovpn_remote_range_valid(self) -> "UpdateSiteSettingsRequest":
        mode = self.ovpn_remote_mode
        port_min = self.ovpn_remote_port_min
        port_max = self.ovpn_remote_port_max
        if mode != "remote_random" and port_min is None and port_max is None:
            return self
        if mode == "remote_random" or port_min is not None or port_max is not None:
            lo = port_min if port_min is not None else 1
            hi = port_max if port_max is not None else lo
            if lo > hi:
                raise ValueError("Remote port range min must be <= max")
            count = hi - lo + 1
            if count > MAX_OVPN_REMOTE_RANDOM_PORTS:
                raise ValueError(
                    f"Remote port range spans {count} ports; "
                    f"maximum is {MAX_OVPN_REMOTE_RANDOM_PORTS}"
                )
        return self

    @field_validator("public_gate_password")
    @classmethod
    def public_gate_password_strength(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if len(value) < 8:
            raise ValueError("Public gate password must be at least 8 characters")
        return value

    @field_validator("analytics_refresh_seconds")
    @classmethod
    def refresh_must_be_allowed(cls, value: float | None) -> float | None:
        if value is None:
            return value
        allowed = {0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0}
        if float(value) not in allowed:
            raise ValueError(
                "analytics_refresh_seconds must be 0.25, 0.5, 1, 2.5, 5, 10, or 30"
            )
        return float(value)

    @field_validator(
        "brand_color_bg",
        "brand_color_primary",
        "brand_color_accent",
        "brand_color_accent_bright",
    )
    @classmethod
    def colors_must_be_hex(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_hex(value)
