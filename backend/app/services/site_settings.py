"""Runtime global site settings stored in Mongo (env provides defaults)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.db import get_db, is_connected
from app.models.site_settings import SiteSettingsData
from app.services.ovpn_template import (
    build_client_common_text,
    load_ovpn_defaults_from_disk,
    try_write_client_common_file,
)

logger = logging.getLogger(__name__)

SITE_SETTINGS_ID = "global"

_cache: SiteSettingsData | None = None
_cache_source: str = "environment"


def _env_defaults() -> SiteSettingsData:
    s = get_settings()
    ovpn = load_ovpn_defaults_from_disk()
    from app.services.openvpn_flags import detect_duplicate_cn

    return SiteSettingsData(
        turnstile_enabled=s.TURNSTILE_ENABLED,
        turnstile_site_key=s.TURNSTILE_SITE_KEY,
        turnstile_secret_key=s.TURNSTILE_SECRET_KEY,
        brand_name=s.BRAND_NAME,
        brand_product=s.BRAND_PRODUCT,
        site_title=s.SITE_TITLE,
        brand_color_bg=s.BRAND_COLOR_BG,
        brand_color_primary=s.BRAND_COLOR_PRIMARY,
        brand_color_accent=s.BRAND_COLOR_ACCENT,
        brand_color_accent_bright=s.BRAND_COLOR_ACCENT_BRIGHT,
        ovpn_remote_host=ovpn.get("ovpn_remote_host", s.OPENVPN_SERVER_HOST),
        ovpn_remote_mode=ovpn.get("ovpn_remote_mode", "single"),
        ovpn_remote_port=ovpn.get("ovpn_remote_port", s.OPENVPN_SERVER_PORT),
        ovpn_remote_port_min=ovpn.get("ovpn_remote_port_min", 45000),
        ovpn_remote_port_max=ovpn.get("ovpn_remote_port_max", 45099),
        ovpn_proto=ovpn.get("ovpn_proto", s.OPENVPN_PROTO),
        ovpn_udp_enabled=ovpn.get("ovpn_udp_enabled", True),
        ovpn_tcp_enabled=ovpn.get("ovpn_tcp_enabled", True),
        ovpn_udp_port=ovpn.get("ovpn_udp_port", 1194),
        ovpn_tcp_port=ovpn.get("ovpn_tcp_port", 1195),
        vpn_bind_ip="10.255.255.1",
        wg_enabled=True,
        wg_listen_port=51820,
        wg_endpoint_host="",
        wg_dns="1.1.1.1,1.0.0.1",
        wg_allowed_ips="0.0.0.0/0,::/0",
        wg_mtu=1420,
        wg_keepalive=25,
        ovpn_tun_mtu=ovpn.get("ovpn_tun_mtu", 1400),
        ovpn_mssfix=ovpn.get("ovpn_mssfix", 1360),
        ovpn_tcp_nodelay=ovpn.get("ovpn_tcp_nodelay", True),
        ovpn_bind_mode=ovpn.get("ovpn_bind_mode", "lport"),
        ovpn_lport=ovpn.get("ovpn_lport", 1),
        ovpn_auth=ovpn.get("ovpn_auth", "SHA512"),
        ovpn_verb=ovpn.get("ovpn_verb", 3),
        ovpn_extra=ovpn.get("ovpn_extra", ""),
        duplicate_cn_mode=detect_duplicate_cn(),
        updated_at=None,
    )


def invalidate_site_settings_cache() -> None:
    global _cache, _cache_source
    _cache = None
    _cache_source = "environment"


def _merge_doc(defaults: SiteSettingsData, doc: dict[str, Any]) -> SiteSettingsData:
    data = defaults.model_dump()
    for key in list(data.keys()):
        if key == "updated_at":
            continue
        if key in doc and doc[key] is not None:
            data[key] = doc[key]
        # Allow explicit null for optional MTU / mssfix
        if key in ("ovpn_tun_mtu", "ovpn_mssfix") and key in doc:
            data[key] = doc[key]
    data["updated_at"] = doc.get("updated_at")
    return SiteSettingsData(**data)


async def ensure_site_settings_seeded() -> None:
    """Create the singleton document from env on first run (if missing)."""
    if not is_connected():
        return
    db = get_db()
    existing = await db.site_settings.find_one({"_id": SITE_SETTINGS_ID})
    if existing is None:
        defaults = _env_defaults()
        now = datetime.now(timezone.utc)
        payload = defaults.model_dump()
        payload["_id"] = SITE_SETTINGS_ID
        payload["updated_at"] = now
        await db.site_settings.insert_one(payload)
        logger.info("Seeded site_settings from environment / client-common defaults")
        invalidate_site_settings_cache()
        return

    # One-time backfill: adopt server.conf duplicate-cn when unset
    if "duplicate_cn_mode" not in existing:
        from app.services.openvpn_flags import detect_duplicate_cn

        detected = detect_duplicate_cn()
        await db.site_settings.update_one(
            {"_id": SITE_SETTINGS_ID},
            {"$set": {"duplicate_cn_mode": detected}},
        )
        logger.info("Backfilled duplicate_cn_mode=%s from server.conf", detected)
        invalidate_site_settings_cache()


async def get_site_settings(*, use_cache: bool = True) -> tuple[SiteSettingsData, str]:
    global _cache, _cache_source

    if use_cache and _cache is not None:
        return _cache, _cache_source

    defaults = _env_defaults()
    if not is_connected():
        _cache = defaults
        _cache_source = "environment"
        return defaults, "environment"

    db = get_db()
    doc = await db.site_settings.find_one({"_id": SITE_SETTINGS_ID})
    if doc is None:
        _cache = defaults
        _cache_source = "environment"
        return defaults, "environment"

    merged = _merge_doc(defaults, doc)
    _cache = merged
    _cache_source = "database"
    return merged, "database"


async def update_site_settings(updates: dict[str, Any]) -> tuple[SiteSettingsData, str]:
    if not is_connected():
        raise RuntimeError("Database unavailable")

    db = get_db()
    current, _ = await get_site_settings(use_cache=False)
    now = datetime.now(timezone.utc)

    payload = current.model_dump()
    for key, value in updates.items():
        if key in ("turnstile_secret_key", "cloudflare_api_token") and value == "":
            # Empty means "do not change"
            continue
        if key == "public_gate_password":
            # Write-only; hash is applied by the API layer
            continue
        if key in ("ovpn_tun_mtu", "ovpn_mssfix") and value == 0:
            payload[key] = None
            continue
        if value is None and key not in ("ovpn_tun_mtu", "ovpn_mssfix"):
            continue
        payload[key] = value
    payload["updated_at"] = now

    to_set = {k: v for k, v in payload.items() if k != "_id"}
    await db.site_settings.update_one(
        {"_id": SITE_SETTINGS_ID},
        {"$set": to_set},
        upsert=True,
    )
    invalidate_site_settings_cache()
    data, source = await get_site_settings(use_cache=False)

    common_text = build_client_common_text(data)
    if try_write_client_common_file(common_text):
        logger.info("Synced client-common.txt from site settings")
    else:
        logger.warning(
            "Could not write client-common.txt; portal template still used for new .ovpn files"
        )

    return data, source
