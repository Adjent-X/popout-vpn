"""Cloudflare zone provisioning: DNS, SSL, cache rules, and related settings.

Used by the installer and by Server settings so the admin portal hostname
works through Cloudflare. The OpenVPN tunnel is never proxied.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.core.config import get_settings
from app.services.cloudflare_waf import _cf_request, resolve_zone_id, sync_cloudflare_waf
from app.services.site_settings import get_site_settings, update_site_settings

logger = logging.getLogger(__name__)

POPOUT_CACHE_BYPASS = "Popout: bypass cache for app and API"
POPOUT_CACHE_STATIC = "Popout: cache Next.js static assets"


def _hosts_from_settings(settings_obj: Any, extra_hosts: list[str] | None = None) -> list[str]:
    hosts: list[str] = []
    raw = getattr(settings_obj, "cloudflare_waf_hosts", None) or ""
    hosts.extend(h.strip().lower() for h in re.split(r"[\s,]+", raw) if h and h.strip())
    env = get_settings()
    for url in (
        getattr(env, "PUBLIC_FRONTEND_URL", "") or "",
        getattr(env, "PUBLIC_CLOUDFLARE_FRONTEND_URL", "") or "",
    ):
        host = urlparse(url).hostname
        if host:
            hosts.append(host.lower())
    if extra_hosts:
        hosts.extend(h.strip().lower() for h in extra_hosts if h and h.strip())
    seen: set[str] = set()
    ordered: list[str] = []
    for host in hosts:
        if host not in seen:
            seen.add(host)
            ordered.append(host)
    return ordered


async def upsert_dns_record(
    token: str,
    zone_id: str,
    *,
    name: str,
    record_type: str,
    content: str,
    proxied: bool = True,
) -> dict[str, Any]:
    """Create or update an A/AAAA record for the admin hostname."""
    existing = await _cf_request(
        "GET",
        f"/zones/{zone_id}/dns_records?type={record_type}&name={name}&per_page=50",
        token,
    )
    records = existing.get("result") or []
    body = {
        "type": record_type,
        "name": name,
        "content": content,
        "ttl": 1,
        "proxied": proxied,
        "comment": "Popout VPN admin portal",
    }
    if records:
        rec_id = str(records[0]["id"])
        return await _cf_request(
            "PUT",
            f"/zones/{zone_id}/dns_records/{rec_id}",
            token,
            json_body=body,
        )
    return await _cf_request(
        "POST",
        f"/zones/{zone_id}/dns_records",
        token,
        json_body=body,
    )


async def apply_zone_settings(token: str, zone_id: str) -> dict[str, Any]:
    """Tune SSL, HTTPS, compression, and security for the admin portal."""
    patches: dict[str, Any] = {
        "ssl": "full",
        "always_use_https": "on",
        "min_tls_version": "1.2",
        "tls_1_3": "on",
        "brotli": "on",
        "http3": "on",
        "opportunistic_encryption": "on",
        "security_level": "medium",
        "browser_check": "on",
        "email_obfuscation": "on",
        "rocket_loader": "off",
        "development_mode": "off",
        "browser_cache_ttl": 0,
        "always_online": "off",
        "websockets": "on",
    }
    applied: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name, value in patches.items():
        try:
            await _cf_request(
                "PATCH",
                f"/zones/{zone_id}/settings/{name}",
                token,
                json_body={"value": value},
            )
            applied[name] = value
        except Exception as exc:
            errors[name] = str(exc)
            logger.warning("Cloudflare setting %s failed: %s", name, exc)
    return {"applied": applied, "errors": errors}


async def apply_cache_rules(token: str, zone_id: str, hosts: list[str]) -> dict[str, Any]:
    """Bypass HTML/API; cache hashed Next.js static assets at the edge."""
    host_expr = " or ".join(
        f'http.host eq "{h}"' for h in hosts if h
    ) or 'http.host eq "admin.example.com"'
    rules = [
        {
            "action": "set_cache_settings",
            "description": POPOUT_CACHE_BYPASS,
            "enabled": True,
            "expression": (
                f"({host_expr}) and ("
                'starts_with(http.request.uri.path, "/api/") or '
                'http.request.uri.path eq "/login" or '
                'starts_with(http.request.uri.path, "/login/") or '
                'http.request.uri.path eq "/register" or '
                'starts_with(http.request.uri.path, "/register/") or '
                'starts_with(http.request.uri.path, "/dashboard")'
                ")"
            ),
            "action_parameters": {"cache": False},
        },
        {
            "action": "set_cache_settings",
            "description": POPOUT_CACHE_STATIC,
            "enabled": True,
            "expression": (
                f"({host_expr}) and "
                'starts_with(http.request.uri.path, "/_next/static/")'
            ),
            "action_parameters": {
                "cache": True,
                "edge_ttl": {"mode": "override_origin", "default": 2678400},
                "browser_ttl": {"mode": "override_origin", "default": 2678400},
            },
        },
    ]
    path = f"/zones/{zone_id}/rulesets/phases/http_request_cache_settings/entrypoint"
    try:
        current = await _cf_request("GET", path, token)
    except Exception:
        current = {}
    existing = list((current.get("result") or {}).get("rules") or [])
    preserved = [
        {
            "action": r.get("action"),
            "description": r.get("description") or "",
            "enabled": bool(r.get("enabled", True)),
            "expression": r.get("expression") or "",
            **(
                {"action_parameters": r["action_parameters"]}
                if r.get("action_parameters")
                else {}
            ),
        }
        for r in existing
        if not str(r.get("description") or "").startswith("Popout:")
    ]
    merged = rules + preserved
    result = await _cf_request("PUT", path, token, json_body={"rules": merged})
    return {"ok": True, "rules": len(merged), "raw": result.get("success")}


async def provision_cloudflare_zone(
    *,
    token: str,
    domain: str,
    hostname: str,
    ipv4: str,
    ipv6: str = "",
    zone_id: str = "",
    sync_waf: bool = True,
) -> dict[str, Any]:
    """Full zone tune used by the installer: DNS + settings + cache + WAF."""
    hosts = [hostname.strip().lower()]
    zone_id = await resolve_zone_id(token, zone_id or None, hosts + [domain])
    dns_results: list[dict[str, Any]] = []
    if ipv4:
        dns_results.append(
            await upsert_dns_record(
                token, zone_id, name=hostname, record_type="A", content=ipv4, proxied=True
            )
        )
    if ipv6:
        dns_results.append(
            await upsert_dns_record(
                token,
                zone_id,
                name=hostname,
                record_type="AAAA",
                content=ipv6,
                proxied=True,
            )
        )
    settings_result = await apply_zone_settings(token, zone_id)
    cache_result = await apply_cache_rules(token, zone_id, hosts)
    waf_result: dict[str, Any] = {"skipped": True}
    if sync_waf:
        try:
            waf_result = await sync_cloudflare_waf(force=True)
        except Exception as exc:
            waf_result = {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "zone_id": zone_id,
        "hostname": hostname,
        "dns": len(dns_results),
        "settings": settings_result,
        "cache": cache_result,
        "waf": waf_result,
    }


async def sync_cloudflare_zone(*, force: bool = False) -> dict[str, Any]:
    """Re-apply DNS/cache/WAF from saved Server settings."""
    settings, _ = await get_site_settings(use_cache=False)
    token = (getattr(settings, "cloudflare_api_token", None) or "").strip()
    enabled = bool(getattr(settings, "cloudflare_waf_sync_enabled", False))
    if not enabled and not force:
        return {"ok": False, "skipped": True, "reason": "sync disabled"}
    if not token:
        return {"ok": False, "skipped": True, "reason": "no Cloudflare API token"}

    hosts = _hosts_from_settings(settings)
    if not hosts:
        return {"ok": False, "skipped": True, "reason": "no portal hostname"}

    env = get_settings()
    ipv4 = (getattr(env, "OPENVPN_SERVER_HOST", None) or "").strip()
    # OPENVPN_SERVER_HOST may be a DNS name; skip A upsert unless it looks like an IP
    if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", ipv4):
        ipv4 = ""

    zone_id = await resolve_zone_id(
        token, getattr(settings, "cloudflare_zone_id", None), hosts
    )
    hostname = hosts[0]
    dns_ok = False
    if ipv4:
        await upsert_dns_record(
            token, zone_id, name=hostname, record_type="A", content=ipv4, proxied=True
        )
        dns_ok = True
    settings_result = await apply_zone_settings(token, zone_id)
    cache_result = await apply_cache_rules(token, zone_id, hosts)
    waf_result = await sync_cloudflare_waf(force=True)
    await update_site_settings({"cloudflare_zone_id": zone_id})
    return {
        "ok": True,
        "zone_id": zone_id,
        "hosts": hosts,
        "dns_updated": dns_ok,
        "settings": settings_result,
        "cache": cache_result,
        "waf": waf_result,
    }
