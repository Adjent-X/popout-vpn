"""Parse OpenVPN status file, ipp.txt, and client-events.log."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ConnectedClient:
    common_name: str
    vpn_ip: str | None = None
    wan_ip: str | None = None
    connected_since: datetime | None = None
    bytes_received: int = 0
    bytes_sent: int = 0


@dataclass
class StatusSnapshot:
    clients: list[ConnectedClient] = field(default_factory=list)
    updated_at: datetime | None = None


def _as_utc_from_unix(ts: int | float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def parse_ipp(path: str | Path | None = None) -> dict[str, str]:
    """Map common_name -> vpn IP from ifconfig-pool-persist."""
    settings = get_settings()
    p = Path(path or settings.OPENVPN_IPP_PATH)
    mapping: dict[str, str] = {}
    if not p.is_file():
        return mapping
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 2 and parts[0] and parts[1]:
                mapping[parts[0]] = parts[1]
    except OSError as exc:
        logger.warning("Could not read ipp.txt %s: %s", p, exc)
    return mapping


def _extract_wan_ip(real_address: str) -> str | None:
    """
    OpenVPN Real Address may be:
      1.2.3.4:1194
      udp4:1.2.3.4:56442
      tcp4:1.2.3.4:443
      [2001:db8::1]:1194
    """
    real = (real_address or "").strip()
    if not real:
        return None
    # Strip proto prefix (udp/tcp/udp4/tcp6/…)
    if real.startswith(("udp", "tcp")) and ":" in real:
        real = real.split(":", 1)[1]
    if real.startswith("["):
        end = real.find("]")
        if end > 0:
            return real[1:end] or None
    # IPv4 host:port — take host; bare IP has no colon
    if real.count(":") == 1:
        return real.split(":", 1)[0] or None
    # IPv6 without brackets (rare in status) — return as-is
    return real or None


def parse_status(path: str | Path | None = None) -> StatusSnapshot:
    """
    Parse OpenVPN status-version 2/3 file.
    Falls back to empty snapshot if missing.
    """
    settings = get_settings()
    p = Path(path or settings.OPENVPN_STATUS_PATH)
    snap = StatusSnapshot(updated_at=datetime.now(timezone.utc))
    if not p.is_file():
        return snap

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Could not read status file %s: %s", p, exc)
        return snap

    clients: list[ConnectedClient] = []
    # STATUS VERSION 2/3: CLIENT_LIST lines
    # CLIENT_LIST,Common Name,Real Address,Virtual Address,...,Connected Since (unix),...
    for line in text.splitlines():
        if line.startswith("CLIENT_LIST,"):
            parts = line.split(",")
            if len(parts) < 6:
                continue
            cn = parts[1].strip()
            real = parts[2].strip()
            virt = parts[3].strip()
            wan_ip = _extract_wan_ip(real)
            bytes_recv = 0
            bytes_sent = 0
            connected_since = None
            try:
                # v2: idx 5 connected since (human), 7/8 bytes OR unix depending on version
                # Prefer numeric unix fields when present
                for idx in (7, 8, 5, 6):
                    if idx < len(parts) and parts[idx].strip().isdigit():
                        val = int(parts[idx].strip())
                        if val > 1_000_000_000:  # unix ts
                            connected_since = _as_utc_from_unix(val)
                            break
                if len(parts) > 5 and parts[5].strip().isdigit() and int(parts[5]) < 1_000_000_000:
                    bytes_recv = int(parts[5])
                if len(parts) > 6 and parts[6].strip().isdigit() and int(parts[6]) < 1_000_000_000:
                    bytes_sent = int(parts[6])
                # Common v2 layout: ...,Bytes Received,Bytes Sent,Connected Since,...
                if len(parts) >= 9:
                    if parts[5].isdigit():
                        bytes_recv = int(parts[5])
                    if parts[6].isdigit():
                        bytes_sent = int(parts[6])
                    if parts[8].isdigit() and int(parts[8]) > 1_000_000_000:
                        connected_since = _as_utc_from_unix(int(parts[8]))
            except ValueError:
                pass
            if cn and cn != "UNDEF":
                clients.append(
                    ConnectedClient(
                        common_name=cn,
                        vpn_ip=virt or None,
                        wan_ip=wan_ip or None,
                        connected_since=connected_since,
                        bytes_received=bytes_recv,
                        bytes_sent=bytes_sent,
                    )
                )
        elif line.startswith("HEADER,CLIENT_LIST"):
            continue
        elif line.startswith("TIME,"):
            # TIME,Human,Unix
            parts = line.split(",")
            if len(parts) >= 3 and parts[2].strip().isdigit():
                snap.updated_at = _as_utc_from_unix(int(parts[2]))

    # Legacy status format (no CLIENT_LIST)
    if not clients and "OpenVPN CLIENT LIST" in text:
        section = None
        for line in text.splitlines():
            if line.startswith("OpenVPN CLIENT LIST"):
                section = "clients"
                continue
            if line.startswith("ROUTING TABLE"):
                section = "routing"
                continue
            if line.startswith("GLOBAL STATS") or line.startswith("END"):
                section = None
                continue
            if section == "clients" and line and not line.startswith("Updated") and not line.startswith("Common Name"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    cn = parts[0]
                    wan = parts[1].split(":")[0]
                    clients.append(ConnectedClient(common_name=cn, wan_ip=wan))
            if section == "routing" and line and not line.startswith("Virtual Address"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    vip, cn = parts[0], parts[1]
                    for c in clients:
                        if c.common_name == cn and not c.vpn_ip:
                            c.vpn_ip = vip

    snap.clients = clients
    return snap


def tail_client_events(
    path: str | Path | None = None,
    *,
    max_lines: int = 5000,
) -> list[dict]:
    """
    Read client-events.log lines:
      ISO8601,connect|disconnect,common_name,wan_ip,vpn_ip
    """
    settings = get_settings()
    p = Path(path or settings.OPENVPN_CLIENT_EVENTS_PATH)
    if not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events: list[dict] = []
    for line in lines[-max_lines:]:
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 4:
            continue
        ts_raw, event, cn, wan = parts[0], parts[1], parts[2], parts[3]
        vpn = parts[4] if len(parts) > 4 else None
        try:
            at = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        events.append(
            {
                "at": at,
                "event": event,
                "client_name": cn,
                "wan_ip": wan or None,
                "vpn_ip": vpn or None,
            }
        )
    return events
