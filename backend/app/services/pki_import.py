"""Import OpenVPN clients that already exist in easy-rsa PKI into MongoDB."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from app.models.documents import ClientConfigStatus
from app.services.openvpn import (
    OpenVPNError,
    list_pki_clients,
    parse_ipp_map,
    read_cert_serial,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def find_full_admin_owner(db: Any) -> ObjectId | None:
    """Prefer an unlocked full admin as owner for auto-imported configs."""
    doc = await db.admins.find_one(
        {"role": "admin", "locked": {"$ne": True}},
        sort=[("created_at", 1)],
    )
    if doc is None:
        doc = await db.admins.find_one({"role": "admin"}, sort=[("created_at", 1)])
    if doc is None:
        return None
    return doc["_id"]


async def list_orphan_pki_clients(db: Any) -> list[dict[str, Any]]:
    """PKI clients not yet represented in client_configs."""
    known_rows = await db.client_configs.find({}, {"client_name": 1}).to_list(length=5000)
    known = {row["client_name"] for row in known_rows if row.get("client_name")}
    ipp = parse_ipp_map()
    orphans: list[dict[str, Any]] = []
    for client in await list_pki_clients():
        if client.client_name in known:
            continue
        orphans.append(
            {
                "client_name": client.client_name,
                "cert_serial": client.cert_serial,
                "revoked": client.revoked,
                "has_key": client.has_key,
                "vpn_ip": ipp.get(client.client_name),
            }
        )
    return orphans


async def import_pki_clients(
    db: Any,
    *,
    owner_admin_id: ObjectId,
    client_names: list[str] | None = None,
    expiry_days: int = 3650,
) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    """
    Create client_configs rows for existing PKI certs (no new easy-rsa build).

    Returns (imported_docs, skipped_names, errors_by_name).
    """
    orphans = await list_orphan_pki_clients(db)
    orphan_by_name = {o["client_name"]: o for o in orphans}

    if client_names:
        wanted = [n.strip() for n in client_names if n and n.strip()]
    else:
        wanted = list(orphan_by_name.keys())

    imported: list[dict[str, Any]] = []
    skipped: list[str] = []
    errors: dict[str, str] = {}
    now = _utcnow()
    expires_at = now + timedelta(days=expiry_days)
    ipp = parse_ipp_map()

    for name in wanted:
        orphan = orphan_by_name.get(name)
        if orphan is None:
            # Already in DB or not on PKI
            existing = await db.client_configs.find_one({"client_name": name})
            if existing is not None:
                skipped.append(name)
            else:
                errors[name] = "Not found in OpenVPN PKI"
            continue

        if not orphan["has_key"] and not orphan["revoked"]:
            errors[name] = "Private key missing; cannot manage/download"
            continue

        try:
            serial = await read_cert_serial(name)
        except OpenVPNError as exc:
            errors[name] = str(exc)
            continue

        status = (
            ClientConfigStatus.REVOKED.value
            if orphan["revoked"]
            else ClientConfigStatus.ACTIVE.value
        )
        doc: dict[str, Any] = {
            "label": name,
            "client_name": name,
            "owner_admin_id": owner_admin_id,
            "created_at": now,
            "expires_at": expires_at,
            "status": status,
            "cert_serial": serial,
            "revoked_at": now if orphan["revoked"] else None,
            "vpn_ip": ipp.get(name) or orphan.get("vpn_ip"),
            "warp_routing_enabled": False,
            "imported_from_pki": True,
        }
        try:
            result = await db.client_configs.insert_one(doc)
        except Exception as exc:
            # Unique index race
            logger.warning("Import insert failed for %s: %s", name, exc)
            skipped.append(name)
            continue
        doc["_id"] = result.inserted_id
        imported.append(doc)
        logger.info("Imported PKI client %s into panel (status=%s)", name, status)

    return imported, skipped, errors


async def auto_import_pki_clients(db: Any) -> int:
    """Startup helper: import all orphan PKI clients under the first full admin."""
    owner = await find_full_admin_owner(db)
    if owner is None:
        logger.warning("Skipping PKI auto-import: no full admin found")
        return 0
    imported, _skipped, errors = await import_pki_clients(
        db, owner_admin_id=owner, client_names=None
    )
    if errors:
        logger.warning("PKI auto-import errors: %s", errors)
    if imported:
        logger.info("Auto-imported %s existing OpenVPN client(s) into panel", len(imported))
    return len(imported)
