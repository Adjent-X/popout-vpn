"""Helpers for admin/sub-admin accounts and slot quotas."""

from __future__ import annotations

from typing import Any

from app.models.auth import AdminPublic
from app.models.documents import AdminRole, ClientConfigStatus, ThemePreference


def is_full_admin(admin: dict[str, Any]) -> bool:
    return admin.get("role", AdminRole.ADMIN.value) == AdminRole.ADMIN.value


def is_sub_admin(admin: dict[str, Any]) -> bool:
    return admin.get("role") == AdminRole.SUB_ADMIN.value


async def count_used_slots(db: Any, admin_id: Any) -> int:
    """Non-revoked configs owned by this account count against the slot limit."""
    return await db.client_configs.count_documents(
        {
            "owner_admin_id": admin_id,
            "status": {"$ne": ClientConfigStatus.REVOKED.value},
        }
    )


async def admin_to_public(admin: dict[str, Any], db: Any) -> AdminPublic:
    used = await count_used_slots(db, admin["_id"])
    return AdminPublic(
        id=str(admin["_id"]),
        email=admin["email"],
        role=admin.get("role", AdminRole.ADMIN.value),
        theme=admin.get("theme", ThemePreference.DARK.value),
        config_slot_limit=admin.get("config_slot_limit"),
        config_slots_used=used,
        locked=bool(admin.get("locked", False)),
        last_login_at=admin.get("last_login_at"),
        last_login_ip=admin.get("last_login_ip"),
        created_at=admin.get("created_at"),
    )
