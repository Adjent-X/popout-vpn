from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse

from app.api.deps import get_current_admin, require_db, resolve_display_status, utcnow
from app.core.config import get_settings
from app.models.configs import (
    ActiveSession,
    ClientConfigResponse,
    CreateConfigRequest,
    CreateConfigResponse,
    ImportConfigsRequest,
    ImportConfigsResponse,
    OrphanPkiClient,
    UpdateExpiryRequest,
    UpdateWanLoggingRequest,
    UpdateWarpRoutingRequest,
)
from app.models.analytics import ConnectionLogEntry
from app.models.documents import ClientConfigStatus
from app.services.admins import count_used_slots, is_full_admin, is_sub_admin
from app.services.metrics_collector import CONNECTION_EVENTS_COLLECTION
from app.services.openvpn import OpenVPNError, build_client, rebuild_ovpn, revoke_client
from app.services.pki_import import import_pki_clients, list_orphan_pki_clients
from app.services.warp_routing import WarpRoutingError, sync_warp_routing
from app.services.wireguard import WireGuardError, add_peer, rebuild_client_conf, revoke_peer, wg_available

router = APIRouter(prefix="/api/configs", tags=["configs"])

ConfigDownloadFormat = Literal["ovpn", "wg"]


def _try_add_wg_peer(client_name: str) -> tuple[str | None, str | None]:
    if not wg_available():
        return None, None
    try:
        body, ipv4 = add_peer(client_name)
        return body, ipv4
    except WireGuardError as exc:
        import logging

        logging.getLogger(__name__).warning("WireGuard peer for %s: %s", client_name, exc)
        return None, None


def _try_rebuild_wg(client_name: str) -> str | None:
    if not wg_available():
        return None
    try:
        return rebuild_client_conf(client_name)
    except WireGuardError:
        return None


def _try_revoke_wg(client_name: str) -> None:
    try:
        revoke_peer(client_name)
    except WireGuardError:
        import logging

        logging.getLogger(__name__).warning("WireGuard revoke failed for %s", client_name)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _doc_to_response(
    doc: dict[str, Any],
    *,
    include_wan: bool = True,
) -> ClientConfigResponse:
    settings = get_settings()
    display = resolve_display_status(
        status_value=doc.get("status", ClientConfigStatus.ACTIVE.value),
        expires_at=_as_utc(doc["expires_at"]),
        expiring_soon_days=settings.CONFIG_EXPIRING_SOON_DAYS,
    )
    return ClientConfigResponse(
        id=str(doc["_id"]),
        label=doc["label"],
        client_name=doc["client_name"],
        owner_admin_id=str(doc["owner_admin_id"]),
        created_at=_as_utc(doc["created_at"]),
        expires_at=_as_utc(doc["expires_at"]),
        status=display,
        cert_serial=doc["cert_serial"],
        revoked_at=_as_utc(doc["revoked_at"]) if doc.get("revoked_at") else None,
        vpn_ip=doc.get("vpn_ip"),
        last_wan_ip=doc.get("last_wan_ip") if include_wan else None,
        last_connected_at=_as_utc(doc["last_connected_at"])
        if doc.get("last_connected_at")
        else None,
        is_online=bool(doc.get("is_online")),
        wan_ip_logging_enabled=doc.get("wan_ip_logging_enabled") if include_wan else None,
        warp_routing_enabled=bool(doc.get("warp_routing_enabled")),
        session_count=int(doc.get("session_count") or 0),
        active_sessions=[
            ActiveSession(
                vpn_ip=s.get("vpn_ip"),
                wan_ip=s.get("wan_ip") if include_wan else None,
                connected_since=_as_utc(s["connected_since"])
                if s.get("connected_since")
                else None,
                bytes_received=int(s.get("bytes_received") or 0),
                bytes_sent=int(s.get("bytes_sent") or 0),
            )
            for s in (doc.get("active_sessions") or [])
            if isinstance(s, dict)
        ],
    )


