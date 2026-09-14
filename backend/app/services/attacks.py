"""Attack pcap inventory, event ingest, Discord notify, and config sync."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.db import get_db, is_connected
from app.services.site_settings import get_site_settings

logger = logging.getLogger(__name__)

ATTACK_EVENTS_COLLECTION = "attack_events"
SAFE_PCAP_NAME = re.compile(r"^[\w.\-]+\.pcap$")

DEFAULT_CAPTURE_DIR = "/var/log/popout-vpn/captures"
DEFAULT_EVENTS_DIR = "/var/log/popout-vpn/events"
CONFIG_PATH = Path("/etc/popout-vpn/attacks.conf")
SERVICE_NAME = "popout-attacks"

# Discord webhook file limit is 25 MiB; keep headroom under that.
DEFAULT_DISCORD_MAX_ATTACH = 24 * 1024 * 1024

DEFAULT_ATTACK_EMBED_JSON = """{
  "embeds": [
    {
      "title": "Attack {{severity}} — {{service}}",
      "color": {{color}},
      "fields": [
        {"name": "Severity", "value": "{{severity}}", "inline": true},
        {"name": "Kind", "value": "{{kind}}", "inline": true},
        {"name": "PPS", "value": "{{pps}}", "inline": true},
        {"name": "BPS", "value": "{{bps}}", "inline": true},
        {"name": "Capture", "value": "`{{pcap_name}}`\\nSize: {{pcap_size}}\\nAttached: {{pcap_attached}}", "inline": false},
        {"name": "Unique sources", "value": "{{unique_srcs}}", "inline": true},
        {"name": "Filter", "value": "`{{bpf}}`", "inline": false}
      ],
      "footer": {"text": "Popout VPN"},
      "timestamp": "{{detected_at}}"
    }
  ]
}"""

SEVERITY_COLORS = {
    "WARNING": 16776960,
    "ATTACK": 16766720,
    "SEVERE": 15158332,
    "CRITICAL": 10038562,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def capture_dir() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "ATTACK_PCAP_DIR", None) or DEFAULT_CAPTURE_DIR)


def events_dir() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "ATTACK_EVENTS_DIR", None) or DEFAULT_EVENTS_DIR)


def ensure_attack_dirs() -> None:
    capture_dir().mkdir(parents=True, exist_ok=True)
    events_dir().mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _format_rate(n: float, unit: str) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} M{unit}"
    if n >= 1_000:
        return f"{n / 1_000:.2f} K{unit}"
    return f"{n:.0f} {unit}"


def attack_service_label() -> str:
    """Discord {{service}} / attacks.conf affected_service label for this host."""
    import socket

    return (
        (os.environ.get("ATTACK_AFFECTED_SERVICE") or "").strip()
        or socket.gethostname()
        or "vpn"
    )


async def _wait_for_pcap_ready(
    path: Path,
    *,
    min_bytes: int = 64,
    stable_checks: int = 3,
    interval: float = 1.0,
    max_wait: float = 180.0,
) -> int:
    """
    Wait until the capture file has data and its size stops growing
    (tcpdump finished or paused), so Discord gets a complete .pcap.
    """
    import asyncio
    import time

    deadline = time.monotonic() + max_wait
    last = -1
    stable = 0
    size = 0
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size >= min_bytes:
            if size == last:
                stable += 1
                if stable >= stable_checks:
                    return size
            else:
                stable = 0
                last = size
        await asyncio.sleep(interval)
    try:
        return path.stat().st_size
    except OSError:
        return size


def _prepare_discord_payload(
    payload_text: str,
    *,
    attach_name: str | None = None,
) -> str:
    """Ensure payload JSON is valid; declare attachment id 0 when uploading a file."""
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return payload_text
    if not isinstance(payload, dict):
        return payload_text
    if attach_name:
        payload["attachments"] = [{"id": 0, "filename": attach_name}]
    elif "attachments" in payload and payload["attachments"] in ([], None):
        # Empty attachments array can block file uploads on some Discord clients.
        payload.pop("attachments", None)
    return json.dumps(payload, ensure_ascii=False)


async def write_attacks_conf() -> None:
    """Write /etc/popout-vpn/attacks.conf from site settings."""
    ensure_attack_dirs()
    site, _ = await get_site_settings(use_cache=False)
    settings = get_settings()

    webhook = (site.attack_discord_webhook_url or "").strip()
    if not webhook and CONFIG_PATH.is_file():
        try:
            text = CONFIG_PATH.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if line.startswith("webhook_url="):
                    webhook = line.split("=", 1)[1].strip().strip("'\"")
                    break
        except OSError:
            pass

    bpf = (site.attack_pcap_bpf or "").strip()
    if not bpf:
        host = (settings.OPENVPN_SERVER_HOST or "").strip()
        if host and re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", host):
            bpf = f"ip dst host {host}"
    retention = int(site.attack_pcap_retention_days)
    packets = int(site.attack_pcap_packet_count)
    affected = attack_service_label()

    body = "\n".join(
        [
            "# Managed by Popout VPN panel — overwritten on site-settings save.",
            'interface="eth0"',
            "threshold_warning=25000",
            "threshold_attack=50000",
            "threshold_severe=100000",
            "threshold_critical=250000",
            "required_hits=5",
            "cooldown=300",
            "enable_capture=true",
            f"capture_dir={_shell_quote(str(capture_dir()))}",
            f"events_dir={_shell_quote(str(events_dir()))}",
            f"capture_filter={_shell_quote(bpf)}",
            f"capture_packet_count={packets}",
            "capture_snaplength=65535",
            "capture_promiscuous=true",
            f"retention_days={retention}",
            f"webhook_url={_shell_quote(webhook)}",
            'mitigation_system="Provider DDoS Protection"',
            f"affected_service={_shell_quote(affected)}",
            'footer_text="Popout VPN"',
            "",
        ]
    )
    CONFIG_PATH.write_text(body, encoding="utf-8", newline="\n")
    try:
        os.chmod(CONFIG_PATH, 0o640)
    except OSError:
        pass


def try_restart_attacks_service() -> None:
    if shutil.which("systemctl") is None:
        return
    try:
        subprocess.run(
            ["systemctl", "restart", SERVICE_NAME],
            check=False,
            timeout=30,
            capture_output=True,
        )
    except Exception:
        logger.exception("Failed to restart %s", SERVICE_NAME)


def list_pcap_files() -> list[dict[str, Any]]:
    ensure_attack_dirs()
    root = capture_dir()
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for path in sorted(root.glob("*.pcap"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            st = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "name": path.name,
                "size_bytes": int(st.st_size),
                "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                "path": str(path),
            }
        )
    return rows


def resolve_pcap(name: str) -> Path:
    if not SAFE_PCAP_NAME.match(name):
        raise ValueError("Invalid pcap name")
    root = capture_dir().resolve()
    path = (root / name).resolve()
    if path.parent != root:
        raise ValueError("Invalid pcap path")
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


def delete_pcap(name: str) -> None:
    path = resolve_pcap(name)
    path.unlink(missing_ok=False)


def invalidate_attack_stats_cache() -> None:
    global _attack_stats_cache, _attack_stats_cache_at
    _attack_stats_cache = None
    _attack_stats_cache_at = None


async def delete_pcap_and_events(name: str) -> int:
    """Delete a .pcap capture file; keep attack_events as durable analytics.

    Returns how many event rows were marked capture-unavailable (not deleted).
    """
    delete_pcap(name)
    marked = 0
    if is_connected():
        db = get_db()
        result = await db[ATTACK_EVENTS_COLLECTION].update_many(
            {"pcap_file": name},
            {
                "$set": {
                    "pcap_available": False,
                    "pcap_deleted_at": _utcnow(),
                }
            },
        )
        marked = int(result.modified_count)
    # Counts are unchanged, but listing joins disk metadata — drop any stale cache.
    invalidate_attack_stats_cache()
    return marked


def _parse_event_ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return _utcnow()


def _render_embed_template(template: str, values: dict[str, str]) -> str:
    out = template
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", val)
    return out


async def _send_discord_for_event(doc: dict[str, Any]) -> bool:
    site, _ = await get_site_settings(use_cache=True)
    webhook = (site.attack_discord_webhook_url or "").strip()
    if not webhook:
        return True  # nothing to send; treat as done

    template = (site.attack_discord_embed_json or "").strip() or DEFAULT_ATTACK_EMBED_JSON
    max_attach = int(
        getattr(site, "attack_discord_max_attach_bytes", None)
        or DEFAULT_DISCORD_MAX_ATTACH
    )
    # Discord webhook hard limit is 25 MiB; never attempt above that.
    max_attach = max(0, min(max_attach, 25 * 1024 * 1024))

    severity = str(doc.get("severity") or "UNKNOWN")
    pps = int(doc.get("pps") or 0)
    bps = int(doc.get("bps") or 0)
    pcap_name = str(doc.get("pcap_file") or "") or "none"
    pcap_path: Path | None = None
    pcap_size = 0
    if doc.get("pcap_file"):
        try:
            pcap_path = resolve_pcap(str(doc["pcap_file"]))
        except (ValueError, FileNotFoundError, OSError):
            pcap_path = None

    # Event is written when capture starts — wait for a finished/stable pcap.
    if pcap_path is not None:
        pcap_size = await _wait_for_pcap_ready(pcap_path)
        if pcap_size < 64:
            return False  # still empty; retry on next ingest cycle

    attach = bool(pcap_path and 64 <= pcap_size <= max_attach and max_attach > 0)

    unique_srcs = "NA"
    if pcap_path is not None and pcap_size >= 64:
        try:
            from app.services.pcap_analysis import count_unique_pcap_sources

            unique_srcs = str(count_unique_pcap_sources(pcap_path))
        except Exception:
            logger.exception("Could not count unique sources for Discord embed")
            unique_srcs = "NA"

    values = {
        "severity": severity,
        "kind": str(doc.get("kind") or "detection"),
        "pps": _format_rate(float(pps), "pps"),
        "bps": _format_rate(float(bps), "B/s"),
        "pps_raw": str(pps),
        "bps_raw": str(bps),
        "pcap_name": pcap_name,
        "pcap_size": _format_bytes(pcap_size) if pcap_size else "n/a",
        "pcap_attached": (
            "yes"
            if attach
            else (
                "too large"
                if pcap_size > max_attach
                else ("missing" if not pcap_path else "no")
            )
        ),
        "unique_srcs": unique_srcs,
        "bpf": str(doc.get("bpf") or "ALL TRAFFIC") or "ALL TRAFFIC",
        "service": attack_service_label(),
        "color": str(SEVERITY_COLORS.get(severity.upper(), 15158332)),
        "detected_at": _parse_event_ts(doc.get("detected_at")).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "interface": str(doc.get("interface") or "eth0"),
        "packet_count": str(int(doc.get("packet_count") or 0)),
    }

    try:
        payload_text = _render_embed_template(template, values)
        json.loads(payload_text)
    except Exception:
        logger.exception("Invalid attack Discord embed JSON after render")
        payload_text = _render_embed_template(DEFAULT_ATTACK_EMBED_JSON, values)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            if attach and pcap_path is not None:
                file_bytes = pcap_path.read_bytes()
                if len(file_bytes) < 64:
                    return False
                payload_text = _prepare_discord_payload(
                    payload_text, attach_name=pcap_path.name
                )
                files = {
                    "files[0]": (
                        pcap_path.name,
                        file_bytes,
                        "application/vnd.tcpdump.pcap",
                    )
                }
                resp = await client.post(
                    webhook,
                    data={"payload_json": payload_text},
                    files=files,
                )
            else:
                payload_text = _prepare_discord_payload(payload_text)
                resp = await client.post(
                    webhook,
                    content=payload_text,
                    headers={"Content-Type": "application/json"},
                )
            if resp.status_code >= 400:
                logger.warning(
                    "Discord webhook failed status=%s body=%s attach=%s pcap=%s size=%s",
                    resp.status_code,
                    resp.text[:300],
                    attach,
                    pcap_name,
                    pcap_size,
                )
                return False
        logger.info(
            "Discord webhook ok attach=%s pcap=%s size=%s",
            attach,
            pcap_name,
            pcap_size,
        )
        return True
    except Exception:
        logger.exception("Discord webhook send failed")
        return False


def empty_pcap_bytes() -> bytes:
    """Classic libpcap file with global header only (0 packets)."""
    import struct

    # magic, vmaj, vmin, thiszone, sigfigs, snaplen, network(Ethernet)
    return struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)


async def send_test_attack_webhook(
    *,
    webhook_url: str | None = None,
    embed_json: str | None = None,
) -> dict[str, Any]:
    """
    Send a Discord webhook using the detection embed template with NA placeholders.
    Attaches a fake empty .pcap (0 packets) so the test mirrors a real detection upload.
    Optional overrides use the in-form (unsaved) webhook / embed JSON.
    """
    site, _ = await get_site_settings(use_cache=True)
    webhook = (webhook_url if webhook_url is not None else site.attack_discord_webhook_url or "").strip()
    if not webhook:
        raise ValueError("Discord webhook URL is not configured")

    template = (
        (embed_json if embed_json is not None else site.attack_discord_embed_json or "").strip()
        or DEFAULT_ATTACK_EMBED_JSON
    )

    pcap_name = "test_empty_0pkts.pcap"
    pcap_bytes = empty_pcap_bytes()
    na = "NA"
    values = {
        "severity": na,
        "kind": "test",
        "pps": na,
        "bps": na,
        "pps_raw": na,
        "bps_raw": na,
        "pcap_name": pcap_name,
        "pcap_size": _format_bytes(len(pcap_bytes)),
        "pcap_attached": "yes",
        "unique_srcs": na,
        "bpf": na,
        "service": attack_service_label(),
        "color": "0",
        "detected_at": _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interface": na,
        "packet_count": "0",
    }

    try:
        payload_text = _render_embed_template(template, values)
        json.loads(payload_text)
    except Exception:
        logger.exception("Invalid attack Discord embed JSON for webhook test")
        payload_text = _render_embed_template(DEFAULT_ATTACK_EMBED_JSON, values)

    payload_text = _prepare_discord_payload(payload_text, attach_name=pcap_name)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            webhook,
            data={"payload_json": payload_text},
            files={
                "files[0]": (
                    pcap_name,
                    pcap_bytes,
                    "application/vnd.tcpdump.pcap",
                )
            },
        )
        if resp.status_code >= 400:
            detail = (resp.text or "")[:300]
            raise RuntimeError(
                f"Discord webhook returned HTTP {resp.status_code}"
                + (f": {detail}" if detail else "")
            )

    return {
        "ok": True,
        "message": (
            "Test webhook sent (NA placeholders + empty 0-packet .pcap attached)"
        ),
        "service": values["service"],
        "pcap_name": pcap_name,
    }


async def ingest_attack_events() -> int:
    """Ingest JSON event files written by attacks.sh into Mongo."""
    if not is_connected():
        return 0
    ensure_attack_dirs()
    db = get_db()
    ingested = 0
    for path in sorted(events_dir().glob("attack_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Skipping bad attack event file %s", path)
            continue
        event_id = str(data.get("id") or path.stem)
        doc = {
            "_id": event_id,
            "detected_at": _parse_event_ts(data.get("detected_at")),
            "severity": str(data.get("severity") or "UNKNOWN"),
            "pps": int(data.get("pps") or 0),
            "bps": int(data.get("bps") or 0),
            "kind": str(data.get("kind") or "detection"),
            "interface": str(data.get("interface") or "eth0"),
            "pcap_file": str(data.get("pcap_file") or "") or None,
            "packet_count": int(data.get("packet_count") or 0),
            "bpf": str(data.get("bpf") or ""),
            "ingested_at": _utcnow(),
            "discord_sent": False,
            "pcap_available": True,
        }
        result = await db[ATTACK_EVENTS_COLLECTION].update_one(
            {"_id": event_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        if result.upserted_id is not None or result.matched_count:
            ingested += 1
        try:
            processed = events_dir() / "processed"
            processed.mkdir(parents=True, exist_ok=True)
            path.rename(processed / path.name)
        except OSError:
            try:
                path.unlink()
            except OSError:
                pass
    await dispatch_pending_discord()
    return ingested


async def dispatch_pending_discord() -> int:
    if not is_connected():
        return 0
    db = get_db()
    cursor = db[ATTACK_EVENTS_COLLECTION].find({"discord_sent": {"$ne": True}}).limit(50)
    sent = 0
    async for doc in cursor:
        ok = await _send_discord_for_event(doc)
        if ok:
            await db[ATTACK_EVENTS_COLLECTION].update_one(
                {"_id": doc["_id"]},
                {"$set": {"discord_sent": True, "discord_sent_at": _utcnow()}},
            )
            sent += 1
    return sent


async def list_attack_events(
    limit: int = 200,
    *,
    ingest: bool = True,
) -> list[dict[str, Any]]:
    if ingest:
        await ingest_attack_events()
    if not is_connected():
        return []
    db = get_db()
    cursor = (
        db[ATTACK_EVENTS_COLLECTION]
        .find({})
        .sort("detected_at", -1)
        .limit(limit)
    )
    rows: list[dict[str, Any]] = []
    pcap_index = {p["name"]: p for p in list_pcap_files()}
    async for doc in cursor:
        pcap_name = doc.get("pcap_file")
        pcap_meta = pcap_index.get(pcap_name) if pcap_name else None
        available = bool(pcap_meta) and doc.get("pcap_available", True) is not False
        rows.append(
            {
                "id": str(doc["_id"]),
                "detected_at": doc.get("detected_at"),
                "severity": doc.get("severity") or "UNKNOWN",
                "kind": doc.get("kind") or "detection",
                "pps": int(doc.get("pps") or 0),
                "bps": int(doc.get("bps") or 0),
                "interface": doc.get("interface") or "eth0",
                "pcap_file": pcap_name,
                "pcap_available": available,
                "pcap_size_bytes": (
                    int(pcap_meta["size_bytes"]) if pcap_meta else None
                ),
                "pcap_modified_at": (
                    pcap_meta["modified_at"] if pcap_meta else None
                ),
                "bpf": doc.get("bpf") or "",
                "discord_sent": bool(doc.get("discord_sent")),
            }
        )
    return rows


_attack_stats_cache: dict[str, int] | None = None
_attack_stats_cache_at: float | None = None


async def attack_stats(
    *,
    ingest: bool = True,
    max_cache_age: float = 0.0,
) -> dict[str, int]:
    """Return attack counts. Optionally skip filesystem ingest and use a short TTL cache."""
    global _attack_stats_cache, _attack_stats_cache_at
    import time

    now = time.monotonic()
    if (
        max_cache_age > 0
        and _attack_stats_cache is not None
        and _attack_stats_cache_at is not None
        and (now - _attack_stats_cache_at) < max_cache_age
    ):
        return dict(_attack_stats_cache)

    if ingest:
        await ingest_attack_events()
    if not is_connected():
        return {"attacks_lifetime": 0, "attacks_24h": 0}
    db = get_db()
    lifetime = await db[ATTACK_EVENTS_COLLECTION].count_documents({})
    since = _utcnow() - timedelta(hours=24)
    last_24h = await db[ATTACK_EVENTS_COLLECTION].count_documents(
        {"detected_at": {"$gte": since}}
    )
    result = {"attacks_lifetime": int(lifetime), "attacks_24h": int(last_24h)}
    _attack_stats_cache = dict(result)
    _attack_stats_cache_at = now
    return result
