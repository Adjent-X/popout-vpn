"""Full-admin management of all admin accounts."""

from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.api.deps import invalidate_admin_cache, require_db, require_full_admin
from app.core.security import hash_password
from app.models.auth import AdminPublic, UpdateAdminAccountRequest
from app.models.documents import AdminRole
from app.services.admins import admin_to_public, is_full_admin

router = APIRouter(prefix="/api/admins", tags=["admins"])


def _normalize_email(email: str) -> str:
    return email.strip().lower()


@router.get("", response_model=list[AdminPublic])
async def list_admins(
    _admin: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> list[AdminPublic]:
    try:
        cursor = db.admins.find({}).sort("created_at", -1)
        docs = await cursor.to_list(length=500)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return [await admin_to_public(doc, db) for doc in docs]


@router.patch("/{admin_id}", response_model=AdminPublic)
async def update_admin(
    admin_id: str,
    body: UpdateAdminAccountRequest,
    actor: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> AdminPublic:
    if not ObjectId.is_valid(admin_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )
    oid = ObjectId(admin_id)
    target = await db.admins.find_one({"_id": oid})
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )

    updates: dict = {}

    if body.email is not None:
        email = _normalize_email(str(body.email))
        if email != target["email"]:
            clash = await db.admins.find_one({"email": email, "_id": {"$ne": oid}})
            if clash is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this email already exists",
                )
            updates["email"] = email

    if body.password is not None:
        updates["hashed_password"] = hash_password(body.password)

    if body.locked is not None:
        if str(actor["_id"]) == admin_id and body.locked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot lock your own account",
            )
        if body.locked and is_full_admin(target):
            peers = await db.admins.find(
                {
                    "role": AdminRole.ADMIN.value,
                    "_id": {"$ne": oid},
                }
            ).to_list(length=200)
            unlocked_peers = [
                a for a in peers if not bool(a.get("locked", False))
            ]
            if len(unlocked_peers) < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot lock the last unlocked full admin",
                )
        updates["locked"] = bool(body.locked)

    target_is_full = is_full_admin(target)

    if body.clear_slot_limit:
        if not target_is_full:
            # Sub-admins need a slot limit; clearing only valid for full admins
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sub-admins require a config slot limit",
            )
        updates["config_slot_limit"] = None
    elif body.config_slot_limit is not None:
        if target_is_full:
            # Allow setting a limit on full admins if desired, but usually unlimited
            updates["config_slot_limit"] = int(body.config_slot_limit)
        else:
            updates["config_slot_limit"] = int(body.config_slot_limit)

    if not updates:
        return await admin_to_public(target, db)

    try:
        await db.admins.update_one({"_id": oid}, {"$set": updates})
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc

    invalidate_admin_cache(admin_id)
    updated = await db.admins.find_one({"_id": oid})
    assert updated is not None
    return await admin_to_public(updated, db)


@router.delete("/{admin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin(
    admin_id: str,
    actor: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> None:
    if not ObjectId.is_valid(admin_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )
    if str(actor["_id"]) == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )

    oid = ObjectId(admin_id)
    target = await db.admins.find_one({"_id": oid})
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )

    # Keep at least one unlocked full admin
    if is_full_admin(target):
        peers = await db.admins.find(
            {
                "role": AdminRole.ADMIN.value,
                "_id": {"$ne": oid},
            }
        ).to_list(length=200)
        unlocked_peers = [a for a in peers if not bool(a.get("locked", False))]
        if len(unlocked_peers) < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last unlocked full admin",
            )

    result = await db.admins.delete_one({"_id": oid})
    if result.deleted_count != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )
    invalidate_admin_cache(admin_id)
