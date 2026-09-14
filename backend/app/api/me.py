from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_current_admin, invalidate_admin_cache, require_db
from app.core.security import hash_password, verify_password
from app.models.auth import AdminPublic
from app.models.me import UpdateCredentialsRequest, UpdateThemeRequest
from app.services.admins import admin_to_public

router = APIRouter(prefix="/api/me", tags=["me"])


def _normalize_email(email: str) -> str:
    return email.strip().lower()


@router.get("", response_model=AdminPublic)
async def get_me(
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> AdminPublic:
    return await admin_to_public(admin, db)


@router.patch("/theme", response_model=AdminPublic)
async def update_theme(
    body: UpdateThemeRequest,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> AdminPublic:
    await db.admins.update_one(
        {"_id": admin["_id"]},
        {"$set": {"theme": body.theme.value}},
    )
    admin["theme"] = body.theme.value
    invalidate_admin_cache(str(admin["_id"]))
    return await admin_to_public(admin, db)


@router.patch("/credentials", response_model=AdminPublic)
async def update_credentials(
    body: UpdateCredentialsRequest,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> AdminPublic:
    if not verify_password(body.current_password, admin["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    updates: dict = {}

    if body.new_email is not None:
        email = _normalize_email(str(body.new_email))
        if email != admin["email"]:
            existing = await db.admins.find_one({"email": email})
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this email already exists",
                )
            updates["email"] = email

    if body.new_password is not None:
        updates["hashed_password"] = hash_password(body.new_password)

    if not updates:
        return await admin_to_public(admin, db)

    try:
        await db.admins.update_one({"_id": admin["_id"]}, {"$set": updates})
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None

    admin.update(updates)
    invalidate_admin_cache(str(admin["_id"]))
    return await admin_to_public(admin, db)
