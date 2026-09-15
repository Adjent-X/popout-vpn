from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.admin_tokens import router as admin_tokens_router
from app.api.admins import router as admins_router
from app.api.analytics import router as analytics_router
from app.api.api_keys import router as api_keys_router
from app.api.attacks import router as attacks_router
from app.api.auth import router as auth_router
from app.api.configs import router as configs_router
from app.api.health import router as health_router
from app.api.me import router as me_router
from app.api.public import router as public_router
from app.api.site_settings import router as site_settings_router
from app.api.v1 import router as v1_router
from app.core.config import get_settings
from app.core.hardening import validate_settings
from app.db import close_db, connect_db, ensure_indexes
from app.services.bootstrap import ensure_bootstrap_admin, ensure_bootstrap_public_gate
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.site_settings import ensure_site_settings_seeded

logger = logging.getLogger(__name__)
settings = get_settings()
validate_settings(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        # Retry — mongod may still be warming after reboot / memory-tune restarts
        await connect_db(retries=20, delay_seconds=1.0)
        await ensure_indexes()
        await ensure_site_settings_seeded()
        await ensure_bootstrap_admin()
        try:
            await ensure_bootstrap_public_gate()
        except Exception:
            logger.exception("Could not seed public access code")
        logger.info("MongoDB connected; indexes ensured")
        try:
            from app.db import get_db
            from app.services.pki_import import auto_import_pki_clients

            db = get_db()
            if db is not None:
                await auto_import_pki_clients(db)
        except Exception:
            logger.exception("Could not auto-import existing OpenVPN PKI clients")
        try:
            from app.services.attacks import ensure_attack_dirs, write_attacks_conf

            ensure_attack_dirs()
            await write_attacks_conf()
        except Exception:
            logger.exception("Could not seed attack monitor config")
    except Exception:
        logger.exception(
            "MongoDB unavailable after retries — API will keep trying on requests. "
            "Ensure local mongod is running on 127.0.0.1:27017."
        )
        await close_db()

    start_scheduler()
    try:
        from app.services.scheduler import apply_analytics_interval_from_db

        await apply_analytics_interval_from_db()
    except Exception:
        logger.exception("Could not apply analytics collector interval from site settings")
    try:
        from app.services.scheduler import apply_backup_interval_from_db

        await apply_backup_interval_from_db()
    except Exception:
        logger.exception("Could not apply backup interval from site settings")
    try:
        from app.services.public_gate import (
            ensure_sync_script_installed,
            sync_public_access_gate,
        )

        # App-level modal gate replaces nginx basic auth — keep nginx auth off
        # so visitors only see the client password dialog (no username prompt).
        ensure_sync_script_installed()
        sync_public_access_gate(enabled=False)
    except Exception:
        logger.exception("Could not sync public Cloudflare password gate")
    yield
    stop_scheduler()
    await close_db()


_docs_enabled = settings.DEBUG and not settings.is_production

app = FastAPI(
    title=settings.APP_NAME,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_public_gate(request: Request, call_next):
    """Block API traffic until the public site gate cookie is valid."""
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    from app.services.public_gate_auth import (
        COOKIE_NAME,
        is_gate_path_allowed,
        verify_public_gate_token,
    )
    from app.services.site_settings import get_site_settings

    if is_gate_path_allowed(path):
        return await call_next(request)

    try:
        data, _ = await get_site_settings(use_cache=True)
    except Exception:
        return await call_next(request)

    gate_on = bool(data.public_gate_enabled) and bool(
        (data.public_gate_password_hash or "").strip()
    )
    if not gate_on:
        return await call_next(request)

    if verify_public_gate_token(request.cookies.get(COOKIE_NAME)):
        return await call_next(request)

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Public site gate locked — enter the gate password"},
        headers={"X-Popout-Gate": "required"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    if settings.is_production:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Invalid request"},
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


app.include_router(health_router)
app.include_router(public_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(admin_tokens_router)
app.include_router(admins_router)
app.include_router(api_keys_router)
app.include_router(v1_router)
app.include_router(attacks_router)
app.include_router(analytics_router)
app.include_router(site_settings_router)
app.include_router(configs_router)
