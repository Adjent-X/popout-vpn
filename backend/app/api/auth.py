from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.api.deps import require_auth_rate_limit, require_db, require_turnstile
from app.core.rate_limit import client_ip
from app.core.security import (
    access_token_expires_seconds,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    refresh_token_max_age_seconds,
    verify_password,
)
from app.models.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from app.models.documents import AdminRole, ThemePreference
from app.services.admins import admin_to_public, is_full_admin

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _set_refresh_cookie(
    response: Response,
    refresh_token: str,
    *,
    persistent: bool,
) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=refresh_token_max_age_seconds(persistent=persistent),
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/auth",
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
    )


def _session_persistent(admin: dict) -> bool:
    """Full admins never expire until logout."""
    return is_full_admin(admin)


async def _issue_tokens(
    admin: dict,
    response: Response,
    db,
    *,
    persistent: bool = False,
) -> TokenResponse:
    # Full admins always get non-expiring tokens regardless of checkbox.
    use_persistent = _session_persistent(admin) or persistent
    role = admin.get("role", AdminRole.ADMIN.value)
    access = create_access_token(
        admin_id=str(admin["_id"]),
        role=role,
        email=admin["email"],
        persistent=use_persistent,
    )
    refresh = create_refresh_token(
        admin_id=str(admin["_id"]),
        persistent=use_persistent,
    )
    _set_refresh_cookie(response, refresh, persistent=use_persistent)
    return TokenResponse(
        access_token=access,
        expires_in=access_token_expires_seconds(persistent=use_persistent),
        admin=await admin_to_public(admin, db),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_auth_rate_limit)],
)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db=Depends(require_db),
) -> TokenResponse:
    await require_turnstile(request, body.turnstile_token)

    email = _normalize_email(str(body.email))
    from app.core.rate_limit import enforce_auth_email_rate_limit

    await enforce_auth_email_rate_limit(email)
    now = _utcnow()

    try:
        token_doc = await db.registration_tokens.find_one_and_update(
            {
                "token": body.registration_token,
                "used": False,
                "expires_at": {"$gt": now},
            },
            {"$set": {"used": True}},
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    if token_doc is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired registration token",
        )

    existing = await db.admins.find_one({"email": email})
    if existing is not None:
        await db.registration_tokens.update_one(
            {"_id": token_doc["_id"]},
            {"$set": {"used": False}},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    role = token_doc.get("role", AdminRole.ADMIN.value)
    if role not in {AdminRole.ADMIN.value, AdminRole.SUB_ADMIN.value}:
        role = AdminRole.ADMIN.value

    slot_limit = token_doc.get("config_slot_limit")
    if role == AdminRole.SUB_ADMIN.value:
        if not isinstance(slot_limit, int) or slot_limit < 1:
            await db.registration_tokens.update_one(
                {"_id": token_doc["_id"]},
                {"$set": {"used": False}},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registration token is missing a valid config slot limit",
            )
    else:
        slot_limit = None

    admin_doc = {
        "email": email,
        "hashed_password": hash_password(body.password),
        "role": role,
        "theme": ThemePreference.DARK.value,
        "config_slot_limit": slot_limit,
        "locked": False,
        "last_login_at": now,
        "last_login_ip": client_ip(request),
        "created_at": now,
    }

    try:
        result = await db.admins.insert_one(admin_doc)
    except DuplicateKeyError:
        await db.registration_tokens.update_one(
            {"_id": token_doc["_id"]},
            {"$set": {"used": False}},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None
    except Exception:
        await db.registration_tokens.update_one(
            {"_id": token_doc["_id"]},
            {"$set": {"used": False}},
        )
        raise

    admin_id = result.inserted_id
    await db.registration_tokens.update_one(
        {"_id": token_doc["_id"]},
        {"$set": {"used_by": admin_id}},
    )

    admin_doc["_id"] = admin_id
    try:
        return await _issue_tokens(admin_doc, response, db)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(require_auth_rate_limit)],
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db=Depends(require_db),
) -> TokenResponse:
    await require_turnstile(request, body.turnstile_token)

    email = _normalize_email(str(body.email))
    from app.core.rate_limit import enforce_auth_email_rate_limit

    await enforce_auth_email_rate_limit(email)

    try:
        admin = await db.admins.find_one({"email": email})
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc

    password_ok = False
    if admin is not None:
        password_ok = verify_password(body.password, admin["hashed_password"])

    if admin is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if bool(admin.get("locked", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is locked. Contact another full admin.",
        )

    now = _utcnow()
    ip = client_ip(request)
    await db.admins.update_one(
        {"_id": admin["_id"]},
        {"$set": {"last_login_at": now, "last_login_ip": ip}},
    )
    admin["last_login_at"] = now
    admin["last_login_ip"] = ip

    # Full admins always persistent; sub-admins only when keep_signed_in
    persistent = _session_persistent(admin) or bool(body.keep_signed_in)

    try:
        return await _issue_tokens(
            admin, response, db, persistent=persistent
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(require_auth_rate_limit)],
)
async def refresh_access_token(
    request: Request,
    response: Response,
    db=Depends(require_db),
) -> TokenResponse:
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    try:
        payload = decode_token(raw, expected_type="refresh")
    except ValueError:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from None

    admin_id = payload["sub"]
    if not ObjectId.is_valid(admin_id):
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    admin = await db.admins.find_one({"_id": ObjectId(admin_id)})
    if admin is None:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if bool(admin.get("locked", False)):
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is locked",
        )

    return await _issue_tokens(admin, response, db)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_auth_rate_limit)],
)
async def logout(response: Response) -> None:
    _clear_refresh_cookie(response)
