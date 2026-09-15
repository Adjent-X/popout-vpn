"""Create the first admin from env when the admins collection is empty."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import get_db, is_connected
from app.models.documents import AdminRole, ThemePreference

logger = logging.getLogger(__name__)


async def ensure_bootstrap_admin() -> None:
    """
    If no admins exist and BOOTSTRAP_ADMIN_EMAIL + BOOTSTRAP_ADMIN_PASSWORD
    are set, create that account once. Never updates an existing admin.
    """
    if not is_connected():
        return

    settings = get_settings()
    email = (settings.BOOTSTRAP_ADMIN_EMAIL or "").strip().lower()
    password = settings.BOOTSTRAP_ADMIN_PASSWORD or ""

    if not email or not password:
        logger.info(
            "No bootstrap admin configured (set BOOTSTRAP_ADMIN_EMAIL / "
            "BOOTSTRAP_ADMIN_PASSWORD to seed the first login when the DB is empty)"
        )
        return

    if len(password) < 8:
        logger.warning(
            "BOOTSTRAP_ADMIN_PASSWORD is shorter than 8 characters — refusing to seed"
        )
        return

    db = get_db()
    existing = await db.admins.count_documents({})
    if existing > 0:
        return

    now = datetime.now(timezone.utc)
    await db.admins.insert_one(
        {
            "email": email,
            "hashed_password": hash_password(password),
            "role": AdminRole.ADMIN.value,
            "theme": ThemePreference.DARK.value,
            "config_slot_limit": None,
            "created_at": now,
        }
    )
    logger.warning(
        "Bootstrapped first admin %s — change this password after first login "
        "and clear BOOTSTRAP_ADMIN_PASSWORD from config/app.env when done",
        email,
    )


async def ensure_bootstrap_public_gate() -> None:
    """
    If PUBLIC_GATE_PASSWORD is set and no gate hash exists yet, enable the
    public hostname access code. Never overwrites an operator-set password.
    """
    if not is_connected():
        return

    settings = get_settings()
    password = (settings.PUBLIC_GATE_PASSWORD or "").strip()
    if not password:
        return
    if len(password) < 8:
        logger.warning(
            "PUBLIC_GATE_PASSWORD is shorter than 8 characters — refusing to seed"
        )
        return

    from app.services.site_settings import get_site_settings, update_site_settings

    data, _ = await get_site_settings(use_cache=False)
    if (data.public_gate_password_hash or "").strip():
        if not data.public_gate_enabled:
            await update_site_settings({"public_gate_enabled": True})
            logger.info("Public access gate enabled (password already configured)")
        return

    await update_site_settings(
        {
            "public_gate_enabled": True,
            "public_gate_password_hash": hash_password(password),
        }
    )
    logger.warning(
        "Bootstrapped public access code — change it under Server settings, "
        "then clear PUBLIC_GATE_PASSWORD from config/app.env"
    )
