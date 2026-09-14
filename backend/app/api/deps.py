from datetime import datetime, timedelta, timezone
from typing import Any
import time

from bson import ObjectId
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.rate_limit import client_ip, enforce_auth_rate_limit
from app.core.security import decode_token
from app.core.turnstile import verify_turnstile
from app.db import get_db, is_connected
from app.models.documents import AdminRole, ClientConfigStatus

_bearer = HTTPBearer(auto_error=False)

# Short TTL cuts remote Mongo RTT on Live analytics polls (~4/sec).
_admin_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_ADMIN_CACHE_TTL = 5.0


async def require_db():
    if not is_connected():
        from app.db.mongodb import ensure_connected

        if not await ensure_connected():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
    return get_db()


async def require_auth_rate_limit(request: Request) -> None:
    await enforce_auth_rate_limit(request)


async def require_turnstile(request: Request, turnstile_token: str) -> None:
    ok = await verify_turnstile(turnstile_token, remote_ip=client_ip(request))
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Turnstile verification failed",
        )


def invalidate_admin_cache(admin_id: str | None = None) -> None:
    if admin_id is None:
        _admin_cache.clear()
    else:
        _admin_cache.pop(str(admin_id), None)


async def get_current_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db=Depends(require_db),
) -> dict[str, Any]:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    admin_id = payload.get("sub")
    if not admin_id or not ObjectId.is_valid(admin_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    now = time.monotonic()
    cached = _admin_cache.get(admin_id)
    if cached is not None and (now - cached[0]) < _ADMIN_CACHE_TTL:
        return cached[1]

    admin = await db.admins.find_one({"_id": ObjectId(admin_id)})
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    if bool(admin.get("locked", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is locked",
        )

    # Enforce role from Mongo (source of truth), not only the JWT claim
    role = admin.get("role", AdminRole.ADMIN.value)
    if role not in {AdminRole.ADMIN.value, AdminRole.SUB_ADMIN.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    _admin_cache[admin_id] = (now, admin)
    return admin


async def require_full_admin(
    admin: dict[str, Any] = Depends(get_current_admin),
) -> dict[str, Any]:
    """Site settings and invite tokens are full-admin only."""
    if admin.get("role", AdminRole.ADMIN.value) != AdminRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full admin role required",
        )
    return admin


async def get_api_key_context(
    request: Request,
    db=Depends(require_db),
) -> dict[str, Any]:
    """Authenticate machine clients via API key (Bearer pk_live_… or X-Api-Key)."""
    from app.services.api_keys import (
        enforce_api_key_rate_limit,
        is_key_expired,
        lookup_api_key,
        parse_bearer_api_key,
        utcnow,
    )

    raw = parse_bearer_api_key(
        request.headers.get("Authorization"),
        request.headers.get("X-Api-Key"),
    )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    doc = await lookup_api_key(db, raw)
    if doc is None or is_key_expired(doc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    owner_id = doc.get("owner_admin_id")
    admin = await db.admins.find_one({"_id": owner_id})
    if admin is None or bool(admin.get("locked", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key owner account unavailable",
        )

    await enforce_api_key_rate_limit(
        str(doc["_id"]),
        int(doc.get("rate_limit_per_minute") or 60),
    )

    # Touch last_used_at (best-effort, non-blocking semantics)
    try:
        await db.api_keys.update_one(
            {"_id": doc["_id"]},
            {"$set": {"last_used_at": utcnow()}},
        )
    except Exception:
        pass

    return {
        "key": doc,
        "admin": admin,
        "scopes": list(doc.get("scopes") or []),
        "key_id": str(doc["_id"]),
        "analytics_min_interval_seconds": float(
            doc.get("analytics_min_interval_seconds") or 2.5
        ),
        "rate_limit_per_minute": int(doc.get("rate_limit_per_minute") or 60),
    }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def resolve_display_status(
    *,
    status_value: str,
    expires_at: datetime,
    expiring_soon_days: int,
) -> ClientConfigStatus:
    if status_value == ClientConfigStatus.REVOKED.value:
        return ClientConfigStatus.REVOKED
    if status_value == ClientConfigStatus.EXPIRED.value:
        return ClientConfigStatus.EXPIRED

    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    now = utcnow()
    if exp <= now:
        return ClientConfigStatus.EXPIRED
    if exp <= now + timedelta(days=expiring_soon_days):
        return ClientConfigStatus.EXPIRING_SOON
    return ClientConfigStatus.ACTIVE
