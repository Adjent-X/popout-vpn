"""Public Cloudflare site gate — password cookie for browser sessions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import JWTError, jwt

from app.core.config import get_settings

COOKIE_NAME = "popout_public_gate"
GATE_TOKEN_TYPE = "public_gate"
GATE_TTL_HOURS = 24


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_public_gate_token() -> str:
    settings = get_settings()
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": "public-gate",
        "type": GATE_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(hours=GATE_TTL_HOURS),
        "jti": str(uuid4()),
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_public_gate_token(token: str | None) -> bool:
    if not token:
        return False
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return False
    return payload.get("type") == GATE_TOKEN_TYPE and bool(payload.get("sub"))


def gate_cookie_max_age() -> int:
    return GATE_TTL_HOURS * 60 * 60


def is_gate_path_allowed(path: str) -> bool:
    """API paths reachable before the public gate is unlocked."""
    if path in {
        "/api/public/config",
        "/api/public/gate/unlock",
        "/api/health",
    }:
        return True
    if path.startswith("/api/public/gate/"):
        return True
    # Machine API keys authenticate themselves — no browser gate cookie
    if path.startswith("/api/v1/"):
        return True
    return False
