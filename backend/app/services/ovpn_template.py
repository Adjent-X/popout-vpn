"""Build / parse OpenVPN client template text (Nyr client-common / Angristan client-template)."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import get_settings
from app.models.site_settings import OvpnBindMode, SiteSettingsData
from app.services.openvpn_layout import (
    angristan_default_extra,
    detect_flavor,
    resolve_layout,
)


def _remote_directive_lines(data: SiteSettingsData) -> list[str]:
    host = data.ovpn_remote_host.strip()
    if data.ovpn_remote_mode == "remote_random":
        lo = int(data.ovpn_remote_port_min)
        hi = int(data.ovpn_remote_port_max)
        if lo > hi:
            lo, hi = hi, lo
        lines = ["remote-random"]
        for port in range(lo, hi + 1):
            lines.append(f"remote {host} {port}")
        return lines
    return [f"remote {host} {int(data.ovpn_remote_port)}"]


def _normalize_proto(proto: str) -> str:
    """Map common aliases; keep Angristan tcp-client / tcp6-client as-is."""
    value = (proto or "").strip()
    aliases = {
        "tcp": "tcp4",
        "udp": "udp",
        "tcp-client": "tcp-client",
        "tcp6-client": "tcp6-client",
    }
    return aliases.get(value.lower(), value) or "udp"


def build_client_common_text(data: SiteSettingsData) -> str:
    """Generate client template body from structured site settings."""
    flavor = detect_flavor()
    proto = _normalize_proto(data.ovpn_proto)
    lines: list[str] = ["client", "dev tun"]

    if data.ovpn_tun_mtu and data.ovpn_tun_mtu > 0:
        lines.append(f"tun-mtu {data.ovpn_tun_mtu}")
    if data.ovpn_mssfix and data.ovpn_mssfix > 0:
        lines.append(f"mssfix {data.ovpn_mssfix}")
    if data.ovpn_tcp_nodelay:
        lines.append("tcp-nodelay")

    lines.append(f"proto {proto}")
    # Angristan expects explicit-exit-notify for UDP before remotes when using
    # their stock template; keep it in ovpn_extra so admins can edit it.
    lines.extend(_remote_directive_lines(data))
    lines.append("resolv-retry infinite")
    if data.ovpn_bind_mode == "nobind":
        lines.append("nobind")
    else:
        lines.append(f"lport {int(data.ovpn_lport)}")
    lines.extend(
        [
            "",
            "persist-key",
            "persist-tun",
            "remote-cert-tls server",
            f"auth {data.ovpn_auth.strip()}",
            "ignore-unknown-option block-outside-dns",
            f"verb {int(data.ovpn_verb)}",
        ]
    )
    extra = (data.ovpn_extra or "").strip()
    if extra:
        lines.append("")
        for raw in extra.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            # Common typo: "ignore-unknown option X" → Connect treats
            # "ignore-unknown" as an unsupported option name.
            if stripped.lower().startswith("ignore-unknown ") and not stripped.lower().startswith(
                "ignore-unknown-option"
            ):
                rest = (
                    stripped.split(None, 1)[1]
                    if len(stripped.split(None, 1)) > 1
                    else ""
                )
                if rest.lower().startswith("option "):
                    rest = (
                        rest.split(None, 1)[1] if len(rest.split(None, 1)) > 1 else ""
                    )
                if rest:
                    stripped = f"ignore-unknown-option {rest}"
                else:
                    continue
            lines.append(stripped)
    elif flavor == "angristan":
        # Safety net if Mongo seed missed extras
        layout = resolve_layout()
        lines.append("")
        lines.extend(angristan_default_extra(layout.server_cn).splitlines())

    return "\n".join(lines).rstrip() + "\n"


def _parse_int(match: re.Match[str] | None) -> int | None:
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def parse_client_common_text(text: str) -> dict:
    """Extract known directives from a client template body into field updates."""
    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )

    remotes = re.findall(
        r"(?im)^\s*remote\s+(\S+)\s+(\d+)\s*$",
        body,
    )
    remote_random = bool(re.search(r"(?im)^\s*remote-random\s*$", body))
    proto = re.search(r"(?im)^\s*proto\s+(\S+)\s*$", body)
    tun_mtu = re.search(r"(?im)^\s*tun-mtu\s+(\d+)\s*$", body)
    mssfix = re.search(r"(?im)^\s*mssfix\s+(\d+)\s*$", body)
    lport = re.search(r"(?im)^\s*lport\s+(\d+)\s*$", body)
    auth = re.search(r"(?im)^\s*auth\s+(\S+)\s*$", body)
    verb = re.search(r"(?im)^\s*verb\s+(\d+)\s*$", body)

    bind_mode: OvpnBindMode = (
        "nobind" if re.search(r"(?im)^\s*nobind\s*$", body) else "lport"
    )

    known = {
        "client",
        "dev",
        "tun-mtu",
        "mssfix",
        "tcp-nodelay",
        "proto",
        "remote",
        "remote-random",
        "resolv-retry",
        "nobind",
        "lport",
        "persist-key",
        "persist-tun",
        "remote-cert-tls",
        "auth",
        "ignore-unknown-option",
        "verb",
    }
    extras: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        key = stripped.split()[0].lower()
        if key not in known:
            extras.append(line.rstrip())

    result: dict = {
        "ovpn_tcp_nodelay": bool(re.search(r"(?im)^\s*tcp-nodelay\s*$", body)),
        "ovpn_bind_mode": bind_mode,
        "ovpn_extra": "\n".join(extras),
    }
    if remotes:
        result["ovpn_remote_host"] = remotes[0][0]
        ports = sorted({int(p) for _, p in remotes})
        if remote_random and len(ports) > 1:
            result["ovpn_remote_mode"] = "remote_random"
            result["ovpn_remote_port_min"] = ports[0]
            result["ovpn_remote_port_max"] = ports[-1]
            result["ovpn_remote_port"] = ports[0]
        else:
            result["ovpn_remote_mode"] = "single"
            result["ovpn_remote_port"] = ports[0]
            if len(ports) > 1:
                result["ovpn_remote_port_min"] = ports[0]
                result["ovpn_remote_port_max"] = ports[-1]
    if proto:
        result["ovpn_proto"] = proto.group(1)
    mtu = _parse_int(tun_mtu)
    result["ovpn_tun_mtu"] = mtu
    mss = _parse_int(mssfix)
    result["ovpn_mssfix"] = mss
    lp = _parse_int(lport)
    if lp is not None:
        result["ovpn_lport"] = lp
    if auth:
        result["ovpn_auth"] = auth.group(1)
    v = _parse_int(verb)
    if v is not None:
        result["ovpn_verb"] = v

    return result


def load_ovpn_defaults_from_disk() -> dict:
    """Prefer parsing the live client template; fall back to env + flavor defaults."""
    settings = get_settings()
    layout = resolve_layout()
    path = layout.client_template
    if path.is_file():
        try:
            parsed = parse_client_common_text(path.read_text(encoding="utf-8"))
            # If Angristan template was overwritten without extras, restore them.
            if layout.flavor == "angristan" and not (parsed.get("ovpn_extra") or "").strip():
                parsed["ovpn_extra"] = angristan_default_extra(layout.server_cn)
            return parsed
        except OSError:
            pass

    if layout.flavor == "angristan":
        return {
            "ovpn_remote_host": settings.OPENVPN_SERVER_HOST,
            "ovpn_remote_mode": "single",
            "ovpn_remote_port": settings.OPENVPN_SERVER_PORT,
            "ovpn_remote_port_min": 45000,
            "ovpn_remote_port_max": 45099,
            "ovpn_proto": settings.OPENVPN_PROTO or "udp",
            "ovpn_tun_mtu": None,
            "ovpn_mssfix": None,
            "ovpn_tcp_nodelay": False,
            "ovpn_bind_mode": "nobind",
            "ovpn_lport": 1,
            "ovpn_auth": "SHA256",
            "ovpn_verb": 3,
            "ovpn_extra": angristan_default_extra(layout.server_cn),
        }

    return {
        "ovpn_remote_host": settings.OPENVPN_SERVER_HOST,
        "ovpn_remote_mode": "single",
        "ovpn_remote_port": settings.OPENVPN_SERVER_PORT,
        "ovpn_remote_port_min": 45000,
        "ovpn_remote_port_max": 45099,
        "ovpn_proto": settings.OPENVPN_PROTO,
        "ovpn_tun_mtu": 1400,
        "ovpn_mssfix": 1360,
        "ovpn_tcp_nodelay": True,
        "ovpn_bind_mode": "lport",
        "ovpn_lport": 1,
        "ovpn_auth": "SHA512",
        "ovpn_verb": 3,
        "ovpn_extra": "",
    }


def try_write_client_common_file(text: str) -> bool:
    """Best-effort sync to the on-disk client template (Nyr or Angristan)."""
    layout = resolve_layout()
    path = layout.client_template
    # Also keep the configured path in sync when it differs (symlink farms).
    configured = Path(get_settings().OPENVPN_CLIENT_COMMON_PATH)
    targets = [path]
    if configured != path:
        targets.append(configured)
    wrote = False
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            wrote = True
        except OSError:
            continue
    return wrote
