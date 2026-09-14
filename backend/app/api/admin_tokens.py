import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_db, require_full_admin, utcnow
from app.core.config import get_settings
from app.models.admin_tokens import (
    CreateRegistrationTokenRequest,
    RegistrationTokenResponse,
)
from app.models.documents import AdminRole

router = APIRouter(prefix="/api/admin/tokens", tags=["admin-tokens"])


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _token_to_response(doc: dict) -> RegistrationTokenResponse:
    return RegistrationTokenResponse(
        id=str(doc["_id"]),
        token=doc["token"],
        role=doc.get("role", AdminRole.ADMIN.value),
        config_slot_limit=doc.get("config_slot_limit"),
        note=doc.get("note"),
        used=bool(doc.get("used", False)),
        used_by=str(doc["used_by"]) if doc.get("used_by") else None,
        created_by=str(doc["created_by"]) if doc.get("created_by") else None,
        expires_at=_as_utc(doc["expires_at"]),
        created_at=_as_utc(doc["created_at"]),
    )


@router.get("", response_model=list[RegistrationTokenResponse])
async def list_registration_tokens(
    admin: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> list[RegistrationTokenResponse]:
    _ = admin
    cursor = db.registration_tokens.find({}).sort("created_at", -1)
    docs = await cursor.to_list(length=500)
    return [_token_to_response(doc) for doc in docs]


@router.post(
    "",
    response_model=RegistrationTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_registration_token(
    body: CreateRegistrationTokenRequest,
    admin: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> RegistrationTokenResponse:
    settings = get_settings()
    hours = body.expires_in_hours or settings.REGISTRATION_TOKEN_TTL_HOURS
    now = utcnow()
    doc = {
        "token": secrets.token_urlsafe(32),
        "role": body.role.value,
        "config_slot_limit": body.config_slot_limit,
        "note": body.note,
        "created_by": admin["_id"],
        "used": False,
        "used_by": None,
        "expires_at": now + timedelta(hours=hours),
        "created_at": now,
    }
    result = await db.registration_tokens.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _token_to_response(doc)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registration_token(
    token_id: str,
    admin: dict = Depends(require_full_admin),
    db=Depends(require_db),
) -> None:
    _ = admin
    if not ObjectId.is_valid(token_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    doc = await db.registration_tokens.find_one({"_id": ObjectId(token_id)})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    if doc.get("used"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a token that has already been used",
        )

    await db.registration_tokens.delete_one({"_id": doc["_id"]})
