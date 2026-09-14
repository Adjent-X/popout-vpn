from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_admin, require_db
from app.models.analytics import (
    AnalyticsOverview,
    BandwidthToDate,
    HostMetricsLatest,
    MetricPoint,
    MonthlyBandwidth,
)
from app.models.documents import ClientConfigStatus
from app.services.admins import is_sub_admin
from app.services.metrics_collector import (
    ensure_fresh_metrics,
    get_bandwidth_to_date,
    get_latest_metrics,
    get_metrics_series,
    get_monthly_bandwidth,
)
from app.services.openvpn_status import parse_status
from app.services.scheduler import normalize_analytics_refresh_seconds
from app.services.site_settings import get_site_settings

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
logger = logging.getLogger(__name__)

# Short TTL caches so Live (250ms) ticks stay memory-bound.
_side_cache: dict[str, Any] = {}
_side_cache_at: float = 0.0
_SIDE_TTL_LIVE = 2.0
_SIDE_TTL_NORMAL = 5.0


def _host_metrics_latest(latest_raw: dict[str, Any] | None) -> HostMetricsLatest | None:
    if not latest_raw:
        return None
    try:
        return HostMetricsLatest(
            ts=latest_raw["ts"],
            cpu_percent=float(latest_raw.get("cpu_percent") or 0),
            mem_total=int(latest_raw.get("mem_total") or 0),
            mem_used=int(latest_raw.get("mem_used") or 0),
            mem_percent=float(latest_raw.get("mem_percent") or 0),
            disk_total=int(latest_raw.get("disk_total") or 0),
            disk_used=int(latest_raw.get("disk_used") or 0),
            disk_percent=float(latest_raw.get("disk_percent") or 0),
            net_bytes_sent=int(latest_raw.get("net_bytes_sent") or 0),
            net_bytes_recv=int(latest_raw.get("net_bytes_recv") or 0),
            net_bytes_sent_rate=float(latest_raw.get("net_bytes_sent_rate") or 0),
            net_bytes_recv_rate=float(latest_raw.get("net_bytes_recv_rate") or 0),
            net_packets_sent=int(latest_raw.get("net_packets_sent") or 0),
            net_packets_recv=int(latest_raw.get("net_packets_recv") or 0),
            net_packets_sent_rate=float(latest_raw.get("net_packets_sent_rate") or 0),
            net_packets_recv_rate=float(latest_raw.get("net_packets_recv_rate") or 0),
            eth0_bytes_sent=int(latest_raw.get("eth0_bytes_sent") or 0),
            eth0_bytes_recv=int(latest_raw.get("eth0_bytes_recv") or 0),
            eth0_packets_sent=int(latest_raw.get("eth0_packets_sent") or 0),
            eth0_packets_recv=int(latest_raw.get("eth0_packets_recv") or 0),
            eth0_bytes_sent_rate=float(latest_raw.get("eth0_bytes_sent_rate") or 0),
            eth0_bytes_recv_rate=float(latest_raw.get("eth0_bytes_recv_rate") or 0),
            eth0_packets_sent_rate=float(latest_raw.get("eth0_packets_sent_rate") or 0),
            eth0_packets_recv_rate=float(latest_raw.get("eth0_packets_recv_rate") or 0),
            tun0_bytes_sent=int(latest_raw.get("tun0_bytes_sent") or 0),
            tun0_bytes_recv=int(latest_raw.get("tun0_bytes_recv") or 0),
            tun0_packets_sent=int(latest_raw.get("tun0_packets_sent") or 0),
            tun0_packets_recv=int(latest_raw.get("tun0_packets_recv") or 0),
            tun0_bytes_sent_rate=float(latest_raw.get("tun0_bytes_sent_rate") or 0),
            tun0_bytes_recv_rate=float(latest_raw.get("tun0_bytes_recv_rate") or 0),
            tun0_packets_sent_rate=float(latest_raw.get("tun0_packets_sent_rate") or 0),
            tun0_packets_recv_rate=float(latest_raw.get("tun0_packets_recv_rate") or 0),
            load_avg=latest_raw.get("load_avg"),
        )
    except Exception:
        return None