async def _duplicate_cn_blocks_new_configs(db: Any) -> str | None:
    """Return error detail if duplicate-cn mode forbids another config."""
    from app.services.site_settings import get_site_settings

    site, _ = await get_site_settings(use_cache=True)
    if not site.duplicate_cn_mode:
        return None
    existing = await db.client_configs.count_documents(
        {"status": {"$ne": ClientConfigStatus.REVOKED.value}}
    )
    if existing >= 1:
        return (
            "Duplicate-CN mode is on: this VPN shares one certificate across many "
            "users. Create, import, and reissue of additional configs are disabled. "
            "Manage the existing shared config only."
        )
    return None


def _resolve_expires_at(body: CreateConfigRequest) -> datetime:
    if body.expires_at is not None:
        exp = _as_utc(body.expires_at)
        if exp <= utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="expires_at must be in the future",
            )
        return exp
    assert body.expiry_days is not None
    return utcnow() + timedelta(days=body.expiry_days)


def _can_access_config(admin: dict, doc: dict) -> bool:
    if is_full_admin(admin):
        return True
    return doc.get("owner_admin_id") == admin["_id"]


async def _enforce_slot_limit(admin: dict, db: Any) -> None:
    if not is_sub_admin(admin):
        return
    limit = admin.get("config_slot_limit")
    if isinstance(limit, int) and limit > 0:
        used = await count_used_slots(db, admin["_id"])
        if used >= limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Config slot limit reached ({used}/{limit}). "
                    "Revoke an existing config to free a slot."
                ),
            )


@router.post("", response_model=CreateConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_config(
    body: CreateConfigRequest,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> CreateConfigResponse:
    block = await _duplicate_cn_blocks_new_configs(db)
    if block:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=block)
    await _enforce_slot_limit(admin, db)

    expires_at = _resolve_expires_at(body)
    try:
        built = await build_client(body.label)
    except OpenVPNError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate OpenVPN client certificate",
        ) from exc

    now = utcnow()
    wg_conf, wg_ipv4 = _try_add_wg_peer(built.client_name)
    doc = {
        "label": body.label.strip(),
        "client_name": built.client_name,
        "owner_admin_id": admin["_id"],
        "created_at": now,
        "expires_at": expires_at,
        "status": ClientConfigStatus.ACTIVE.value,
        "cert_serial": built.cert_serial,
        "revoked_at": None,
        "warp_routing_enabled": False,
        "wg_ipv4": wg_ipv4,
    }
    try:
        result = await db.client_configs.insert_one(doc)
    except Exception:
        try:
            await revoke_client(built.client_name)
        except OpenVPNError:
            pass
        _try_revoke_wg(built.client_name)
        raise

    doc["_id"] = result.inserted_id
    base = _doc_to_response(doc)
    return CreateConfigResponse(**base.model_dump(), ovpn=built.ovpn_content, wg_conf=wg_conf)


@router.get("", response_model=list[ClientConfigResponse])
async def list_configs(
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> list[ClientConfigResponse]:
    query: dict[str, Any] = {}
    if is_sub_admin(admin):
        query["owner_admin_id"] = admin["_id"]
    cursor = db.client_configs.find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=1000)
    return [_doc_to_response(doc, include_wan=True) for doc in docs]


