from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_db, require_full_admin
from app.models.site_settings import (
    SiteSettingsAdminResponse,
    UpdateSiteSettingsRequest,
)
from app.services.ovpn_template import build_client_common_text
from app.services.site_settings import get_site_settings, update_site_settings
from app.services.attacks import DEFAULT_ATTACK_EMBED_JSON
from app.services.bpf_validate import BpfSyntaxError, validate_bpf_filter
from app.services.openvpn_flags import detect_duplicate_cn

router = APIRouter(prefix="/api/site-settings", tags=["site-settings"])


def _to_admin_response(data, source: str) -> SiteSettingsAdminResponse:
    wg_installed = False
    servers: dict = {}
    try:
        from app.services.vpn_servers import server_status
        from app.services.wireguard import wg_available

        wg_installed = wg_available()
        servers = server_status(data)
    except Exception:
        pass
    return SiteSettingsAdminResponse(
        turnstile_enabled=data.turnstile_enabled,
        turnstile_site_key=data.turnstile_site_key,
        turnstile_secret_configured=bool(data.turnstile_secret_key.strip()),
        brand_name=data.brand_name,
        brand_product=data.brand_product,
        site_title=data.site_title,
        brand_color_bg=data.brand_color_bg,
        brand_color_primary=data.brand_color_primary,
        brand_color_accent=data.brand_color_accent,
        brand_color_accent_bright=data.brand_color_accent_bright,
        ovpn_remote_host=data.ovpn_remote_host,
        ovpn_remote_mode=data.ovpn_remote_mode,
        ovpn_remote_port=data.ovpn_remote_port,
        ovpn_remote_port_min=data.ovpn_remote_port_min,
        ovpn_remote_port_max=data.ovpn_remote_port_max,
        ovpn_proto=data.ovpn_proto,
        ovpn_udp_enabled=bool(getattr(data, "ovpn_udp_enabled", True)),
        ovpn_tcp_enabled=bool(getattr(data, "ovpn_tcp_enabled", True)),
        ovpn_udp_port=int(getattr(data, "ovpn_udp_port", 1194) or 1194),
        ovpn_tcp_port=int(getattr(data, "ovpn_tcp_port", 1195) or 1195),
        vpn_bind_ip=getattr(data, "vpn_bind_ip", None) or "10.255.255.1",
        wg_enabled=bool(getattr(data, "wg_enabled", True)),
        wg_listen_port=int(getattr(data, "wg_listen_port", 51820) or 51820),
        wg_endpoint_host=getattr(data, "wg_endpoint_host", None) or "",
        wg_dns=getattr(data, "wg_dns", None) or "1.1.1.1,1.0.0.1",
        wg_allowed_ips=getattr(data, "wg_allowed_ips", None) or "0.0.0.0/0,::/0",
        wg_mtu=int(getattr(data, "wg_mtu", 1420) or 1420),
        wg_keepalive=int(getattr(data, "wg_keepalive", 25) or 25),
        wireguard_installed=wg_installed,
        vpn_servers=servers,
        ovpn_tun_mtu=data.ovpn_tun_mtu,
        ovpn_mssfix=data.ovpn_mssfix,
        ovpn_tcp_nodelay=data.ovpn_tcp_nodelay,
        ovpn_bind_mode=data.ovpn_bind_mode,
        ovpn_lport=data.ovpn_lport,
        ovpn_auth=data.ovpn_auth,
        ovpn_verb=data.ovpn_verb,
        ovpn_extra=data.ovpn_extra or "",
        wan_ip_logging_enabled=data.wan_ip_logging_enabled,
        unique_wan_ip_limit=data.unique_wan_ip_limit,
        unique_wan_ip_window_hours=data.unique_wan_ip_window_hours,
        analytics_refresh_seconds=data.analytics_refresh_seconds,
        attack_pcap_retention_days=data.attack_pcap_retention_days,
        attack_pcap_packet_count=data.attack_pcap_packet_count,
        attack_pcap_bpf=data.attack_pcap_bpf or "",
        attack_discord_webhook_url=data.attack_discord_webhook_url or "",
        attack_discord_embed_json=(
            data.attack_discord_embed_json or DEFAULT_ATTACK_EMBED_JSON
        ),
        attack_discord_max_attach_bytes=int(
            data.attack_discord_max_attach_bytes or 8 * 1024 * 1024
        ),
        backup_interval_minutes=int(data.backup_interval_minutes or 30),
        backup_keep_count=int(data.backup_keep_count or 3),
        public_gate_enabled=bool(data.public_gate_enabled),
        public_gate_password_configured=bool(
            (data.public_gate_password_hash or "").strip()
        ),
        public_gate_username="",
        duplicate_cn_mode=bool(data.duplicate_cn_mode),
        duplicate_cn_detected=detect_duplicate_cn(),
        client_shape_enabled=bool(data.client_shape_enabled),
        client_shape_down_mbit=int(data.client_shape_down_mbit or 23),
        client_shape_up_mbit=int(data.client_shape_up_mbit or 23),
        client_shape_live_down=None,
        client_shape_live_up=None,
        client_config_preview=build_client_common_text(data),
        cloudflare_api_token_configured=bool(
            (getattr(data, "cloudflare_api_token", None) or "").strip()
        ),
        cloudflare_zone_id=(getattr(data, "cloudflare_zone_id", None) or ""),
        cloudflare_waf_sync_enabled=bool(
            getattr(data, "cloudflare_waf_sync_enabled", False)
        ),
        cloudflare_waf_hosts=(getattr(data, "cloudflare_waf_hosts", None) or ""),
        cloudflare_waf_last_sync=getattr(data, "cloudflare_waf_last_sync", None),
        updated_at=data.updated_at,
        source=source,
    )


