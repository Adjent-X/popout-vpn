"""Background collector: host metrics, OpenVPN connections, WAN IP auto-revoke."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import psutil

from app.core.config import get_settings
from app.db import get_db, is_connected
from app.models.documents import ClientConfigStatus
from app.services.openvpn import OpenVPNError, revoke_client
from app.services.openvpn_status import parse_ipp, parse_status, tail_client_events
from app.services.site_settings import get_site_settings

logger = logging.getLogger(__name__)

HOST_METRICS_COLLECTION = "host_metrics"
CONNECTION_EVENTS_COLLECTION = "connection_events"
BANDWIDTH_MONTHLY_COLLECTION = "bandwidth_monthly"
BANDWIDTH_TOTALS_COLLECTION = "bandwidth_totals"
BANDWIDTH_TO_DATE_ID = "to_date"
TRACKED_NICS = ("eth0", "tun0")
BANDWIDTH_MONTHS_KEEP = 12
_BW_KEYS = (
    "eth0_bytes_sent",
    "eth0_bytes_recv",
    "tun0_bytes_sent",
    "tun0_bytes_recv",
)

_last_net = psutil.net_io_counters()
_last_nics: dict[str, Any] = {}
_last_net_at = datetime.now(timezone.utc)
_fresh_lock = asyncio.Lock()
_latest_cache: dict[str, Any] | None = None
_last_persist_at: datetime | None = None
_last_metrics_prune_at: datetime | None = None
_bw_prev: dict[str, int] = {}
# Prime non-blocking CPU readings for Live mode.
psutil.cpu_percent(interval=None)

# Match scheduler.METRICS_PERSIST_MIN_SECONDS — avoid circular import at module load.
_PERSIST_MIN_SECONDS = 2.5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _rate(curr: float, prev: float, elapsed: float) -> float:
    return max(0.0, (curr - prev) / elapsed)


def _nic_snapshot(
    name: str,
    curr: Any | None,
    prev: Any | None,
    elapsed: float,
) -> dict[str, float | int]:
    if curr is None:
        return {
            f"{name}_bytes_sent": 0,
            f"{name}_bytes_recv": 0,
            f"{name}_packets_sent": 0,
            f"{name}_packets_recv": 0,
            f"{name}_bytes_sent_rate": 0.0,
            f"{name}_bytes_recv_rate": 0.0,
            f"{name}_packets_sent_rate": 0.0,
            f"{name}_packets_recv_rate": 0.0,
        }
    prev_sent = getattr(prev, "bytes_sent", curr.bytes_sent) if prev else curr.bytes_sent
    prev_recv = getattr(prev, "bytes_recv", curr.bytes_recv) if prev else curr.bytes_recv
    prev_ps = getattr(prev, "packets_sent", curr.packets_sent) if prev else curr.packets_sent
    prev_pr = getattr(prev, "packets_recv", curr.packets_recv) if prev else curr.packets_recv
    return {
        f"{name}_bytes_sent": int(curr.bytes_sent),
        f"{name}_bytes_recv": int(curr.bytes_recv),
        f"{name}_packets_sent": int(curr.packets_sent),
        f"{name}_packets_recv": int(curr.packets_recv),
        f"{name}_bytes_sent_rate": _rate(curr.bytes_sent, prev_sent, elapsed),
        f"{name}_bytes_recv_rate": _rate(curr.bytes_recv, prev_recv, elapsed),
        f"{name}_packets_sent_rate": _rate(curr.packets_sent, prev_ps, elapsed),
        f"{name}_packets_recv_rate": _rate(curr.packets_recv, prev_pr, elapsed),
    }


async def collect_host_metrics(*, force_persist: bool = False) -> dict[str, Any]:
    """Snapshot CPU/mem/disk/network. Always updates in-memory latest.

    Mongo writes are throttled to ~every 2.5s so Live (sub-second) UI polling
    does not flood the database. Background jobs pass force_persist=True.
    """
    global _last_net, _last_nics, _last_net_at, _latest_cache, _last_persist_at

    if not is_connected():
        return {}

    settings = get_settings()
    now = _utcnow()

    # Live (<1s) uses non-blocking CPU; slower samples get a short measurement window.
    def _sample() -> dict[str, Any]:
        # Non-blocking after prime; keeps Live mode cheap on the VPN subnet.
        cpu_interval = 0.05 if force_persist else None
        cpu = psutil.cpu_percent(interval=cpu_interval)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()
        pernic = psutil.net_io_counters(pernic=True)
        try:
            load_avg: list[float] | None = list(psutil.getloadavg())
        except (AttributeError, OSError):
            load_avg = None
        return {
            "cpu": cpu,
            "mem": mem,
            "disk": disk,
            "net": net,
            "pernic": pernic,
            "load_avg": load_avg,
        }

    sample = await asyncio.to_thread(_sample)
    mem = sample["mem"]
    disk = sample["disk"]
    net = sample["net"]
    pernic: dict[str, Any] = sample["pernic"] or {}
    elapsed = max((now - _last_net_at).total_seconds(), 0.001)
    bytes_sent_rate = _rate(net.bytes_sent, _last_net.bytes_sent, elapsed)
    bytes_recv_rate = _rate(net.bytes_recv, _last_net.bytes_recv, elapsed)
    packets_sent_rate = _rate(net.packets_sent, _last_net.packets_sent, elapsed)
    packets_recv_rate = _rate(net.packets_recv, _last_net.packets_recv, elapsed)

    nic_fields: dict[str, float | int] = {}
    next_nics: dict[str, Any] = {}
    for name in TRACKED_NICS:
        curr = pernic.get(name)
        nic_fields.update(_nic_snapshot(name, curr, _last_nics.get(name), elapsed))
        if curr is not None:
            next_nics[name] = curr

    _last_net = net
    _last_nics = next_nics
    _last_net_at = now

    doc: dict[str, Any] = {
        "ts": now,
        "cpu_percent": sample["cpu"],
        "mem_total": mem.total,
        "mem_used": mem.used,
        "mem_percent": mem.percent,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_percent": disk.percent,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
        "net_packets_sent": net.packets_sent,
        "net_packets_recv": net.packets_recv,
        "net_bytes_sent_rate": bytes_sent_rate,
        "net_bytes_recv_rate": bytes_recv_rate,
        "net_packets_sent_rate": packets_sent_rate,
        "net_packets_recv_rate": packets_recv_rate,
        "load_avg": sample["load_avg"],
        **nic_fields,
    }

    _latest_cache = dict(doc)

    should_persist = force_persist
    if not should_persist:
        if _last_persist_at is None:
            should_persist = True
        else:
            since = (now - _last_persist_at).total_seconds()
            should_persist = since >= _PERSIST_MIN_SECONDS

    if should_persist:
        db = get_db()
        await db[HOST_METRICS_COLLECTION].insert_one(dict(doc))
        _last_persist_at = now
        # Retention prune at most every 5 minutes (was every insert — expensive).
        global _last_metrics_prune_at
        prune_due = (
            _last_metrics_prune_at is None
            or (now - _last_metrics_prune_at).total_seconds() >= 300
        )
        if prune_due:
            retain_h = max(1, int(settings.METRICS_RETENTION_HOURS))
            cutoff = now - timedelta(hours=retain_h)
            await db[HOST_METRICS_COLLECTION].delete_many({"ts": {"$lt": cutoff}})
            _last_metrics_prune_at = now
        try:
            await _accumulate_monthly_bandwidth(db, doc=doc, elapsed=elapsed, now=now)
        except Exception:
            logger.exception("Monthly bandwidth accumulate failed")

    return doc


def _counter_delta(curr: int, prev: int | None) -> int:
    if prev is None:
        return 0
    if curr < prev:
        # Counter reset (reboot / NIC reinit) — don't invent a huge spike.
        return 0
    return curr - prev


async def _accumulate_monthly_bandwidth(
    db: Any,
    *,
    doc: dict[str, Any],
    elapsed: float,
    now: datetime,
) -> None:
    """Roll NIC byte counters into to-date + calendar-month totals."""
    global _bw_prev

    deltas: dict[str, int] = {}
    for key in _BW_KEYS:
        curr = int(doc.get(key) or 0)
        deltas[key] = _counter_delta(curr, _bw_prev.get(key))
        _bw_prev[key] = curr

    if not any(deltas.values()) and elapsed <= 0:
        return

    inc = {
        "eth0_bytes_sent": deltas["eth0_bytes_sent"],
        "eth0_bytes_recv": deltas["eth0_bytes_recv"],
        "tun0_bytes_sent": deltas["tun0_bytes_sent"],
        "tun0_bytes_recv": deltas["tun0_bytes_recv"],
        "sample_seconds": max(0.0, float(elapsed)),
    }

    # Lifetime / to-date (never pruned) — counting starts from first sample after enable.
    await db[BANDWIDTH_TOTALS_COLLECTION].update_one(
        {"_id": BANDWIDTH_TO_DATE_ID},
        {
            "$inc": inc,
            "$set": {"updated_at": now},
            "$setOnInsert": {"started_at": now},
        },
        upsert=True,
    )

    month_id = f"{now.year:04d}-{now.month:02d}"
    await db[BANDWIDTH_MONTHLY_COLLECTION].update_one(
        {"_id": month_id},
        {
            "$inc": inc,
            "$set": {
                "year": now.year,
                "month": now.month,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    # Drop months older than ~12 calendar months
    cutoff = (now.replace(day=1) - timedelta(days=370)).strftime("%Y-%m")
    await db[BANDWIDTH_MONTHLY_COLLECTION].delete_many({"_id": {"$lt": cutoff}})


def _bandwidth_row(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not doc:
        return {
            "eth0_bytes_sent": 0,
            "eth0_bytes_recv": 0,
            "tun0_bytes_sent": 0,
            "tun0_bytes_recv": 0,
            "total_bytes": 0,
            "sample_seconds": 0.0,
            "avg_bps": 0.0,
            "started_at": None,
            "updated_at": None,
        }
    eth0_sent = int(doc.get("eth0_bytes_sent") or 0)
    eth0_recv = int(doc.get("eth0_bytes_recv") or 0)
    tun0_sent = int(doc.get("tun0_bytes_sent") or 0)
    tun0_recv = int(doc.get("tun0_bytes_recv") or 0)
    total_bytes = eth0_sent + eth0_recv
    sample_seconds = float(doc.get("sample_seconds") or 0)
    avg_bps = (total_bytes * 8 / sample_seconds) if sample_seconds > 0 else 0.0
    return {
        "eth0_bytes_sent": eth0_sent,
        "eth0_bytes_recv": eth0_recv,
        "tun0_bytes_sent": tun0_sent,
        "tun0_bytes_recv": tun0_recv,
        "total_bytes": total_bytes,
        "sample_seconds": sample_seconds,
        "avg_bps": avg_bps,
        "started_at": doc.get("started_at") or doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


async def get_bandwidth_to_date() -> dict[str, Any]:
    """All WAN bandwidth counted since tracking began (from now onward)."""
    if not is_connected():
        return _bandwidth_row(None)
    db = get_db()
    doc = await db[BANDWIDTH_TOTALS_COLLECTION].find_one(
        {"_id": BANDWIDTH_TO_DATE_ID}
    )
    return _bandwidth_row(doc)


async def get_monthly_bandwidth(*, months: int = 12) -> list[dict[str, Any]]:
    """Return up to `months` of WAN/VPN byte totals + average bps."""
    if not is_connected():
        return []
    db = get_db()
    keep = max(1, min(24, int(months)))
    cursor = (
        db[BANDWIDTH_MONTHLY_COLLECTION]
        .find({})
        .sort("_id", -1)
        .limit(keep)
    )
    docs = await cursor.to_list(length=keep)
    out: list[dict[str, Any]] = []
    for doc in reversed(docs):
        row = _bandwidth_row(doc)
        year = int(doc.get("year") or 0)
        month = int(doc.get("month") or 0)
        sample_seconds = float(row["sample_seconds"] or 0)
        if sample_seconds < 1 and year and month:
            import calendar

            days = calendar.monthrange(year, month)[1]
            sample_seconds = float(days * 86400)
            total_bytes = int(row["total_bytes"])
            row["sample_seconds"] = sample_seconds
            row["avg_bps"] = (
                (total_bytes * 8 / sample_seconds) if sample_seconds > 0 else 0.0
            )
        out.append(
            {
                "id": str(doc.get("_id")),
                "year": year,
                "month": month,
                **{k: row[k] for k in (
                    "eth0_bytes_sent",
                    "eth0_bytes_recv",
                    "tun0_bytes_sent",
                    "tun0_bytes_recv",
                    "total_bytes",
                    "sample_seconds",
                    "avg_bps",
                )},
            }
        )
    return out


def _logging_enabled_for_config(doc: dict[str, Any], site_default: bool) -> bool:
    override = doc.get("wan_ip_logging_enabled")
    if override is None:
        return site_default
    return bool(override)


async def _record_event(
    db: Any,
    *,
    client_name: str,
    config_id: Any,
    event: str,
    wan_ip: str | None,
    vpn_ip: str | None,
    at: datetime,
    store_wan: bool,
) -> None:
    payload = {
        "client_name": client_name,
        "config_id": config_id,
        "event": event,
        "wan_ip": wan_ip if store_wan else None,
        "vpn_ip": vpn_ip,
        "at": at,
        "wan_logged": bool(store_wan and wan_ip),
    }
    await db[CONNECTION_EVENTS_COLLECTION].insert_one(payload)


async def _maybe_auto_revoke(
    db: Any,
    *,
    doc: dict[str, Any],
    site,
    now: datetime,
) -> None:
    if doc.get("status") == ClientConfigStatus.REVOKED.value:
        return
    if not _logging_enabled_for_config(doc, site.wan_ip_logging_enabled):
        return

    limit = int(site.unique_wan_ip_limit or 3)
    window_h = int(site.unique_wan_ip_window_hours or 24)
    since = now - timedelta(hours=window_h)

    pipeline = [
        {
            "$match": {
                "client_name": doc["client_name"],
                "at": {"$gte": since},
                "wan_ip": {"$nin": [None, ""]},
                "wan_logged": True,
            }
        },
        {"$group": {"_id": "$wan_ip"}},
        {"$count": "n"},
    ]
    rows = await db[CONNECTION_EVENTS_COLLECTION].aggregate(pipeline).to_list(length=1)
    unique = int(rows[0]["n"]) if rows else 0
    if unique < limit:
        return

    client_name = doc["client_name"]
    logger.warning(
        "Auto-revoking %s: %s unique WAN IPs in %sh (limit %s)",
        client_name,
        unique,
        window_h,
        limit,
    )
    try:
        await revoke_client(client_name)
    except OpenVPNError:
        logger.exception("Auto-revoke OpenVPN failed for %s", client_name)
        return

    await db.client_configs.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "status": ClientConfigStatus.REVOKED.value,
                "revoked_at": now,
                "is_online": False,
            }
        },
    )
    await _record_event(
        db,
        client_name=client_name,
        config_id=doc["_id"],
        event="auto_revoke",
        wan_ip=None,
        vpn_ip=doc.get("vpn_ip"),
        at=now,
        store_wan=False,
    )


async def sync_connections() -> None:
    """
    Poll OpenVPN status + ipp + event log; update client_configs; enforce WAN IP limits.
    """
    if not is_connected():
        return

    db = get_db()
    site, _ = await get_site_settings(use_cache=True)
    now = _utcnow()
    ipp = parse_ipp()
    status = parse_status()
    from collections import defaultdict

    online_by_cn: dict[str, list] = defaultdict(list)
    for c in status.clients:
        online_by_cn[c.common_name].append(c)

    # Ingest new file events (dedupe by client_name+event+at+wan)
    file_events = tail_client_events()
    for ev in file_events[-200:]:
        exists = await db[CONNECTION_EVENTS_COLLECTION].find_one(
            {
                "client_name": ev["client_name"],
                "event": ev["event"],
                "at": ev["at"],
                "wan_ip": ev.get("wan_ip"),
            }
        )
        if exists:
            continue
        cfg = await db.client_configs.find_one({"client_name": ev["client_name"]})
        if cfg is None:
            continue
        store_wan = _logging_enabled_for_config(cfg, site.wan_ip_logging_enabled)
        await _record_event(
            db,
            client_name=ev["client_name"],
            config_id=cfg["_id"],
            event=ev["event"],
            wan_ip=ev.get("wan_ip"),
            vpn_ip=ev.get("vpn_ip") or ipp.get(ev["client_name"]),
            at=ev["at"],
            store_wan=store_wan,
        )
        if store_wan and ev.get("event") == "connect" and ev.get("wan_ip"):
            await db.client_configs.update_one(
                {"_id": cfg["_id"]},
                {
                    "$set": {
                        "last_wan_ip": ev["wan_ip"],
                        "last_connected_at": ev["at"],
                        "vpn_ip": ev.get("vpn_ip") or ipp.get(ev["client_name"]) or cfg.get("vpn_ip"),
                    }
                },
            )
            cfg = await db.client_configs.find_one({"_id": cfg["_id"]}) or cfg
            await _maybe_auto_revoke(db, doc=cfg, site=site, now=now)

    # Refresh online flags + sessions from live status / ipp for all configs
    cursor = db.client_configs.find({})
    docs = await cursor.to_list(length=2000)
    for doc in docs:
        cn = doc.get("client_name")
        if not cn:
            continue
        sessions_live = online_by_cn.get(cn) or []
        store_wan = _logging_enabled_for_config(doc, site.wan_ip_logging_enabled)
        session_payload = [
            {
                "vpn_ip": s.vpn_ip,
                # Always surface live WAN for the sessions list (ops UI).
                # Historical logging / last_wan_ip still respects store_wan.
                "wan_ip": s.wan_ip,
                "connected_since": s.connected_since or now,
                "bytes_received": int(s.bytes_received or 0),
                "bytes_sent": int(s.bytes_sent or 0),
            }
            for s in sessions_live
        ]
        # Prefer a live session VPN IP; fall back to ipp / stored
        vpn_ip = None
        if len(sessions_live) == 1:
            vpn_ip = sessions_live[0].vpn_ip
        elif len(sessions_live) > 1:
            vpn_ip = None  # ambiguous under duplicate-cn — use active_sessions
        if not vpn_ip:
            vpn_ip = ipp.get(cn) or doc.get("vpn_ip")

        updates: dict[str, Any] = {
            "is_online": bool(sessions_live)
            and doc.get("status") != ClientConfigStatus.REVOKED.value,
            "vpn_ip": vpn_ip,
            "session_count": len(sessions_live),
            "active_sessions": session_payload,
        }
        if sessions_live:
            newest = max(
                (s.connected_since for s in sessions_live if s.connected_since),
                default=None,
            )
            updates["last_connected_at"] = newest or now
            # Track latest WAN for UI summary (first session with a WAN)
            if store_wan:
                for s in sessions_live:
                    if s.wan_ip:
                        if s.wan_ip != doc.get("last_wan_ip"):
                            await _record_event(
                                db,
                                client_name=cn,
                                config_id=doc["_id"],
                                event="seen",
                                wan_ip=s.wan_ip,
                                vpn_ip=s.vpn_ip or vpn_ip,
                                at=now,
                                store_wan=True,
                            )
                        updates["last_wan_ip"] = s.wan_ip
                        break
            # Unique-WAN auto-revoke does not apply in duplicate-cn (many users, one CN)
            if not site.duplicate_cn_mode and store_wan and updates.get("last_wan_ip"):
                merged = {**doc, **updates}
                await _maybe_auto_revoke(db, doc=merged, site=site, now=now)

        await db.client_configs.update_one({"_id": doc["_id"]}, {"$set": updates})

        # Keep warp-routing ipset in sync once a VPN IP is known (single-session only)
        if (
            get_settings().WARP_ROUTING_ENABLED
            and doc.get("warp_routing_enabled")
            and vpn_ip
            and vpn_ip != doc.get("vpn_ip")
            and len(sessions_live) <= 1
        ):
            try:
                from app.services.warp_routing import sync_warp_routing

                await sync_warp_routing(vpn_ip=vpn_ip, enabled=True)
            except Exception:
                logger.exception(
                    "Failed to sync warp-routing ipset for %s (%s)", cn, vpn_ip
                )


async def get_latest_metrics(*, allow_stale_mongo: bool = True) -> dict[str, Any] | None:
    """Prefer in-memory Live sample; only hit Mongo when cache is cold/stale."""
    cache = _latest_cache
    if cache is not None:
        cache_age = _age_seconds(cache.get("ts"))
        # Hot path for Live polling — avoid a remote Mongo round-trip every tick.
        if cache_age is not None and cache_age < 5.0:
            out = dict(cache)
            out.setdefault("id", "live")
            return out

    mongo_doc: dict[str, Any] | None = None
    if allow_stale_mongo and is_connected():
        db = get_db()
        mongo_doc = await db[HOST_METRICS_COLLECTION].find_one(sort=[("ts", -1)])
        if mongo_doc:
            mongo_doc = dict(mongo_doc)
            mongo_doc["id"] = str(mongo_doc.pop("_id"))

    if cache is not None:
        cache_age = _age_seconds(cache.get("ts"))
        mongo_age = _age_seconds(mongo_doc.get("ts") if mongo_doc else None)
        if mongo_doc is None or (
            cache_age is not None
            and (mongo_age is None or cache_age <= mongo_age)
        ):
            out = dict(cache)
            out.setdefault("id", "live")
            return out

    return mongo_doc


def _age_seconds(ts: Any) -> float | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (_utcnow() - ts).total_seconds())
    return None


async def ensure_fresh_metrics(*, max_age_seconds: float) -> None:
    """Collect a new host sample if the latest is older than max_age_seconds."""
    if not is_connected():
        return
    max_age = max(0.05, float(max_age_seconds))

    # Memory-only check first (no Mongo) so Live ticks stay cheap.
    cache = _latest_cache
    age = _age_seconds(cache.get("ts") if cache else None)
    if age is not None and age < max_age:
        return

    async with _fresh_lock:
        cache = _latest_cache
        age = _age_seconds(cache.get("ts") if cache else None)
        if age is not None and age < max_age:
            return
        await collect_host_metrics(force_persist=False)


_SERIES_FIELDS = (
    "cpu_percent",
    "mem_percent",
    "disk_percent",
    "net_bytes_sent_rate",
    "net_bytes_recv_rate",
    "net_packets_sent_rate",
    "net_packets_recv_rate",
    "eth0_bytes_sent_rate",
    "eth0_bytes_recv_rate",
    "eth0_packets_sent_rate",
    "eth0_packets_recv_rate",
    "tun0_bytes_sent_rate",
    "tun0_bytes_recv_rate",
    "tun0_packets_sent_rate",
    "tun0_packets_recv_rate",
)

_SERIES_PROJECTION = {"_id": 0, "ts": 1, **{f: 1 for f in _SERIES_FIELDS}}
_series_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_SERIES_CACHE_TTL = 8.0
_SERIES_CACHE_MAX_KEYS = 2


def _store_series_cache(hours: int, rows: list[dict[str, Any]]) -> None:
    """Keep at most a couple of chart windows in RAM."""
    import time as _time

    now_mono = _time.monotonic()
    _series_cache[hours] = (now_mono, rows)
    if len(_series_cache) <= _SERIES_CACHE_MAX_KEYS:
        return
    # Drop oldest entries beyond the cap
    ordered = sorted(_series_cache.items(), key=lambda kv: kv[1][0])
    for key, _ in ordered[: max(0, len(ordered) - _SERIES_CACHE_MAX_KEYS)]:
        _series_cache.pop(key, None)


async def get_metrics_series(*, hours: int = 24) -> list[dict[str, Any]]:
    """Return ~720 evenly bucketed points for the requested window (Mongo-side)."""
    if not is_connected():
        return []

    import time

    hours = max(1, min(int(hours), 168))
    cached = _series_cache.get(hours)
    now_mono = time.monotonic()
    if cached is not None and (now_mono - cached[0]) < _SERIES_CACHE_TTL:
        return list(cached[1])

    db = get_db()
    since = _utcnow() - timedelta(hours=hours)
    max_points = 720
    span_ms = max(hours * 3600 * 1000, max_points)
    bucket_ms = max(1000, span_ms // max_points)

    group: dict[str, Any] = {
        "_id": {
            "$subtract": [
                {"$toLong": "$ts"},
                {"$mod": [{"$toLong": "$ts"}, bucket_ms]},
            ]
        },
        "ts": {"$first": "$ts"},
    }
    for field in _SERIES_FIELDS:
        group[field] = {"$avg": f"${field}"}

    pipeline = [
        {"$match": {"ts": {"$gte": since}}},
        {"$project": _SERIES_PROJECTION},
        {"$sort": {"ts": 1}},
        {"$group": group},
        {"$sort": {"_id": 1}},
        {"$limit": max_points},
    ]
    docs = await db[HOST_METRICS_COLLECTION].aggregate(pipeline).to_list(
        length=max_points
    )
    out: list[dict[str, Any]] = []
    for doc in docs:
        row: dict[str, Any] = {"ts": doc.get("ts")}
        for field in _SERIES_FIELDS:
            val = doc.get(field)
            row[field] = float(val) if val is not None else None
        out.append(row)

    _store_series_cache(hours, out)
    return list(out)