async def _load_side_stats(
    *,
    admin: dict,
    db,
    full_admin: bool,
) -> dict[str, Any]:
    owner_filter: dict[str, Any] = {}
    if is_sub_admin(admin):
        owner_filter = {"owner_admin_id": admin["_id"]}

    my_configs = await db.client_configs.find(
        owner_filter,
        {"client_name": 1, "status": 1, "is_online": 1},
    ).to_list(length=2000)

    my_cns = {c.get("client_name") for c in my_configs if c.get("client_name")}
    status = await asyncio.to_thread(parse_status)
    if is_sub_admin(admin):
        clients_online = sum(1 for c in status.clients if c.common_name in my_cns)
    else:
        clients_online = len(status.clients)

    total = len(my_configs)
    revoked = sum(
        1 for c in my_configs if c.get("status") == ClientConfigStatus.REVOKED.value
    )
    active = total - revoked

    attacks_lifetime = 0
    attacks_24h = 0
    if full_admin:
        try:
            from app.services.attacks import attack_stats

            # Live overview: read counts only; ingest runs on Attacks page / slower polls.
            stats = await attack_stats(ingest=False, max_cache_age=10.0)
            attacks_lifetime = stats["attacks_lifetime"]
            attacks_24h = stats["attacks_24h"]
        except Exception:
            logger.exception("attack_stats failed")

    bandwidth_monthly: list[MonthlyBandwidth] = []
    bandwidth_to_date: BandwidthToDate | None = None
    try:
        bandwidth_monthly = [
            MonthlyBandwidth(**row) for row in await get_monthly_bandwidth(months=12)
        ]
        bandwidth_to_date = BandwidthToDate(**await get_bandwidth_to_date())
    except Exception:
        logger.exception("bandwidth totals failed")

    return {
        "clients_online": clients_online,
        "clients_total_active": active,
        "configs_total": total,
        "configs_revoked": revoked,
        "attacks_lifetime": attacks_lifetime,
        "attacks_24h": attacks_24h,
        "bandwidth_to_date": bandwidth_to_date,
        "bandwidth_monthly": bandwidth_monthly,
    }


@router.get("/overview", response_model=AnalyticsOverview)
async def analytics_overview(
    hours: int = Query(default=24, ge=1, le=168),
    max_age: float | None = Query(
        default=None,
        description="Collect a fresh host sample if latest is older than this many seconds",
    ),
    include_series: bool = Query(
        default=True,
        description="When false, skip history series (cheaper for Live polling)",
    ),
    admin: dict = Depends(get_current_admin),
    db=Depends(require_db),
) -> AnalyticsOverview:
    global _side_cache, _side_cache_at

    age = None
    if max_age is not None:
        age = normalize_analytics_refresh_seconds(max_age)
    else:
        try:
            site, _ = await get_site_settings(use_cache=True)
            age = normalize_analytics_refresh_seconds(site.analytics_refresh_seconds)
        except Exception:
            age = 10.0

    live_poll = (not include_series) and age is not None and age < 2.5

    try:
        await ensure_fresh_metrics(max_age_seconds=age)
    except Exception:
        logger.exception("ensure_fresh_metrics failed (max_age=%s)", age)

    latest_raw = await get_latest_metrics()
    latest = _host_metrics_latest(latest_raw)

    series: list[MetricPoint] = []
    if include_series:
        series_raw = await get_metrics_series(hours=hours)
        series = [MetricPoint(**row) for row in series_raw]

    full_admin = not is_sub_admin(admin)
    cache_key = f"{'full' if full_admin else 'sub'}:{admin.get('_id')}"
    now = time.monotonic()
    ttl = _SIDE_TTL_LIVE if live_poll else _SIDE_TTL_NORMAL
    cached = _side_cache.get(cache_key)
    if cached is not None and (now - _side_cache_at) < ttl:
        side = cached
    else:
        side = await _load_side_stats(admin=admin, db=db, full_admin=full_admin)
        _side_cache[cache_key] = side
        _side_cache_at = now

    return AnalyticsOverview(
        latest=latest,
        series=series,
        clients_online=int(side["clients_online"]),
        clients_total_active=int(side["clients_total_active"]),
        configs_total=int(side["configs_total"]),
        configs_revoked=int(side["configs_revoked"]),
        attacks_lifetime=int(side["attacks_lifetime"]),
        attacks_24h=int(side["attacks_24h"]),
        bandwidth_to_date=side.get("bandwidth_to_date"),
        bandwidth_monthly=side.get("bandwidth_monthly") or [],
    )
