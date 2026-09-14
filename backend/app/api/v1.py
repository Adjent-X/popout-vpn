"""Versioned REST API for machine clients authenticated with API keys."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.api.analytics import analytics_overview
from app.api.configs import (
    create_config,
    delete_config,
    get_connection_logs,
)
from app.api.deps import get_api_key_context, require_db
from app.api.site_settings import _to_admin_response, _with_live_shape, patch_site_settings
from app.models.analytics import AnalyticsOverview, ConnectionLogEntry
from app.models.configs import (
    ClientConfigResponse,
    CreateConfigRequest,
    CreateConfigResponse,
)
from app.models.documents import AdminRole
from app.models.site_settings import (
    SiteSettingsAdminResponse,
    UpdateSiteSettingsRequest,
)
from app.services.api_keys import (
    enforce_analytics_min_interval,
    require_scope,
)
from app.services.site_settings import get_site_settings

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


class V1ShapeUpdateRequest(BaseModel):
    """Traffic shaping + selected server settings (full-admin keys only)."""

    client_shape_enabled: bool | None = None
    client_shape_down_mbit: int | None = Field(default=None, ge=1, le=10_000)
    client_shape_up_mbit: int | None = Field(default=None, ge=1, le=10_000)
    analytics_refresh_seconds: float | None = None
    wan_ip_logging_enabled: bool | None = None
    unique_wan_ip_limit: int | None = Field(default=None, ge=1, le=1000)
    unique_wan_ip_window_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    duplicate_cn_mode: bool | None = None


@router.get("/health")
async def v1_health(ctx: dict[str, Any] = Depends(get_api_key_context)) -> dict[str, Any]:
    return {
        "status": "ok",
        "key_id": ctx["key_id"],
        "scopes": ctx["scopes"],
        "owner_role": ctx["admin"].get("role"),
    }


@router.post(
    "/configs",
    response_model=CreateConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def v1_create_config(
    body: CreateConfigRequest,
    ctx: dict[str, Any] = Depends(get_api_key_context),
    db=Depends(require_db),
) -> CreateConfigResponse:
    require_scope(ctx, "configs:create")
    return await create_config(body=body, admin=ctx["admin"], db=db)


@router.delete("/configs/{config_id}", response_model=None)
async def v1_revoke_config(
    config_id: str,
    ctx: dict[str, Any] = Depends(get_api_key_context),
    db=Depends(require_db),
) -> ClientConfigResponse | Response:
    require_scope(ctx, "configs:revoke")
    return await delete_config(config_id=config_id, admin=ctx["admin"], db=db)


@router.get(
    "/configs/{config_id}/connection-logs",
    response_model=list[ConnectionLogEntry],
)
async def v1_connection_logs(
    config_id: str,
    ctx: dict[str, Any] = Depends(get_api_key_context),
    db=Depends(require_db),
) -> list[ConnectionLogEntry]:
    require_scope(ctx, "configs:logs")
    return await get_connection_logs(config_id=config_id, admin=ctx["admin"], db=db)


@router.get("/analytics/overview", response_model=AnalyticsOverview)
async def v1_analytics_overview(
    hours: int = Query(default=24, ge=1, le=168),
    include_series: bool = Query(default=True),
    ctx: dict[str, Any] = Depends(get_api_key_context),
    db=Depends(require_db),
) -> AnalyticsOverview:
    require_scope(ctx, "analytics:read")
    await enforce_analytics_min_interval(
        ctx["key_id"],
        ctx.get("analytics_min_interval_seconds") or 2.5,
    )
    return await analytics_overview(
        hours=hours,
        max_age=None,
        include_series=include_series,
        admin=ctx["admin"],
        db=db,
    )


@router.get("/site-settings", response_model=SiteSettingsAdminResponse)
async def v1_read_site_settings(
    ctx: dict[str, Any] = Depends(get_api_key_context),
) -> SiteSettingsAdminResponse:
    require_scope(ctx, "settings:write")
    if ctx["admin"].get("role") != AdminRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full admin API key required",
        )
    data, source = await get_site_settings(use_cache=False)
    return _with_live_shape(_to_admin_response(data, source))


@router.patch("/site-settings", response_model=SiteSettingsAdminResponse)
async def v1_patch_site_settings(
    body: V1ShapeUpdateRequest,
    ctx: dict[str, Any] = Depends(get_api_key_context),
    db=Depends(require_db),
) -> SiteSettingsAdminResponse:
    """Traffic shaping and selected server settings — full-admin keys only."""
    require_scope(ctx, "settings:write")
    if ctx["admin"].get("role") != AdminRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full admin API key required",
        )
    payload = UpdateSiteSettingsRequest(**body.model_dump(exclude_unset=True))
    return await patch_site_settings(body=payload, admin=ctx["admin"], db=db)