def _with_live_shape(resp: SiteSettingsAdminResponse) -> SiteSettingsAdminResponse:
    try:
        from app.services.vpn_shape import get_shaping_status

        live = get_shaping_status()
        resp.client_shape_live_down = (
            str(live.get("download")) if live.get("download") else None
        )
        resp.client_shape_live_up = (
            str(live.get("upload")) if live.get("upload") else None
        )
    except Exception:
        pass
    return resp


@router.get("", response_model=SiteSettingsAdminResponse)
async def read_site_settings(
    admin: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> SiteSettingsAdminResponse:
    _ = admin, db
    data, source = await get_site_settings(use_cache=False)
    return _with_live_shape(_to_admin_response(data, source))


class ValidateBpfRequest(BaseModel):
    bpf: str = Field(default="", max_length=512)


class ValidateBpfResponse(BaseModel):
    ok: bool = True
    message: str = "BPF filter is valid"


@router.post("/validate-bpf", response_model=ValidateBpfResponse)
async def validate_bpf_endpoint(
    body: ValidateBpfRequest,
    admin: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> ValidateBpfResponse:
    _ = admin, db
    try:
        validate_bpf_filter(body.bpf)
    except BpfSyntaxError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    msg = (
        "BPF filter is valid"
        if (body.bpf or "").strip()
        else "Empty filter (capture all traffic) is valid"
    )
    return ValidateBpfResponse(ok=True, message=msg)


class TestAttackWebhookRequest(BaseModel):
    webhook_url: str | None = Field(default=None, max_length=512)
    embed_json: str | None = Field(default=None, max_length=32_768)


class TestAttackWebhookResponse(BaseModel):
    ok: bool = True
    message: str
    service: str = ""


@router.post("/test-attack-webhook", response_model=TestAttackWebhookResponse)
async def test_attack_webhook_endpoint(
    body: TestAttackWebhookRequest,
    admin: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> TestAttackWebhookResponse:
    _ = admin, db
    from app.services.attacks import send_test_attack_webhook

    try:
        result = await send_test_attack_webhook(
            webhook_url=body.webhook_url,
            embed_json=body.embed_json,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Webhook test failed: {exc}",
        ) from exc
    return TestAttackWebhookResponse(
        ok=True,
        message=str(result.get("message") or "Test webhook sent"),
        service=str(result.get("service") or ""),
    )


@router.patch("", response_model=SiteSettingsAdminResponse)
async def patch_site_settings(
    body: UpdateSiteSettingsRequest,
    admin: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> SiteSettingsAdminResponse:
    _ = admin, db
    updates = body.model_dump(exclude_unset=True)

    if "attack_pcap_bpf" in updates:
        try:
            validate_bpf_filter(str(updates.get("attack_pcap_bpf") or ""))
        except BpfSyntaxError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    current_settings, _ = await get_site_settings(use_cache=False)

    if updates.get("turnstile_enabled") is True:
        site_key = updates.get("turnstile_site_key", current_settings.turnstile_site_key)
        secret = updates.get("turnstile_secret_key") or current_settings.turnstile_secret_key
        if not (site_key or "").strip() or not (secret or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Turnstile site key and secret are required when enabling captcha",
            )

    gate_password_plain: str | None = None
    if "public_gate_password" in updates:
        gate_password_plain = updates.pop("public_gate_password") or None
        if gate_password_plain:
            from app.core.security import hash_password

            updates["public_gate_password_hash"] = hash_password(gate_password_plain)
        # Empty string means leave existing password unchanged

    will_enable_gate = updates.get(
        "public_gate_enabled", current_settings.public_gate_enabled
    )
    has_gate_password = bool(
        (gate_password_plain or current_settings.public_gate_password_hash or "").strip()
    )
    if will_enable_gate and not has_gate_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set a public gate password before enabling the Cloudflare password gate",
        )

    try:
        data, source = await update_site_settings(updates)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if (
        "public_gate_enabled" in updates
        or gate_password_plain
        or "public_gate_password_hash" in updates
    ):
        from app.services.public_gate import sync_public_access_gate

        try:
            # Client modal gate only — never enable nginx basic auth
            sync_public_access_gate(enabled=False)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to sync public Cloudflare password gate"
            )

    if "analytics_refresh_seconds" in updates:
        from app.services.scheduler import reschedule_analytics_jobs

        reschedule_analytics_jobs(data.analytics_refresh_seconds, run_soon=True)

    if "backup_interval_minutes" in updates:
        from app.services.scheduler import reschedule_backup_job

        reschedule_backup_job(data.backup_interval_minutes, run_soon=False)

    if "backup_keep_count" in updates:
        try:
            from app.services.backup import prune_backups

            prune_backups(int(data.backup_keep_count or 3))
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Failed to prune backups after settings change")

    if any(
        k in updates
        for k in (
            "attack_pcap_retention_days",
            "attack_pcap_packet_count",
            "attack_pcap_bpf",
            "attack_discord_webhook_url",
            "attack_discord_embed_json",
            "attack_discord_max_attach_bytes",
        )
    ):
        from app.services.attacks import try_restart_attacks_service, write_attacks_conf

        try:
            await write_attacks_conf()
            try_restart_attacks_service()
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to sync attack monitor config"
            )

    if any(
        k in updates
        for k in (
            "client_shape_enabled",
            "client_shape_down_mbit",
            "client_shape_up_mbit",
        )
    ):
        try:
            from app.services.vpn_shape import apply_client_shaping

            apply_client_shaping(
                enabled=bool(data.client_shape_enabled),
                down_mbit=int(data.client_shape_down_mbit or 23),
                up_mbit=int(data.client_shape_up_mbit or 23),
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to apply client traffic shaping"
            )

    if any(
        k in updates
        for k in (
            "cloudflare_api_token",
            "cloudflare_zone_id",
            "cloudflare_waf_sync_enabled",
            "cloudflare_waf_hosts",
        )
    ):
        try:
            from datetime import datetime, timezone

            from app.services.cloudflare_waf import sync_cloudflare_waf

            result = await sync_cloudflare_waf(force=True)
            sync_note = json_dumps_safe(result)
            await update_site_settings(
                {
                    "cloudflare_waf_last_sync": (
                        f"{datetime.now(timezone.utc).isoformat()} {sync_note}"
                    )[:500]
                }
            )
            data, source = await get_site_settings(use_cache=False)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("Cloudflare WAF sync after settings")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Saved settings but Cloudflare sync failed: {exc}",
            ) from exc

    vpn_unit_keys = (
        "ovpn_udp_enabled",
        "ovpn_tcp_enabled",
        "wg_enabled",
        "ovpn_udp_port",
        "ovpn_tcp_port",
        "wg_listen_port",
        "vpn_bind_ip",
    )
    vpn_param_keys = vpn_unit_keys + (
        "wg_endpoint_host",
        "wg_dns",
        "wg_allowed_ips",
        "wg_mtu",
        "wg_keepalive",
        "ovpn_remote_host",
        "ovpn_remote_port_min",
        "ovpn_remote_port_max",
    )
    if any(k in updates for k in vpn_param_keys):
        try:
            import asyncio

            from app.services.vpn_servers import apply_vpn_servers

            touch_units = any(k in updates for k in vpn_unit_keys)
            await asyncio.to_thread(
                apply_vpn_servers, data, touch_units=touch_units
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to apply VPN server enable/disable / DNAT"
            )

    return _with_live_shape(_to_admin_response(data, source))


