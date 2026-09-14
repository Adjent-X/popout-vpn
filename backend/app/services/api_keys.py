"""API key create/verify helpers and per-key rate limiting."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status

from app.core.rate_limit import SlidingWindowRateLimiter
from app.models.api_keys import (
    ALL_API_SCOPES,
    FULL_ADMIN_ONLY_SCOPES,
    ApiKeyPolicy,
    ApiScope,
)
from app.models.documents import AdminRole
from app.services.site_settings import get_site_settings

KEY_PREFIX_TAG = "pk_live_"
api_key_rate_limiter = SlidingWindowRateLimiter()
_analytics_last_hit: dict[str, float] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (raw_key, key_prefix, key_hash)."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    raw = f"{KEY_PREFIX_TAG}{prefix}_{secret}"
    return raw, prefix, hash_api_key(raw)


def parse_bearer_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key and x_api_key.strip().startswith(KEY_PREFIX_TAG):
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            if token.startswith(KEY_PREFIX_TAG):
                return token
    return None


async def get_api_key_policy() -> ApiKeyPolicy:
    data, _ = await get_site_settings(use_cache=True)
    raw = getattr(data, "api_key_policy", None)
    if isinstance(raw, dict):
        try:
            return ApiKeyPolicy.model_validate(raw)
        except Exception:
            pass
    if isinstance(raw, ApiKeyPolicy):
        return raw
    return ApiKeyPolicy()


def allowed_scopes_for_role(policy: ApiKeyPolicy, role: str) -> list[ApiScope]:
    if role == AdminRole.ADMIN.value:
        return list(policy.admin_scopes)
    # Strip full-admin-only scopes for sub-admins even if misconfigured
    return [
        s
        for s in policy.sub_admin_scopes
        if s not in FULL_ADMIN_ONLY_SCOPES and s in ALL_API_SCOPES
    ]


def validate_requested_scopes(
    *,
    role: str,
    requested: list[str],
    policy: ApiKeyPolicy,
) -> list[str]:
    allowed = set(allowed_scopes_for_role(policy, role))
    cleaned: list[str] = []
    for s in requested:
        if s not in ALL_API_SCOPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown scope: {s}",
            )
        if s not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope not allowed for your role: {s}",
            )
        if s not in cleaned:
            cleaned.append(s)
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one allowed scope",
        )
    return cleaned


async def enforce_api_key_rate_limit(key_id: str, limit_per_minute: int) -> None:
    await api_key_rate_limiter.hit(
        f"apikey:{key_id}",
        limit=max(1, int(limit_per_minute)),
        window_seconds=60.0,
    )


async def enforce_analytics_min_interval(key_id: str, min_seconds: float) -> None:
    import time

    floor = max(2.5, float(min_seconds))
    now = time.monotonic()
    last = _analytics_last_hit.get(key_id)
    if last is not None:
        elapsed = now - last
        if elapsed < floor:
            retry = max(1, int(floor - elapsed) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Analytics API limited to once every {floor:g}s for this key"
                ),
                headers={"Retry-After": str(retry)},
            )
    _analytics_last_hit[key_id] = now


def require_scope(ctx: dict[str, Any], scope: str) -> None:
    scopes = set(ctx.get("scopes") or [])
    if scope not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key missing scope: {scope}",
        )


def key_doc_to_public(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name") or "",
        "key_prefix": doc.get("key_prefix") or "",
        "scopes": list(doc.get("scopes") or []),
        "rate_limit_per_minute": int(doc.get("rate_limit_per_minute") or 60),
        "analytics_min_interval_seconds": float(
            doc.get("analytics_min_interval_seconds") or 2.5
        ),
        "enabled": bool(doc.get("enabled", True)),
        "created_at": doc["created_at"],
        "last_used_at": doc.get("last_used_at"),
        "expires_at": doc.get("expires_at"),
    }


async def lookup_api_key(db: Any, raw_key: str) -> dict[str, Any] | None:
    if not raw_key.startswith(KEY_PREFIX_TAG):
        return None
    rest = raw_key[len(KEY_PREFIX_TAG) :]
    if "_" not in rest:
        return None
    prefix, _secret = rest.split("_", 1)
    digest = hash_api_key(raw_key)
    doc = await db.api_keys.find_one(
        {"key_prefix": prefix, "key_hash": digest, "enabled": True}
    )
    return doc


def is_key_expired(doc: dict[str, Any], now: datetime | None = None) -> bool:
    exp = doc.get("expires_at")
    if not exp:
        return False
    now = now or utcnow()
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp <= now


def resolve_expires_at(days: int | None) -> datetime | None:
    if days is None:
        return None
    return utcnow() + timedelta(days=int(days))
