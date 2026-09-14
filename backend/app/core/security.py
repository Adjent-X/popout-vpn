from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_token(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(
    *,
    admin_id: str,
    role: str,
    email: str,
    persistent: bool = False,
) -> str:
    """Issue an access JWT.

    Full-admin / persistent sessions use a multi-year lifetime so they only
    end on explicit logout (or account lock). Everyone else uses the short TTL.
    """
    settings = get_settings()
    if persistent:
        expires_delta = timedelta(days=3650)  # ~10 years
    else:
        expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    return create_token(
        subject=admin_id,
        token_type="access",
        expires_delta=expires_delta,
        extra_claims={"role": role, "email": email},
    )


def create_refresh_token(*, admin_id: str, persistent: bool = False) -> str:
    settings = get_settings()
    if persistent:
        expires_delta = timedelta(days=3650)
    else:
        expires_delta = timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return create_token(
        subject=admin_id,
        token_type="refresh",
        expires_delta=expires_delta,
    )


def access_token_expires_seconds(*, persistent: bool) -> int:
    settings = get_settings()
    if persistent:
        return 3650 * 24 * 60 * 60
    return settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


def refresh_token_max_age_seconds(*, persistent: bool) -> int:
    settings = get_settings()
    if persistent:
        return 3650 * 24 * 60 * 60
    return settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise ValueError("Invalid token") from exc

    if payload.get("type") != expected_type:
        raise ValueError("Invalid token type")
    if not payload.get("sub"):
        raise ValueError("Invalid token subject")
    return payload