@router.get("/orphans", response_model=list[OrphanPkiClient])
async def list_orphan_configs(
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> list[OrphanPkiClient]:
    """Full admin: CLI/installer clients on disk that are not in the panel yet."""
    if not is_full_admin(admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full admin role required",
        )
    orphans = await list_orphan_pki_clients(db)
    return [OrphanPkiClient(**row) for row in orphans]


@router.post("/import", response_model=ImportConfigsResponse)
async def import_configs(
    body: ImportConfigsRequest,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> ImportConfigsResponse:
    """
    Full admin: register existing easy-rsa clients (created via CLI/installer)
    so they can be downloaded, revoked, and monitored from the panel.
    Does not mint new certificates.
    """
    if not is_full_admin(admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full admin role required",
        )
    block = await _duplicate_cn_blocks_new_configs(db)
    if block:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=block)
    imported_docs, skipped, errors = await import_pki_clients(
        db,
        owner_admin_id=admin["_id"],
        client_names=body.client_names or None,
        expiry_days=body.expiry_days,
    )
    return ImportConfigsResponse(
        imported=[_doc_to_response(doc, include_wan=True) for doc in imported_docs],
        skipped=skipped,
        errors=errors,
    )


@router.get("/{config_id}/download")
async def download_config(
    config_id: str,
    file_format: ConfigDownloadFormat = Query(default="ovpn", alias="format"),
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> Response:
    if not ObjectId.is_valid(config_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    doc = await db.client_configs.find_one({"_id": ObjectId(config_id)})
    if doc is None or not _can_access_config(admin, doc):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    if doc.get("status") == ClientConfigStatus.REVOKED.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Config has been revoked",
        )

    if file_format == "wg":
        body = _try_rebuild_wg(doc["client_name"])
        if not body:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="WireGuard config is not available for this seat",
            )
        filename = f"{doc['client_name']}.conf"
        return PlainTextResponse(
            content=body,
            media_type="application/x-wireguard-profile",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    try:
        ovpn = await rebuild_ovpn(doc["client_name"])
    except OpenVPNError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to assemble OpenVPN config",
        ) from exc

    filename = f"{doc['client_name']}.ovpn"
    return PlainTextResponse(
        content=ovpn,
        media_type="application/x-openvpn-profile",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{config_id}/reissue", response_model=CreateConfigResponse)
async def reissue_config(
    config_id: str,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> CreateConfigResponse:
    """
    Revoked certificates stay on the CRL forever. Reissue mints a new cert under
    the same label and restores this row so a fresh .ovpn can be downloaded.
    """
    if not ObjectId.is_valid(config_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    doc = await db.client_configs.find_one({"_id": ObjectId(config_id)})
    if doc is None or not _can_access_config(admin, doc):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    if doc.get("status") != ClientConfigStatus.REVOKED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only revoked configs can be reissued",
        )

    block = await _duplicate_cn_blocks_new_configs(db)
    if block:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=block)

    await _enforce_slot_limit(admin, db)

    try:
        built = await build_client(doc["label"])
    except OpenVPNError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate OpenVPN client certificate",
        ) from exc

    _try_revoke_wg(doc["client_name"])
    wg_conf, wg_ipv4 = _try_add_wg_peer(built.client_name)

    now = utcnow()
    expires_at = _as_utc(doc["expires_at"])
    if expires_at <= now:
        expires_at = now + timedelta(days=30)

    updates = {
        "client_name": built.client_name,
        "cert_serial": built.cert_serial,
        "status": ClientConfigStatus.ACTIVE.value,
        "revoked_at": None,
        "expires_at": expires_at,
        "created_at": now,
        "wg_ipv4": wg_ipv4,
    }
    try:
        await db.client_configs.update_one({"_id": doc["_id"]}, {"$set": updates})
    except Exception:
        try:
            await revoke_client(built.client_name)
        except OpenVPNError:
            pass
        _try_revoke_wg(built.client_name)
        raise

    doc.update(updates)
    base = _doc_to_response(doc)
    return CreateConfigResponse(**base.model_dump(), ovpn=built.ovpn_content, wg_conf=wg_conf)


@router.delete(
    "/{config_id}",
    response_model=None,
    responses={
        200: {"model": ClientConfigResponse},
        204: {"description": "Revoked config permanently removed"},
    },
)
async def delete_config(
    config_id: str,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> ClientConfigResponse | Response:
    """
    Active/expired: revoke the cert (soft delete).
    Already revoked: remove the row from the database (hard delete).
    """
    if not ObjectId.is_valid(config_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    doc = await db.client_configs.find_one({"_id": ObjectId(config_id)})
    if doc is None or not _can_access_config(admin, doc):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    if doc.get("status") == ClientConfigStatus.REVOKED.value:
        if doc.get("warp_routing_enabled"):
            try:
                await sync_warp_routing(vpn_ip=doc.get("vpn_ip"), enabled=False)
            except WarpRoutingError:
                pass
        await db.client_configs.delete_one({"_id": doc["_id"]})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        await revoke_client(doc["client_name"])
    except OpenVPNError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to revoke OpenVPN client certificate",
        ) from exc

    _try_revoke_wg(doc["client_name"])

    if doc.get("warp_routing_enabled"):
        try:
            await sync_warp_routing(vpn_ip=doc.get("vpn_ip"), enabled=False)
        except WarpRoutingError:
            pass

    now = utcnow()
    await db.client_configs.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "status": ClientConfigStatus.REVOKED.value,
                "revoked_at": now,
                "is_online": False,
                "warp_routing_enabled": False,
            }
        },
    )
    doc["status"] = ClientConfigStatus.REVOKED.value
    doc["revoked_at"] = now
    doc["is_online"] = False
    doc["warp_routing_enabled"] = False
    return _doc_to_response(doc, include_wan=True)


