"""Cloudflare WAF sync: allowlist valid API keys at the edge for /api/v1."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.db import get_db, is_connected
from app.services.site_settings import get_site_settings

logger = logging.getLogger(__name__)

POPOUT_RULE_PREFIX = "Popout:"
API_KEYS_RULE_DESC = "Popout: /api/v1 allowlist valid API keys"
CF_API = "https://api.cloudflare.com/client/v4"

# Common hosting/cloud ASNs — challenged for panel browser traffic (not /api/v1 allowlisted keys)
HOSTING_ASNS: tuple[int, ...] = (
    16509, 14618, 8987, 15169, 396982, 36040, 8075, 3598, 14061, 62567,
    20473, 63949, 16276, 24940, 51167, 213230, 8560, 12876, 31898, 45102,
    37963, 136907, 54825, 9009, 212238, 60068, 40676, 132203, 55933, 20860,
    201011, 197540, 53667, 8100, 46562, 63018, 35916, 26496, 46606, 36351,
    3223, 50340, 49505, 57043, 62240, 25820, 29802, 55286, 18779, 19437,
    7203, 30633, 28753, 60781,
)


def _fernet() -> Fernet:
    raw = get_settings().JWT_SECRET_KEY.encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(raw_key: str) -> str:
    return _fernet().encrypt(raw_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(ciphertext: str) -> str | None:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def _cf_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _cf_request(
    method: str,
    path: str,
    token: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{CF_API}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.request(
            method, url, headers=_cf_headers(token), json=json_body
        )
    try:
        data = res.json()
    except Exception as exc:
        raise RuntimeError(f"Cloudflare API non-JSON ({res.status_code})") from exc
    if res.status_code >= 400 or not data.get("success", True):
        errs = data.get("errors") or [{"message": res.text[:300]}]
        msg = "; ".join(
            str(e.get("message") or e) for e in errs if isinstance(e, dict)
        ) or res.text[:300]
        raise RuntimeError(f"Cloudflare API error: {msg}")
    return data


def _quote_cf(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _panel_hosts_expr(hosts: list[str]) -> str:
    cleaned = [h.strip().lower() for h in hosts if h and h.strip()]
    if not cleaned:
        return 'http.host eq "invalid.invalid"'
    inner = " ".join(_quote_cf(h) for h in cleaned)
    return f"http.host in {{{inner}}}"


def _api_key_allow_expr(hosts: list[str], raw_keys: list[str]) -> str:
    host_expr = _panel_hosts_expr(hosts)
    base = (
        f"({host_expr}) and "
        f'(starts_with(http.request.uri.path, "/api/v1/"))'
    )
    if not raw_keys:
        # No valid keys → block all machine API traffic at the edge
        return base

    # Cap to keep expression under CF size limits
    keys = raw_keys[:40]
    x_api = " ".join(_quote_cf(k) for k in keys)
    bearers = " ".join(_quote_cf(f"Bearer {k}") for k in keys)
    allow = (
        f"(any(http.request.headers[\"x-api-key\"][*] in {{{x_api}}}) or "
        f"any(http.request.headers[\"authorization\"][*] in {{{bearers}}}))"
    )
    return f"{base} and not {allow}"


def _static_popout_rules(hosts: list[str]) -> list[dict[str, Any]]:
    host_expr = _panel_hosts_expr(hosts)
    asn_list = " ".join(str(a) for a in HOSTING_ASNS)
    host_ors = " or ".join(
        f"http.host eq {_quote_cf(h.strip().lower())}"
        for h in hosts
        if h and h.strip()
    ) or 'http.host eq "invalid.invalid"'
    return [
        {
            "action": "block",
            "description": f"{POPOUT_RULE_PREFIX} block exploit / scanner paths",
            "enabled": True,
            "expression": (
                f"({host_expr}) and ("
                'http.request.uri.path contains "/wp-" or '
                'http.request.uri.path contains "/wordpress" or '
                'http.request.uri.path contains "/xmlrpc.php" or '
                'http.request.uri.path contains ".php" or '
                'http.request.uri.path contains "/.env" or '
                'http.request.uri.path contains "/.git" or '
                'http.request.uri.path contains "/vendor/phpunit" or '
                'http.request.uri.path contains "/actuator" or '
                'http.request.uri.path contains "/cgi-bin" or '
                'http.request.uri.path contains "/phpmyadmin"'
                ")"
            ),
        },
        {
            "action": "managed_challenge",
            "description": f"{POPOUT_RULE_PREFIX} challenge non-US clients",
            "enabled": True,
            "expression": (
                f"({host_expr}) and "
                'not (starts_with(http.request.uri.path, "/api/v1/")) and '
                'not (ip.geoip.country in {"US" "PR" "VI" "GU" "AS" "MP"})'
            ),
        },
        {
            "action": "managed_challenge",
            "description": f"{POPOUT_RULE_PREFIX} challenge non-residential / hosting ASN",
            "enabled": True,
            "expression": (
                f"({host_expr}) and "
                'not (starts_with(http.request.uri.path, "/api/v1/")) and '
                f"(ip.src.asnum in {{{asn_list}}})"
            ),
        },
        {
            "action": "managed_challenge",
            "description": f"{POPOUT_RULE_PREFIX} challenge elevated threat score",
            "enabled": True,
            "expression": (
                f"({host_expr}) and "
                'not (starts_with(http.request.uri.path, "/api/v1/")) and '
                "(cf.threat_score ge 5)"
            ),
        },
        {
            "action": "block",
            "description": f"{POPOUT_RULE_PREFIX} landing page non-GET exclude panel",
            "enabled": True,
            "expression": (
                '(http.request.method ne "GET") and not '
                f"({host_ors})"
            ),
        },
    ]


async def _load_raw_api_keys() -> list[str]:
    if not is_connected():
        return []
    db = get_db()
    cursor = db.api_keys.find({"enabled": True}, {"key_ciphertext": 1, "expires_at": 1})
    keys: list[str] = []
    from app.services.api_keys import is_key_expired

    async for doc in cursor:
        if is_key_expired(doc):
            continue
        ct = doc.get("key_ciphertext")
        if not ct:
            continue
        raw = decrypt_api_key(str(ct))
        if raw and raw.startswith("pk_live_"):
            keys.append(raw)
    return keys


async def resolve_zone_id(token: str, zone_id: str | None, hosts: list[str]) -> str:
    if zone_id and zone_id.strip():
        return zone_id.strip()
    # Infer zone from first host (e.g. admin.example.com → example.com)
    host = next((h.strip().lower() for h in hosts if h.strip()), "")
    parts = host.split(".")
    if len(parts) >= 2:
        candidates = [".".join(parts[-2:]), host]
    else:
        candidates = [host]
    data = await _cf_request("GET", "/zones?per_page=50", token)
    zones = data.get("result") or []
    by_name = {str(z.get("name") or "").lower(): str(z.get("id")) for z in zones}
    for name in candidates:
        if name in by_name:
            return by_name[name]
    raise RuntimeError(
        "Could not resolve Cloudflare zone id — set it explicitly in Server settings"
    )


async def _get_custom_firewall_ruleset_id(token: str, zone_id: str) -> str:
    data = await _cf_request("GET", f"/zones/{zone_id}/rulesets", token)
    for item in data.get("result") or []:
        if item.get("phase") == "http_request_firewall_custom" and item.get("kind") == "zone":
            return str(item["id"])
    # Create entrypoint if missing
    created = await _cf_request(
        "POST",
        f"/zones/{zone_id}/rulesets",
        token,
        json_body={
            "name": "default",
            "kind": "zone",
            "phase": "http_request_firewall_custom",
            "rules": [],
        },
    )
    return str(created["result"]["id"])


async def sync_cloudflare_waf(*, force: bool = False) -> dict[str, Any]:
    """Push Popout WAF rules + dynamic /api/v1 API-key allowlist to Cloudflare."""
    settings, _ = await get_site_settings(use_cache=False)
    token = (getattr(settings, "cloudflare_api_token", None) or "").strip()
    enabled = bool(getattr(settings, "cloudflare_waf_sync_enabled", False))
    if not enabled and not force:
        return {"ok": False, "skipped": True, "reason": "sync disabled"}
    if not token:
        return {"ok": False, "skipped": True, "reason": "no Cloudflare API token"}

    hosts_raw = getattr(settings, "cloudflare_waf_hosts", None) or ""
    hosts = [h.strip() for h in re.split(r"[\s,]+", hosts_raw) if h.strip()]
    if not hosts:
        # Default to public frontend host from env
        from urllib.parse import urlparse

        env = get_settings()
        for url in (
            getattr(env, "PUBLIC_FRONTEND_URL", "") or "",
            getattr(env, "PUBLIC_CLOUDFLARE_FRONTEND_URL", "") or "",
        ):
            host = urlparse(url).hostname
            if host:
                hosts.append(host)
        hosts = list(dict.fromkeys(hosts))
    if not hosts:
        hosts = ["admin.example.com"]

    zone_id = await resolve_zone_id(
        token,
        getattr(settings, "cloudflare_zone_id", None),
        hosts,
    )
    ruleset_id = await _get_custom_firewall_ruleset_id(token, zone_id)
    current = await _cf_request(
        "GET", f"/zones/{zone_id}/rulesets/{ruleset_id}", token
    )
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
        if not str(r.get("description") or "").startswith(POPOUT_RULE_PREFIX)
    ]

    raw_keys = await _load_raw_api_keys()
    popout_rules = _static_popout_rules(hosts)
    # API key gate first among Popout rules so scanners hitting /api/v1 are denied early
    popout_rules.insert(
        0,
        {
            "action": "block",
            "description": API_KEYS_RULE_DESC,
            "enabled": True,
            "expression": _api_key_allow_expr(hosts, raw_keys),
        },
    )

    merged = popout_rules + preserved
    await _cf_request(
        "PUT",
        f"/zones/{zone_id}/rulesets/{ruleset_id}",
        token,
        json_body={"rules": merged},
    )
    logger.info(
        "Cloudflare WAF synced: zone=%s keys=%s hosts=%s rules=%s",
        zone_id,
        len(raw_keys),
        hosts,
        len(merged),
    )
    return {
        "ok": True,
        "zone_id": zone_id,
        "hosts": hosts,
        "api_keys_synced": len(raw_keys),
        "rules": len(merged),
    }


async def sync_cloudflare_waf_safe() -> None:
    try:
        result = await sync_cloudflare_waf()
        if not result.get("ok") and not result.get("skipped"):
            logger.warning("Cloudflare WAF sync failed: %s", result)
    except Exception:
        logger.exception("Cloudflare WAF sync error")
