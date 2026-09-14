"""In-process APScheduler: expiry, host metrics, OpenVPN connection sync, backups."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.db import get_db, is_connected
from app.models.documents import ClientConfigStatus
from app.services.openvpn import OpenVPNError, revoke_client

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

JOB_METRICS = "collect_host_metrics"
JOB_CONNECTIONS = "sync_openvpn_connections"
JOB_BACKUP = "panel_backup"
# UI / site-setting options. Sub-second = Live (on-demand samples; Mongo persist is throttled).
ALLOWED_ANALYTICS_REFRESH = (0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
# Never write host_metrics or sync OpenVPN status faster than this in the background.
METRICS_PERSIST_MIN_SECONDS = 2.5
CONNECTIONS_MIN_SECONDS = 2.5


def normalize_analytics_refresh_seconds(
    value: float | int | None,
    *,
    fallback: float = 10.0,
) -> float:
    try:
        candidate = float(value) if value is not None else float(fallback)
    except (TypeError, ValueError):
        candidate = float(fallback)
    if candidate in ALLOWED_ANALYTICS_REFRESH:
        return candidate
    return min(ALLOWED_ANALYTICS_REFRESH, key=lambda x: abs(x - candidate))


def background_metrics_interval(ui_interval: float) -> float:
    """Background Mongo history cadence — caps load when UI is in Live mode."""
    return max(float(ui_interval), METRICS_PERSIST_MIN_SECONDS)


def background_connections_interval(ui_interval: float) -> float:
    return max(float(ui_interval), CONNECTIONS_MIN_SECONDS)

def normalize_backup_interval_minutes(
    value: float | int | None,
    *,
    fallback: int = 30,
) -> int:
    try:
        candidate = int(value) if value is not None else int(fallback)
    except (TypeError, ValueError):
        candidate = int(fallback)
    return max(5, min(24 * 60, candidate))


async def expire_overdue_configs() -> None:
    if not is_connected():
        logger.warning("Expiry job skipped: MongoDB not connected")
        return

    db = get_db()
    now = datetime.now(timezone.utc)
    query = {
        "status": ClientConfigStatus.ACTIVE.value,
        "expires_at": {"$lt": now},
    }

    cursor = db.client_configs.find(query)
    docs = await cursor.to_list(length=500)
    if not docs:
        logger.debug("Expiry job: no overdue active configs")
        return

    logger.info("Expiry job: found %s overdue config(s) at %s", len(docs), now.isoformat())

    for doc in docs:
        client_name = doc.get("client_name")
        config_id = doc.get("_id")
        try:
            await revoke_client(client_name)
            await db.client_configs.update_one(
                {"_id": config_id},
                {
                    "$set": {
                        "status": ClientConfigStatus.REVOKED.value,
                        "revoked_at": now,
                        "is_online": False,
                    }
                },
            )
            logger.info(
                "Auto-revoked expired config id=%s client_name=%s at %s",
                config_id,
                client_name,
                now.isoformat(),
            )
        except OpenVPNError:
            logger.exception(
                "Auto-revoke failed for config id=%s client_name=%s",
                config_id,
                client_name,
            )
        except Exception:
            logger.exception(
                "Unexpected error auto-revoking config id=%s client_name=%s",
                config_id,
                client_name,
            )


async def job_collect_metrics() -> None:
    try:
        from app.services.metrics_collector import collect_host_metrics

        await collect_host_metrics(force_persist=True)
    except Exception:
        logger.exception("Host metrics collection failed")


async def job_sync_connections() -> None:
    try:
        from app.services.metrics_collector import sync_connections

        await sync_connections()
    except Exception:
        logger.exception("Connection sync failed")


async def job_panel_backup() -> None:
    try:
        from app.services.backup import run_scheduled_backup

        result = await run_scheduled_backup()
        if result:
            logger.info(
                "Panel backup ok name=%s size=%s",
                result.get("name"),
                result.get("size_bytes"),
            )
    except Exception:
        logger.exception("Panel backup job failed")


def reschedule_analytics_jobs(
    seconds: float | int | None,
    *,
    run_soon: bool = True,
) -> None:
    """Update metrics + connection poll intervals to match analytics refresh."""
    global _scheduler
    if _scheduler is None:
        return

    interval = normalize_analytics_refresh_seconds(seconds)
    metrics_iv = background_metrics_interval(interval)
    connections_iv = background_connections_interval(interval)
    next_run = datetime.now(timezone.utc) if run_soon else None
    for job_id, func, iv in (
        (JOB_METRICS, job_collect_metrics, metrics_iv),
        (JOB_CONNECTIONS, job_sync_connections, connections_iv),
    ):
        try:
            _scheduler.add_job(
                func,
                trigger=IntervalTrigger(seconds=iv),
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                next_run_time=next_run,
            )
        except Exception:
            logger.exception("Failed to reschedule job %s", job_id)
            continue
    logger.info(
        "Analytics collector: ui=%ss metrics_bg=%ss connections_bg=%ss",
        interval,
        metrics_iv,
        connections_iv,
    )


def reschedule_backup_job(
    minutes: float | int | None,
    *,
    run_soon: bool = False,
) -> None:
    """Update panel zip backup interval from site settings."""
    global _scheduler
    if _scheduler is None:
        return

    from datetime import timedelta

    interval = normalize_backup_interval_minutes(minutes)
    if run_soon:
        next_run = datetime.now(timezone.utc)
    else:
        next_run = datetime.now(timezone.utc) + timedelta(minutes=interval)
    try:
        _scheduler.add_job(
            job_panel_backup,
            trigger=IntervalTrigger(minutes=interval),
            id=JOB_BACKUP,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=next_run,
        )
        logger.info(
            "Panel backup interval set to %sm (next_run=%s)",
            interval,
            next_run.isoformat(),
        )
    except Exception:
        logger.exception("Failed to reschedule panel backup job")


async def apply_analytics_interval_from_db() -> None:
    """Load site setting (or env fallback) and apply to running jobs."""
    settings = get_settings()
    fallback = normalize_analytics_refresh_seconds(settings.METRICS_POLL_SECONDS)
    seconds = fallback
    try:
        if is_connected():
            from app.services.site_settings import get_site_settings

            data, _ = await get_site_settings(use_cache=False)
            seconds = normalize_analytics_refresh_seconds(
                data.analytics_refresh_seconds,
                fallback=fallback,
            )
    except Exception:
        logger.exception(
            "Could not load analytics_refresh_seconds; using %ss",
            fallback,
        )
        seconds = fallback
    reschedule_analytics_jobs(seconds, run_soon=True)


async def apply_backup_interval_from_db() -> None:
    """Load backup interval from site settings (or env) and apply."""
    settings = get_settings()
    fallback = normalize_backup_interval_minutes(
        getattr(settings, "BACKUP_INTERVAL_MINUTES", 30)
    )
    minutes = fallback
    try:
        if is_connected():
            from app.services.site_settings import get_site_settings

            data, _ = await get_site_settings(use_cache=False)
            minutes = normalize_backup_interval_minutes(
                data.backup_interval_minutes,
                fallback=fallback,
            )
    except Exception:
        logger.exception(
            "Could not load backup_interval_minutes; using %sm",
            fallback,
        )
        minutes = fallback
    # Wait one interval after process start (avoid backup storm on restart).
    reschedule_backup_job(minutes, run_soon=False)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    settings = get_settings()
    minutes = max(1, int(settings.CONFIG_EXPIRY_CHECK_INTERVAL_MINUTES))
    # Env is the boot default; site setting overrides via apply_analytics_interval_from_db
    interval = normalize_analytics_refresh_seconds(settings.METRICS_POLL_SECONDS)
    metrics_iv = background_metrics_interval(interval)
    connections_iv = background_connections_interval(interval)
    backup_minutes = normalize_backup_interval_minutes(
        getattr(settings, "BACKUP_INTERVAL_MINUTES", 30)
    )
    from datetime import timedelta

    backup_next = datetime.now(timezone.utc) + timedelta(minutes=backup_minutes)

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        expire_overdue_configs,
        trigger=IntervalTrigger(minutes=minutes),
        id="expire_overdue_configs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        job_collect_metrics,
        trigger=IntervalTrigger(seconds=metrics_iv),
        id=JOB_METRICS,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        job_sync_connections,
        trigger=IntervalTrigger(seconds=connections_iv),
        id=JOB_CONNECTIONS,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        job_panel_backup,
        trigger=IntervalTrigger(minutes=backup_minutes),
        id=JOB_BACKUP,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=backup_next,
    )
    _scheduler.start()
    logger.info(
        "APScheduler started: expiry=%sm metrics_bg=%ss connections_bg=%ss backup=%sm",
        minutes,
        metrics_iv,
        connections_iv,
        backup_minutes,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("APScheduler stopped")
