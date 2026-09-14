"""tshark line-by-line pcap analysis: heuristics, protocol %, source IP geo."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.services.attacks import resolve_pcap

logger = logging.getLogger(__name__)

MAX_PACKETS = 80_000
TSHARK_TIMEOUT_SEC = 120
TOP_N = 15
GEO_BATCH = 100

# Amplification / reflection: traffic FROM these source ports (reflector replies).
AMP_SRC_PORTS = {
    53: "DNS",
    123: "NTP",
    161: "SNMP",
    389: "CLDAP",
    1900: "SSDP",
    11211: "Memcached",
    19: "Chargen",
    17: "QOTD",
    520: "RIPv1",
    3702: "WS-Discovery",
    137: "NetBIOS-NS",
    138: "NetBIOS-DGM",
    5353: "mDNS",
    27015: "Steam",
    27960: "Quake",
    5683: "CoAP",
}

# TCP services commonly abused for SYN-ACK / ACK reflection.
TCP_REFLECT_SRC_PORTS = {
    80: "HTTP",
    443: "HTTPS",
    8080: "HTTP-Alt",
    8443: "HTTPS-Alt",
    22: "SSH",
    25: "SMTP",
    110: "POP3",
    143: "IMAP",
    389: "LDAP",
    445: "SMB",
    3389: "RDP",
    21: "FTP",
    23: "Telnet",
    53: "DNS-TCP",
}

# Backward-compatible alias used by older UI labels.
AMP_PORTS = AMP_SRC_PORTS

US_STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}


def _analysis_cache_path(pcap: Path) -> Path:
    cache_dir = pcap.parent / ".analysis"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{pcap.name}.json"


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 2)


def _split_field(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def _parse_port(raw: str) -> int | None:
    for part in _split_field(raw):
        try:
            return int(part)
        except ValueError:
            continue
    return None


def _frame_tokens(frame_protocols: str) -> set[str]:
    return {t for t in (frame_protocols or "").lower().split(":") if t}


def _has_tunnel(frame_protocols: str) -> bool:
    tokens = _frame_tokens(frame_protocols)
    if "gre" in tokens or "ipip" in tokens or "6in4" in tokens:
        return True
    # Multiple IP layers (outer + inner)
    parts = [t for t in (frame_protocols or "").lower().split(":") if t]
    return parts.count("ip") + parts.count("ip6") >= 2


def _is_private_ip(ip: str) -> bool:
    """True for RFC1918 / link-local / CGNAT / loopback (IPv4) and unique-local (IPv6)."""
    s = (ip or "").strip().lower()
    if not s or s == "unknown":
        return True
    if ":" in s:
        return s.startswith("fc") or s.startswith("fd") or s.startswith("fe80")
    parts = s.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if a == 10 or a == 127:
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 100 and 64 <= b <= 127:  # CGNAT
        return True
    if a == 169 and b == 254:
        return True
    return False


def _effective_src(
    ip_src_raw: str,
    ipv6_src_raw: str,
    frame_protocols: str,
) -> str:
    """
    Attack attribution source IP.

    For GRE / IP-in-IP victim captures, the outer address is the internet-facing
    peer; inner addresses are often RFC1918 and must not be used for geo / unique
    source counts. Prefer the outermost public IP.
    """
    ips = _split_field(ip_src_raw) + _split_field(ipv6_src_raw)
    if not ips:
        return "unknown"
    if _has_tunnel(frame_protocols) and len(ips) > 1:
        for ip in ips:  # outer → inner
            if not _is_private_ip(ip):
                return ip
        return ips[0]
    # Non-tunnel: still prefer a public address if multiple were captured
    for ip in ips:
        if not _is_private_ip(ip):
            return ip
    return ips[0]


def _proto_name(ip_proto: str, frame_protocols: str) -> str:
    tokens = _frame_tokens(frame_protocols)
    if "udp" in tokens:
        return "UDP"
    if "tcp" in tokens:
        return "TCP"
    if "icmp" in tokens or "icmpv6" in tokens:
        return "ICMP"
    if "gre" in tokens:
        return "GRE"

    proto_raw = (ip_proto or "").strip()
    n = -1
    if proto_raw:
        try:
            n = int(proto_raw.split(",")[0])
        except (TypeError, ValueError):
            n = -1

    if n == 17:
        return "UDP"
    if n == 6:
        return "TCP"
    if n == 1 or n == 58:
        return "ICMP"
    if n == 47:
        return "GRE"
    if n == 4:
        return "IPIP"

    has_ip = "ip" in tokens or "ip6" in tokens or n >= 0 or bool(proto_raw)
    if has_ip:
        # IP present but no recognizable L4 → bare IP / odd IP protocol
        if n > 0:
            return f"IP/{n}"
        return "IP"  # no proto / proto unset
    return "Raw"


_SIGNATURE_IDS = frozenset(
    {
        "udp_amplification",
        "udp_flood",
        "gre_udp_flood",
        "tcp_reflection",
        "syn_flood",
        "ack_flood",
        "rst_flood",
        "fin_flood",
        "connection_flood",
        "icmp_flood",
        "flag_flood_null",
        "flag_flood_xmas",
        "flag_flood_syn_fin",
    }
)


def _protocol_packet_breakdown(
    *,
    total: int,
    proto_packets: Counter[str],
) -> list[dict[str, Any]]:
    """
    Fallback when no attack signature matched.
    Emphasize bare IP (no upper proto) and raw frames; otherwise summarize mix.
    """
    labels: list[dict[str, Any]] = []
    if total <= 0:
        return labels

    bare_ip = int(proto_packets.get("IP", 0))
    raw_pkts = int(proto_packets.get("Raw", 0)) + int(proto_packets.get("Other", 0))
    odd_ip = sum(
        pkts
        for name, pkts in proto_packets.items()
        if name.startswith("IP/")
    )

    # Detailed breakdown for unclassified IP / raw packet types
    for name, pkts in proto_packets.most_common():
        if pkts <= 0:
            continue
        pct = _pct(pkts, total)
        if name == "IP":
            labels.append(
                {
                    "id": "pkt_ip_no_proto",
                    "label": (
                        f"IP packets with no upper protocol "
                        f"({pct}% / {pkts:,} pkts)"
                    ),
                    "confidence": min(95.0, max(25.0, round(pct, 1))),
                }
            )
        elif name.startswith("IP/"):
            ip_n = name.split("/", 1)[1]
            labels.append(
                {
                    "id": f"pkt_ip_proto_{ip_n}",
                    "label": (
                        f"IP protocol {ip_n} packets "
                        f"({pct}% / {pkts:,} pkts)"
                    ),
                    "confidence": min(95.0, max(25.0, round(pct, 1))),
                }
            )
        elif name in ("Raw", "Other"):
            labels.append(
                {
                    "id": "pkt_raw",
                    "label": (
                        f"Raw / non-IP frames "
                        f"({pct}% / {pkts:,} pkts)"
                    ),
                    "confidence": min(95.0, max(25.0, round(pct, 1))),
                }
            )

    unclassified = bare_ip + raw_pkts + odd_ip
    unclassified_pct = _pct(unclassified, total)

    # If little/no bare-IP/raw, still break down by protocol mix
    if unclassified_pct < 5 and not labels:
        parts: list[str] = []
        for name, pkts in proto_packets.most_common(5):
            if pkts <= 0:
                continue
            pct = _pct(pkts, total)
            if pct < 1:
                continue
            parts.append(f"{name} {pct:.0f}%")
            labels.append(
                {
                    "id": f"proto_{name.lower().replace('/', '_')}",
                    "label": f"{name} traffic ({pct}% / {pkts:,} pkts)",
                    "confidence": min(90.0, max(20.0, round(pct, 1))),
                }
            )
        if not labels:
            labels.append(
                {
                    "id": "proto_mix",
                    "label": "No signature matched — empty or unclassified capture",
                    "confidence": 20.0,
                }
            )
        elif parts:
            labels.insert(
                0,
                {
                    "id": "no_signature",
                    "label": "No attack signature matched — protocol mix: "
                    + ", ".join(parts),
                    "confidence": 40.0,
                },
            )
    elif labels:
        labels.insert(
            0,
            {
                "id": "no_signature",
                "label": (
                    "No attack signature matched — packet-type breakdown "
                    f"(unclassified {unclassified_pct}%)"
                ),
                "confidence": 45.0,
            },
        )

    return labels


def _l7_hint(
    frame_protocols: str,
    src_port: int | None,
    dst_port: int | None,
    *,
    proto: str,
    flags: set[str] | None = None,
) -> str | None:
    tokens = _frame_tokens(frame_protocols)
    # Application / amp hints only — GRE is encapsulation, not an L7 service.
    for token in (
        "dns",
        "ntp",
        "http",
        "tls",
        "quic",
        "ssdp",
        "mdns",
        "snmp",
        "dhcp",
        "ldap",
        "rtcp",
        "rtp",
        "openvpn",
    ):
        if token in tokens:
            return token.upper()

    flags = flags or set()
    if proto == "UDP" and src_port in AMP_SRC_PORTS:
        return AMP_SRC_PORTS[src_port]
    if proto == "TCP" and src_port in TCP_REFLECT_SRC_PORTS:
        label = TCP_REFLECT_SRC_PORTS[src_port]
        if flags & {"SYN", "ACK"} or flags & {"ACK"} or flags & {"RST"}:
            return f"{label}-REFLECT"
        return label
    if proto == "UDP" and dst_port in AMP_SRC_PORTS:
        # Query toward amplifiers (less common in inbound victim captures)
        return f"{AMP_SRC_PORTS[dst_port]}-QUERY"
    if "gre" in tokens and proto in {"UDP", "TCP", "ICMP"}:
        return f"GRE-{proto}"
    return None


def _parse_tcp_flags(raw: str) -> set[str]:
    """Interpret tshark tcp.flags hex or mnemonic."""
    flags: set[str] = set()
    if not raw:
        return flags
    # occurrence=a may yield comma-separated values; use first TCP header
    s = raw.strip().split(",")[0].strip().lower()
    if s.startswith("0x"):
        try:
            val = int(s, 16)
        except ValueError:
            return flags
        if val & 0x02:
            flags.add("SYN")
        if val & 0x10:
            flags.add("ACK")
        if val & 0x01:
            flags.add("FIN")
        if val & 0x04:
            flags.add("RST")
        if val & 0x08:
            flags.add("PSH")
        if val & 0x20:
            flags.add("URG")
        if val == 0:
            flags.add("NULL")
        return flags
    for name in ("syn", "ack", "fin", "rst", "psh", "urg", "null"):
        if name in s:
            flags.add(name.upper())
    if not flags and s in {"0", "0x00", "······"}:
        flags.add("NULL")
    return flags


def _run_tshark(pcap: Path) -> list[str]:
    tshark = shutil.which("tshark")
    if not tshark:
        raise RuntimeError(
            "tshark is not installed on this host. Install wireshark-common / tshark."
        )
    cmd = [
        tshark,
        "-r",
        str(pcap),
        "-T",
        "fields",
        "-E",
        "separator=\t",
        "-E",
        "occurrence=a",
        "-e",
        "frame.time_epoch",
        "-e",
        "frame.len",
        "-e",
        "ip.src",
        "-e",
        "ipv6.src",
        "-e",
        "ip.dst",
        "-e",
        "ip.proto",
        "-e",
        "udp.srcport",
        "-e",
        "udp.dstport",
        "-e",
        "tcp.srcport",
        "-e",
        "tcp.dstport",
        "-e",
        "tcp.flags",
        "-e",
        "frame.protocols",
        "-e",
        "gre.proto",
        "-c",
        str(MAX_PACKETS),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=TSHARK_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("tshark timed out analyzing capture") from exc
    if proc.returncode not in (0, 2):
        err = (proc.stderr or "").strip()[:400]
        if not proc.stdout.strip():
            raise RuntimeError(f"tshark failed: {err or proc.returncode}")
        logger.warning("tshark exit=%s stderr=%s", proc.returncode, err)
    return proc.stdout.splitlines()


def count_unique_pcap_sources(pcap: Path, *, max_packets: int = MAX_PACKETS) -> int:
    """Fast unique effective-source count for Discord embeds."""
    if not pcap.is_file():
        return 0
    tshark = shutil.which("tshark")
    if not tshark:
        return 0
    cmd = [
        tshark,
        "-r",
        str(pcap),
        "-T",
        "fields",
        "-E",
        "separator=\t",
        "-E",
        "occurrence=a",
        "-e",
        "ip.src",
        "-e",
        "ipv6.src",
        "-e",
        "frame.protocols",
        "-c",
        str(max_packets),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=min(60, TSHARK_TIMEOUT_SEC),
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.exception("unique source count failed for %s", pcap)
        return 0
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 3:
            parts.append("")
        src = _effective_src(parts[0], parts[1], parts[2])
        if src and src != "unknown":
            seen.add(src)
    return len(seen)


def _lookup_geo(ips: list[str]) -> dict[str, dict[str, str | None]]:
    """Batch GeoIP via ip-api.com (no key). Returns ip -> {country, region, city}."""
    out: dict[str, dict[str, str | None]] = {}
    if not ips:
        return out
    candidates = [ip for ip in ips if ":" not in ip and not ip.startswith("10.")]
    if not candidates:
        return out
    try:
        with httpx.Client(timeout=20.0) as client:
            for i in range(0, len(candidates), GEO_BATCH):
                batch = candidates[i : i + GEO_BATCH]
                payload = [
                    {
                        "query": ip,
                        "fields": "status,country,countryCode,region,regionName,city,query",
                    }
                    for ip in batch
                ]
                resp = client.post("http://ip-api.com/batch", json=payload)
                if resp.status_code >= 400:
                    logger.warning("ip-api batch failed status=%s", resp.status_code)
                    break
                rows = resp.json()
                if not isinstance(rows, list):
                    break
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if row.get("status") != "success":
                        continue
                    q = str(row.get("query") or "")
                    out[q] = {
                        "country": str(row.get("country") or "") or None,
                        "country_code": str(row.get("countryCode") or "") or None,
                        "region": str(row.get("region") or "") or None,
                        "region_name": str(row.get("regionName") or "") or None,
                        "city": str(row.get("city") or "") or None,
                    }
    except Exception:
        logger.exception("GeoIP lookup failed")
    return out


def _heuristic_labels(
    *,
    total: int,
    proto_packets: Counter[str],
    src_port_packets: Counter[int],
    syn_only: int,
    syn_ack: int,
    ack_only: int,
    rst_pkts: int,
    fin_pkts: int,
    null_pkts: int,
    xmas_pkts: int,
    syn_fin_pkts: int,
    tcp_packets: int,
    udp_amp_packets: int,
    tcp_reflect_packets: int,
    gre_packets: int,
    unique_sources: int,
    unique_src_ports: int,
) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    if total <= 0:
        return labels

    udp_pct = _pct(proto_packets.get("UDP", 0), total)
    tcp_pct = _pct(proto_packets.get("TCP", 0), total)
    icmp_pct = _pct(proto_packets.get("ICMP", 0), total)
    gre_pct = _pct(gre_packets, total)
    syn_pct = _pct(syn_only, tcp_packets) if tcp_packets else 0.0
    synack_pct = _pct(syn_ack, tcp_packets) if tcp_packets else 0.0
    ack_pct = _pct(ack_only, tcp_packets) if tcp_packets else 0.0
    rst_pct = _pct(rst_pkts, tcp_packets) if tcp_packets else 0.0
    fin_pct = _pct(fin_pkts, tcp_packets) if tcp_packets else 0.0
    null_pct = _pct(null_pkts, tcp_packets) if tcp_packets else 0.0
    xmas_pct = _pct(xmas_pkts, tcp_packets) if tcp_packets else 0.0
    synfin_pct = _pct(syn_fin_pkts, tcp_packets) if tcp_packets else 0.0
    amp_pct = _pct(udp_amp_packets, total)
    tcp_reflect_pct = _pct(tcp_reflect_packets, total)

    top_src_port, top_src_n = (None, 0)
    if src_port_packets:
        top_src_port, top_src_n = src_port_packets.most_common(1)[0]
    top_src_pct = _pct(top_src_n, total)
    top_amp = AMP_SRC_PORTS.get(int(top_src_port)) if top_src_port is not None else None
    top_tcp_reflect = (
        TCP_REFLECT_SRC_PORTS.get(int(top_src_port)) if top_src_port is not None else None
    )

    if gre_pct >= 15:
        labels.append(
            {
                "id": "gre_encap",
                "label": "GRE / tunneled IP layers present",
                "confidence": min(99.0, round(gre_pct + 20, 1)),
            }
        )

    if gre_pct >= 50 and udp_pct >= 50:
        labels.append(
            {
                "id": "gre_udp_flood",
                "label": "Likely GRE-encapsulated UDP flood",
                "confidence": min(
                    99.0, round(0.45 * gre_pct + 0.55 * udp_pct, 1)
                ),
            }
        )
    elif udp_pct >= 55 and amp_pct >= 35:
        amp_name = top_amp or "UDP"
        labels.append(
            {
                "id": "udp_amplification",
                "label": f"Likely {amp_name} amplification / reflection (src port)",
                "confidence": min(
                    99.0, round(0.45 * udp_pct + 0.55 * max(amp_pct, top_src_pct), 1)
                ),
            }
        )
    elif udp_pct >= 70:
        labels.append(
            {
                "id": "udp_flood",
                "label": "Likely UDP flood",
                "confidence": min(99.0, round(udp_pct, 1)),
            }
        )

    if tcp_pct >= 40 and tcp_reflect_pct >= 30 and (synack_pct >= 25 or ack_pct >= 35):
        svc = top_tcp_reflect or "TCP"
        labels.append(
            {
                "id": "tcp_reflection",
                "label": f"Likely {svc} TCP reflection (src port + SYN/ACK/ACK)",
                "confidence": min(
                    99.0,
                    round(0.4 * tcp_pct + 0.35 * tcp_reflect_pct + 0.25 * max(synack_pct, ack_pct), 1),
                ),
            }
        )

    if tcp_pct >= 50 and syn_pct >= 55:
        labels.append(
            {
                "id": "syn_flood",
                "label": "Likely TCP SYN flood",
                "confidence": min(99.0, round(0.5 * tcp_pct + 0.5 * syn_pct, 1)),
            }
        )

    if tcp_pct >= 50 and ack_pct >= 55 and syn_pct < 25:
        labels.append(
            {
                "id": "ack_flood",
                "label": "Likely TCP ACK flood",
                "confidence": min(99.0, round(0.45 * tcp_pct + 0.55 * ack_pct, 1)),
            }
        )

    if tcp_pct >= 45 and rst_pct >= 45:
        labels.append(
            {
                "id": "rst_flood",
                "label": "Likely TCP RST flood",
                "confidence": min(99.0, round(0.45 * tcp_pct + 0.55 * rst_pct, 1)),
            }
        )

    if tcp_pct >= 45 and fin_pct >= 45:
        labels.append(
            {
                "id": "fin_flood",
                "label": "Likely TCP FIN flood",
                "confidence": min(99.0, round(0.45 * tcp_pct + 0.55 * fin_pct, 1)),
            }
        )

    flag_flood_hits = [
        ("NULL", null_pct),
        ("XMAS", xmas_pct),
        ("SYN+FIN", synfin_pct),
    ]
    for name, pct in flag_flood_hits:
        if tcp_pct >= 40 and pct >= 25:
            labels.append(
                {
                    "id": f"flag_flood_{name.lower().replace('+', '_')}",
                    "label": f"Likely TCP {name} flag flood",
                    "confidence": min(99.0, round(0.4 * tcp_pct + 0.6 * pct, 1)),
                }
            )

    # Connection flood: many SYNs from many sources / many ephemeral source ports
    if (
        tcp_pct >= 45
        and syn_pct >= 40
        and (
            unique_sources >= max(30, total // 25)
            or unique_src_ports >= max(40, total // 20)
        )
    ):
        labels.append(
            {
                "id": "connection_flood",
                "label": "Likely TCP connection / handshake flood",
                "confidence": min(
                    99.0,
                    round(
                        0.35 * tcp_pct
                        + 0.35 * syn_pct
                        + 0.3 * min(95.0, unique_sources / 4 + unique_src_ports / 8),
                        1,
                    ),
                ),
            }
        )

    if icmp_pct >= 50:
        labels.append(
            {
                "id": "icmp_flood",
                "label": "Likely ICMP flood",
                "confidence": min(99.0, round(icmp_pct, 1)),
            }
        )

    if unique_sources >= max(50, total // 20):
        labels.append(
            {
                "id": "distributed",
                "label": "Highly distributed sources",
                "confidence": min(99.0, round(min(95.0, unique_sources / 5), 1)),
            }
        )

    has_signature = any(row.get("id") in _SIGNATURE_IDS for row in labels)
    if not has_signature:
        # Drop weak contextual-only rows before replacing with breakdown
        labels = [
            row
            for row in labels
            if row.get("id") not in {"gre_encap", "distributed"}
        ] + _protocol_packet_breakdown(
            total=total,
            proto_packets=proto_packets,
        )
        # Keep GRE / distributed as extras when present at meaningful rates
        if gre_pct >= 15:
            labels.append(
                {
                    "id": "gre_encap",
                    "label": "GRE / tunneled IP layers present",
                    "confidence": min(99.0, round(gre_pct + 20, 1)),
                }
            )
        if unique_sources >= max(50, total // 20):
            labels.append(
                {
                    "id": "distributed",
                    "label": "Highly distributed sources",
                    "confidence": min(99.0, round(min(95.0, unique_sources / 5), 1)),
                }
            )

    # Deduplicate by id, keep highest confidence
    best: dict[str, dict[str, Any]] = {}
    for row in labels:
        prev = best.get(row["id"])
        if prev is None or float(row["confidence"]) > float(prev["confidence"]):
            best[row["id"]] = row
    return sorted(best.values(), key=lambda r: float(r["confidence"]), reverse=True)


def analyze_pcap(name: str, *, force: bool = False) -> dict[str, Any]:
    pcap = resolve_pcap(name)
    st = pcap.stat()
    cache = _analysis_cache_path(pcap)
    if not force and cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if (
                cached.get("mtime_ns") == st.st_mtime_ns
                and cached.get("size_bytes") == st.st_size
            ):
                return cached["result"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass

    lines = _run_tshark(pcap)
    proto_packets: Counter[str] = Counter()
    proto_bytes: Counter[str] = Counter()
    l7_packets: Counter[str] = Counter()
    src_packets: Counter[str] = Counter()
    src_bytes: Counter[str] = Counter()
    src_port_packets: Counter[int] = Counter()
    dst_port_packets: Counter[int] = Counter()
    length_sum = 0
    length_min = None
    length_max = 0
    syn_only = 0
    syn_ack = 0
    ack_only = 0
    rst_pkts = 0
    fin_pkts = 0
    null_pkts = 0
    xmas_pkts = 0
    syn_fin_pkts = 0
    tcp_packets = 0
    udp_amp_packets = 0
    tcp_reflect_packets = 0
    gre_packets = 0
    unique_src_ports: set[int] = set()
    first_ts: float | None = None
    last_ts: float | None = None
    analyzed = 0

    for line in lines:
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 14:
            parts.append("")
        (
            ts_raw,
            len_raw,
            ip_src,
            ipv6_src,
            _ip_dst,
            ip_proto,
            udp_sport,
            udp_dport,
            tcp_sport,
            tcp_dport,
            tcp_flags,
            frame_protocols,
            gre_proto,
        ) = parts[:13]

        try:
            pkt_len = int(_split_field(len_raw)[0]) if len_raw else 0
        except (ValueError, IndexError):
            pkt_len = 0

        src = _effective_src(ip_src, ipv6_src, frame_protocols)
        proto = _proto_name(ip_proto, frame_protocols)
        tokens = _frame_tokens(frame_protocols)
        if "gre" in tokens or gre_proto.strip() or proto == "GRE":
            gre_packets += 1

        src_port = _parse_port(udp_sport) if proto == "UDP" else _parse_port(tcp_sport)
        if src_port is None:
            src_port = _parse_port(udp_sport) or _parse_port(tcp_sport)
        dst_port = _parse_port(udp_dport) if proto == "UDP" else _parse_port(tcp_dport)
        if dst_port is None:
            dst_port = _parse_port(udp_dport) or _parse_port(tcp_dport)

        analyzed += 1
        proto_packets[proto] += 1
        proto_bytes[proto] += pkt_len
        src_packets[src] += 1
        src_bytes[src] += pkt_len
        length_sum += pkt_len
        length_min = pkt_len if length_min is None else min(length_min, pkt_len)
        length_max = max(length_max, pkt_len)

        if src_port is not None:
            src_port_packets[src_port] += 1
            unique_src_ports.add(src_port)
        if dst_port is not None:
            dst_port_packets[dst_port] += 1

        flags: set[str] = set()
        if proto == "TCP":
            tcp_packets += 1
            flags = _parse_tcp_flags(tcp_flags)
            if "SYN" in flags and "ACK" in flags:
                syn_ack += 1
            elif "SYN" in flags and "ACK" not in flags:
                syn_only += 1
            if "ACK" in flags and "SYN" not in flags and "RST" not in flags and "FIN" not in flags:
                ack_only += 1
            if "RST" in flags:
                rst_pkts += 1
            if "FIN" in flags and "SYN" not in flags:
                fin_pkts += 1
            if flags == {"NULL"} or (not flags and tcp_flags.strip()):
                # empty parse with present field treated cautiously
                if "NULL" in flags or tcp_flags.strip().lower() in {"0x00", "0x0", "0"}:
                    null_pkts += 1
            if {"FIN", "PSH", "URG"}.issubset(flags):
                xmas_pkts += 1
            if {"SYN", "FIN"}.issubset(flags):
                syn_fin_pkts += 1

            if src_port in TCP_REFLECT_SRC_PORTS and (
                "SYN" in flags or "ACK" in flags or "RST" in flags
            ):
                tcp_reflect_packets += 1

        if proto == "UDP" and src_port in AMP_SRC_PORTS:
            udp_amp_packets += 1

        l7 = _l7_hint(frame_protocols, src_port, dst_port, proto=proto, flags=flags)
        if l7:
            l7_packets[l7] += 1

        if ts_raw:
            try:
                ts = float(_split_field(ts_raw)[0])
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)
            except (ValueError, IndexError):
                pass

    total = analyzed
    truncated = total >= MAX_PACKETS
    duration_sec = None
    if first_ts is not None and last_ts is not None and last_ts >= first_ts:
        duration_sec = round(last_ts - first_ts, 3)

    # Do NOT add GRE as a second protocol row — that double-counts packets in
    # pie charts (UDP 99% + GRE 99%). Encapsulation is exposed via gre_*.

    protocols = []
    for pname, pkts in proto_packets.most_common():
        if pname == "GRE":
            continue
        protocols.append(
            {
                "name": pname,
                "packets": pkts,
                "bytes": int(proto_bytes[pname]),
                "pct_packets": _pct(pkts, total),
                "pct_bytes": _pct(int(proto_bytes[pname]), length_sum),
            }
        )

    services = []
    for sname, pkts in l7_packets.most_common(TOP_N):
        services.append(
            {
                "name": sname,
                "packets": pkts,
                "pct_packets": _pct(pkts, total),
            }
        )

    # Prefer the port direction with clearer concentration for the table.
    top_ports = []
    src_top = src_port_packets.most_common(TOP_N)
    dst_top = dst_port_packets.most_common(TOP_N)
    src_conc = _pct(src_top[0][1], total) if src_top else 0.0
    dst_conc = _pct(dst_top[0][1], total) if dst_top else 0.0
    use_dst = dst_conc >= src_conc and dst_conc >= 5.0
    port_rows = dst_top if use_dst else src_top
    direction = "dst" if use_dst else "src"
    for port, pkts in port_rows:
        top_ports.append(
            {
                "port": port,
                "direction": direction,
                "label": AMP_SRC_PORTS.get(port) or TCP_REFLECT_SRC_PORTS.get(port),
                "packets": pkts,
                "pct_packets": _pct(pkts, total),
            }
        )
    # If neither side concentrates, still show top src ports (amp view).
    if not top_ports and src_top:
        for port, pkts in src_top:
            top_ports.append(
                {
                    "port": port,
                    "direction": "src",
                    "label": AMP_SRC_PORTS.get(port)
                    or TCP_REFLECT_SRC_PORTS.get(port),
                    "packets": pkts,
                    "pct_packets": _pct(pkts, total),
                }
            )

    unique_sources = [s for s in src_packets.keys() if s != "unknown"]
    ranked_sources = [ip for ip, _ in src_packets.most_common(200) if ip != "unknown"]
    geo = _lookup_geo(ranked_sources)

    top_sources = []
    for ip, pkts in src_packets.most_common(TOP_N):
        if ip == "unknown":
            continue
        g = geo.get(ip) or {}
        top_sources.append(
            {
                "ip": ip,
                "packets": pkts,
                "bytes": int(src_bytes[ip]),
                "pct_packets": _pct(pkts, total),
                "country_code": g.get("country_code"),
                "region": g.get("region"),
                "region_name": g.get("region_name"),
                "city": g.get("city"),
            }
        )

    us_state_packets: Counter[str] = Counter()
    country_packets: Counter[str] = Counter()
    for ip, pkts in src_packets.items():
        if ip == "unknown":
            continue
        g = geo.get(ip)
        if not g:
            country_packets["ZZ"] += pkts
            continue
        cc = (g.get("country_code") or "ZZ").upper()
        country_packets[cc] += pkts
        if cc == "US":
            region = (g.get("region") or "").upper()
            if region in US_STATE_NAMES:
                us_state_packets[region] += pkts
            else:
                us_state_packets["XX"] += pkts

    us_states = []
    for code, pkts in us_state_packets.most_common():
        us_states.append(
            {
                "code": code,
                "label": US_STATE_NAMES.get(code, "Unknown / multi-state"),
                "packets": pkts,
                "pct_packets": _pct(pkts, total),
                "pct_of_us": _pct(pkts, sum(us_state_packets.values()) or 1),
            }
        )

    countries = []
    for code, pkts in country_packets.most_common(TOP_N):
        countries.append(
            {
                "code": code,
                "label": "Unknown" if code == "ZZ" else code,
                "packets": pkts,
                "pct_packets": _pct(pkts, total),
            }
        )

    uniq_src_count = len(unique_sources)
    heuristics = _heuristic_labels(
        total=total,
        proto_packets=proto_packets,
        src_port_packets=src_port_packets,
        syn_only=syn_only,
        syn_ack=syn_ack,
        ack_only=ack_only,
        rst_pkts=rst_pkts,
        fin_pkts=fin_pkts,
        null_pkts=null_pkts,
        xmas_pkts=xmas_pkts,
        syn_fin_pkts=syn_fin_pkts,
        tcp_packets=tcp_packets,
        udp_amp_packets=udp_amp_packets,
        tcp_reflect_packets=tcp_reflect_packets,
        gre_packets=gre_packets,
        unique_sources=uniq_src_count,
        unique_src_ports=len(unique_src_ports),
    )

    result: dict[str, Any] = {
        "name": name,
        "size_bytes": int(st.st_size),
        "packet_count": total,
        "analyzed_packets": total,
        "truncated": truncated,
        "duration_sec": duration_sec,
        "avg_packet_bytes": round(length_sum / total, 1) if total else 0,
        "min_packet_bytes": int(length_min or 0),
        "max_packet_bytes": int(length_max),
        "unique_sources": uniq_src_count,
        "gre_packets": gre_packets,
        "gre_ratio_pct": _pct(gre_packets, total),
        "udp_amp_packets": udp_amp_packets,
        "tcp_reflect_packets": tcp_reflect_packets,
        "syn_ratio_pct": _pct(syn_only, tcp_packets) if tcp_packets else 0.0,
        "synack_ratio_pct": _pct(syn_ack, tcp_packets) if tcp_packets else 0.0,
        "ack_ratio_pct": _pct(ack_only, tcp_packets) if tcp_packets else 0.0,
        "heuristics": heuristics,
        "protocols": protocols,
        "services": services,
        "top_ports": top_ports,
        "top_sources": top_sources,
        "countries": countries,
        "us_states": us_states,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        cache.write_text(
            json.dumps(
                {
                    "mtime_ns": st.st_mtime_ns,
                    "size_bytes": st.st_size,
                    "result": result,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Could not write analysis cache for %s", name)

    return result
