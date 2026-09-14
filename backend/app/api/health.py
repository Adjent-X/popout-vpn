from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.version import app_version, github_repo_url

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check() -> dict:
    settings = get_settings()
    payload = {
        "status": "ok",
        "version": app_version(),
        "repository": github_repo_url(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if not settings.is_production:
        payload["service"] = settings.APP_NAME
        payload["environment"] = settings.ENVIRONMENT
    return payload