def json_dumps_safe(value: object) -> str:
    import json

    try:
        return json.dumps(value, default=str)
    except Exception:
        return str(value)


class CloudflareWafSyncResponse(BaseModel):
    ok: bool
    detail: dict = Field(default_factory=dict)


@router.post("/cloudflare-waf-sync", response_model=CloudflareWafSyncResponse)
async def trigger_cloudflare_waf_sync(
    admin: dict = Depends(require_full_admin),
) -> CloudflareWafSyncResponse:
    _ = admin
    from datetime import datetime, timezone

    from app.services.cloudflare_waf import sync_cloudflare_waf

    try:
        result = await sync_cloudflare_waf(force=True)
        await update_site_settings(
            {
                "cloudflare_waf_last_sync": (
                    f"{datetime.now(timezone.utc).isoformat()} {json_dumps_safe(result)}"
                )[:500]
            }
        )
        return CloudflareWafSyncResponse(ok=bool(result.get("ok")), detail=result)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/cloudflare-zone-sync", response_model=CloudflareWafSyncResponse)
async def trigger_cloudflare_zone_sync(
    admin: dict = Depends(require_full_admin),
) -> CloudflareWafSyncResponse:
    """Re-apply DNS, SSL, cache rules, and WAF for the admin portal hostname."""
    _ = admin
    from datetime import datetime, timezone

    from app.services.cloudflare_zone import sync_cloudflare_zone

    try:
        result = await sync_cloudflare_zone(force=True)
        await update_site_settings(
            {
                "cloudflare_waf_last_sync": (
                    f"{datetime.now(timezone.utc).isoformat()} {json_dumps_safe(result)}"
                )[:500]
            }
        )
        return CloudflareWafSyncResponse(ok=bool(result.get("ok")), detail=result)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
