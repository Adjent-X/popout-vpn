import logging

import httpx

from app.services.site_settings import get_site_settings

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(token: str, remote_ip: str | None = None) -> bool:
    """Verify Cloudflare Turnstile using runtime site settings (Mongo overlay)."""
    site, _ = await get_site_settings()
    if not site.turnstile_enabled:
        return True

    if not token or not token.strip():
        return False

    if not site.turnstile_secret_key:
        logger.error("Turnstile is enabled but no secret key is configured")
        return False

    data: dict[str, str] = {
        "secret": site.turnstile_secret_key,
        "response": token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(TURNSTILE_VERIFY_URL, data=data)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        logger.exception("Turnstile verification request failed")
        return False

    success = bool(payload.get("success"))
    if not success:
        logger.info("Turnstile verification rejected: %s", payload.get("error-codes"))
    return success