@router.get("/{config_id}/connection-logs", response_model=list[ConnectionLogEntry])
async def get_connection_logs(
    config_id: str,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> list[ConnectionLogEntry]:
    if not ObjectId.is_valid(config_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    doc = await db.client_configs.find_one({"_id": ObjectId(config_id)})
    if doc is None or not _can_access_config(admin, doc):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    cursor = (
        db[CONNECTION_EVENTS_COLLECTION]
        .find({"config_id": doc["_id"]})
        .sort("at", -1)
        .limit(200)
    )
    rows = await cursor.to_list(length=200)
    out: list[ConnectionLogEntry] = []
    for row in rows:
        out.append(
            ConnectionLogEntry(
                id=str(row["_id"]),
                at=_as_utc(row["at"]),
                event=row.get("event", "unknown"),
                client_name=row.get("client_name", doc["client_name"]),
                wan_ip=row.get("wan_ip"),
                vpn_ip=row.get("vpn_ip"),
                wan_logged=bool(row.get("wan_logged")),
            )
        )
    return out


@router.patch("/{config_id}/wan-logging", response_model=ClientConfigResponse)
async def update_wan_logging(
    config_id: str,
    body: UpdateWanLoggingRequest,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> ClientConfigResponse:
    if not ObjectId.is_valid(config_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    doc = await db.client_configs.find_one({"_id": ObjectId(config_id)})
    if doc is None or not _can_access_config(admin, doc):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    await db.client_configs.update_one(
        {"_id": doc["_id"]},
        {"$set": {"wan_ip_logging_enabled": body.wan_ip_logging_enabled}},
    )
    doc["wan_ip_logging_enabled"] = body.wan_ip_logging_enabled
    return _doc_to_response(doc, include_wan=True)


@router.patch("/{config_id}/warp-routing", response_model=ClientConfigResponse)
async def update_warp_routing(
    config_id: str,
    body: UpdateWarpRoutingRequest,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> ClientConfigResponse:
    if not is_full_admin(admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full admin role required",
        )
    from app.core.config import get_settings

    if not get_settings().WARP_ROUTING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Warp routing is disabled on this server",
        )
    if not ObjectId.is_valid(config_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    doc = await db.client_configs.find_one({"_id": ObjectId(config_id)})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    if doc.get("status") == ClientConfigStatus.REVOKED.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Config has been revoked",
        )

    enabled = bool(body.warp_routing_enabled)
    try:
        await sync_warp_routing(vpn_ip=doc.get("vpn_ip"), enabled=enabled)
    except WarpRoutingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await db.client_configs.update_one(
        {"_id": doc["_id"]},
        {"$set": {"warp_routing_enabled": enabled}},
    )
    doc["warp_routing_enabled"] = enabled
    return _doc_to_response(doc, include_wan=True)


@router.patch("/{config_id}/expiry", response_model=ClientConfigResponse)
async def update_expiry(
    config_id: str,
    body: UpdateExpiryRequest,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> ClientConfigResponse:
    if not ObjectId.is_valid(config_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    doc = await db.client_configs.find_one({"_id": ObjectId(config_id)})
    if doc is None or not _can_access_config(admin, doc):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    if doc.get("status") == ClientConfigStatus.REVOKED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update expiry of a revoked config",
        )

    expires_at = _as_utc(body.expires_at)
    if expires_at <= utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expires_at must be in the future",
        )

    await db.client_configs.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "expires_at": expires_at,
                "status": ClientConfigStatus.ACTIVE.value,
            }
        },
    )
    doc["expires_at"] = expires_at
    doc["status"] = ClientConfigStatus.ACTIVE.value
    return _doc_to_response(doc, include_wan=True)
