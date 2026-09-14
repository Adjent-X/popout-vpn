"""Startup checks that refuse unsafe production configuration."""

from __future__ import annotations

import logging
import secrets

from app.core.config import Settings

logger = logging.getLogger(__name__)

_INSECURE_JWT_SECRETS = frozenset(
    {
        "",
        "change-me-in-production",
        "change-me-to-a-long-random-secret",
        "replace-with-openssl-rand-hex-32-output",
        "secret",
        "jwt-secret",
    }
)


def validate_settings(settings: Settings) -> None:
    """
    In production: refuse to start with default/weak secrets.
    Turnstile secrets are required only when TURNSTILE_ENABLED=true.
    """
    weak_jwt = (
        settings.JWT_SECRET_KEY.strip().lower() in _INSECURE_JWT_SECRETS
        or len(settings.JWT_SECRET_KEY.strip()) < 32
    )
    missing_turnstile = settings.TURNSTILE_ENABLED and not settings.TURNSTILE_SECRET_KEY.strip()

    if settings.is_production:
        problems: list[str] = []
        if weak_jwt:
            problems.append(
                "JWT_SECRET_KEY is missing, too short (<32), or still a placeholder"
            )
        if missing_turnstile:
            problems.append(
                "TURNSTILE_ENABLED=true but TURNSTILE_SECRET_KEY is not set"
            )
        if settings.DEBUG:
            problems.append("DEBUG=true while running in production mode")
        if problems:
            raise RuntimeError(
                "Refusing to start with unsafe production settings: "
                + "; ".join(problems)
            )
        if not settings.TURNSTILE_ENABLED:
            logger.warning(
                "TURNSTILE_ENABLED=false — captcha skipped (use only on private/VPN networks)"
            )
        return

    if weak_jwt:
        logger.warning(
            "JWT_SECRET_KEY is weak or placeholder — set a long random secret before production"
        )
    if missing_turnstile:
        logger.warning(
            "TURNSTILE_ENABLED=true but TURNSTILE_SECRET_KEY is empty — login/register will fail checks"
        )
    if not settings.TURNSTILE_ENABLED:
        logger.info("TURNSTILE_ENABLED=false — Cloudflare Turnstile is disabled")


def generate_dev_hint() -> str:
    return secrets.token_urlsafe(48)
