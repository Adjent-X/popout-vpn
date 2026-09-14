from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import get_settings
from app.core.security import verify_password
from app.models.public import (
    BrandColors,
    BrandConfig,
    PublicConfigResponse,
    PublicGateUnlockRequest,
    PublicGateUnlockResponse,
)
from app.services.public_gate_auth import (
    COOKIE_NAME,
    create_public_gate_token,
    gate_cookie_max_age,
    verify_public_gate_token,
)
from app.services.site_settings import get_site_settings

router = APIRouter(prefix="/api/public", tags=["public"])


def _cookie_secure(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    return forwarded.lower() == "https"


def _set_gate_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=gate_cookie_max_age(),
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )


@router.get("/config", response_model=PublicConfigResponse)
async def public_config(request: Request) -> PublicConfigResponse:
    """Unauthenticated settings the UI needs (captcha, branding, gate)."""
    data, _source = await get_site_settings()
    gate_on = bool(data.public_gate_enabled) and bool(
        (data.public_gate_password_hash or "").strip()
    )
    unlocked = (not gate_on) or verify_public_gate_token(
        request.cookies.get(COOKIE_NAME)
    )
    return PublicConfigResponse(
        turnstile_enabled=data.turnstile_enabled,
        turnstile_site_key=data.turnstile_site_key if data.turnstile_enabled else "",
        brand=BrandConfig(
            name=data.brand_name,
            product=data.brand_product,
            site_title=(data.site_title or "").strip() or "Popout VPN Admin",
            colors=BrandColors(
                background=data.brand_color_bg,
                primary=data.brand_color_primary,
                accent=data.brand_color_accent,
                accent_bright=data.brand_color_accent_bright,
            ),
        ),
        warp_routing_enabled=bool(get_settings().WARP_ROUTING_ENABLED),
        duplicate_cn_mode=bool(data.duplicate_cn_mode),
        public_gate_enabled=gate_on,
        public_gate_unlocked=unlocked,
    )


@router.post("/gate/unlock", response_model=PublicGateUnlockResponse)
async def unlock_public_gate(
    body: PublicGateUnlockRequest,
    request: Request,
    response: Response,
) -> PublicGateUnlockResponse:
    """Password-only unlock for the public Cloudflare site gate (no username)."""
    data, _ = await get_site_settings(use_cache=False)
    gate_on = bool(data.public_gate_enabled) and bool(
        (data.public_gate_password_hash or "").strip()
    )
    if not gate_on:
        response.delete_cookie(COOKIE_NAME, path="/")
        return PublicGateUnlockResponse(unlocked=True)

    if not verify_password(body.password, data.public_gate_password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect gate password",
        )

    _set_gate_cookie(response, request, create_public_gate_token())
    return PublicGateUnlockResponse(unlocked=True)
