"""Manage personal API keys (JWT session auth — admin & sub-admin)."""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_admin, require_db, require_full_admin
from app.models.api_keys import (
    ApiKeyPolicy,
    ApiKeyPolicyUpdate,
    ApiKeyPublic,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
)
from app.models.documents import AdminRole
from app.services.api_keys import (
    allowed_scopes_for_role,
    generate_api_key,
    get_api_key_policy,
    key_doc_to_public,
    resolve_expires_at,
    utcnow,
    validate_requested_scopes,
)
from app.services.site_settings import get_site_settings, update_site_settings

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


@router.get("/policy", response_model=ApiKeyPolicy)
async def read_api_key_policy(
    admin: dict = Depends(get_current_admin),
) -> ApiKeyPolicy:
    """Any signed-in admin can read policy (to know which scopes they may pick)."""
    _ = admin
    return await get_api_key_policy()


@router.get("/policy/allowed-scopes", response_model=list[str])
async def read_my_allowed_scopes(
    admin: dict = Depends(get_current_admin),
) -> list[str]:
    policy = await get_api_key_policy()
    role = admin.get("role", AdminRole.ADMIN.value)
    return list(allowed_scopes_for_role(policy, role))


@router.patch("/policy", response_model=ApiKeyPolicy)
async def patch_api_key_policy(
    body: ApiKeyPolicyUpdate,
    admin: dict = Depends(require_full_admin),
) -> ApiKeyPolicy:
    _ = admin
    current = await get_api_key_policy()
    merged = current.model_copy(
        update=body.model_dump(exclude_unset=True),
    )
    # Sub-admins never receive settings:write even if listed in policy
    merged.sub_admin_scopes = [
        s for s in merged.sub_admin_scopes if s != "settings:write"
    ]
    if merged.default_rate_limit_per_minute > merged.max_rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_rate_limit_per_minute cannot exceed max_rate_limit_per_minute",
        )
    await update_site_settings({"api_key_policy": merged.model_dump()})
    return merged


@router.get("", response_model=list[ApiKeyPublic])
async def list_my_api_keys(
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> list[ApiKeyPublic]:
    cursor = db.api_keys.find({"owner_admin_id": admin["_id"]}).sort(
        "created_at", -1
    )
    docs = await cursor.to_list(length=200)
    return [ApiKeyPublic(**key_doc_to_public(d)) for d in docs]


@router.post("", response_model=CreateApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: CreateApiKeyRequest,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> CreateApiKeyResponse:
    policy = await get_api_key_policy()
    role = admin.get("role", AdminRole.ADMIN.value)
    scopes = validate_requested_scopes(
        role=role, requested=list(body.scopes), policy=policy
    )

    count = await db.api_keys.count_documents({"owner_admin_id": admin["_id"]})
    if count >= int(policy.max_keys_per_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key limit reached ({policy.max_keys_per_admin})",
        )

    rate = body.rate_limit_per_minute
    if rate is None:
        rate = policy.default_rate_limit_per_minute
    rate = min(int(rate), int(policy.max_rate_limit_per_minute))

    analytics_iv = body.analytics_min_interval_seconds
    if analytics_iv is None:
        analytics_iv = policy.analytics_min_interval_seconds
    analytics_iv = max(2.5, float(analytics_iv))

    raw, prefix, digest = generate_api_key()
    now = utcnow()
    from app.services.cloudflare_waf import encrypt_api_key, sync_cloudflare_waf_safe

    doc: dict[str, Any] = {
        "name": body.name.strip(),
        "key_prefix": prefix,
        "key_hash": digest,
        "key_ciphertext": encrypt_api_key(raw),
        "owner_admin_id": admin["_id"],
        "scopes": scopes,
        "rate_limit_per_minute": rate,
        "analytics_min_interval_seconds": analytics_iv,
        "enabled": True,
        "created_at": now,
        "last_used_at": None,
        "expires_at": resolve_expires_at(body.expires_in_days),
    }
    result = await db.api_keys.insert_one(doc)
    doc["_id"] = result.inserted_id
    public = key_doc_to_public(doc)
    await sync_cloudflare_waf_safe()
    return CreateApiKeyResponse(**public, api_key=raw)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> None:
    if not ObjectId.is_valid(key_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    query: dict[str, Any] = {"_id": ObjectId(key_id), "owner_admin_id": admin["_id"]}
    # Full admins can delete any key
    if admin.get("role") == AdminRole.ADMIN.value:
        query = {"_id": ObjectId(key_id)}
    result = await db.api_keys.delete_one(query)
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    from app.services.cloudflare_waf import sync_cloudflare_waf_safe

    await sync_cloudflare_waf_safe()
