"""Enable/disable OpenVPN UDP, OpenVPN TCP, and WireGuard; refresh DNAT."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DNAT_ENV = Path("/etc/popout-vpn/dnat.env")
DNAT_SCRIPT = Path("/usr/local/sbin/popout-dnat.sh")


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def unit_active(unit: str) -> bool:
    return _systemctl("is-active", "--quiet", unit).returncode == 0


def set_unit_enabled(unit: str, enabled: bool) -> None:
    if enabled:
        proc = _systemctl("enable", "--now", unit)
        if proc.returncode != 0:
            logger.warning(
                "enable %s failed: %s", unit, (proc.stderr or proc.stdout or "").strip()
            )
        return
    proc = _systemctl("disable", "--now", unit)
    if proc.returncode != 0:
        logger.warning(
            "disable %s failed: %s", unit, (proc.stderr or proc.stdout or "").strip()
        )


def _set_conf_line(body: str, key: str, value: str) -> str:
    pat = re.compile(rf"(?m)^(?:#\s*)?{re.escape(key)}\s+.*$")
    if pat.search(body):
        return pat.sub(f"{key} {value}", body, count=1)
    return body.rstrip() + f"\n{key} {value}\n"


def rewrite_openvpn_instance(name: str, *, bind_ip: str, port: int) -> None:
    path = Path(f"/etc/openvpn/server/{name}.conf")
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = _set_conf_line(text, "local", bind_ip)
        text = _set_conf_line(text, "port", str(int(port)))
        path.write_text(text, encoding="utf-8")
    except OSError:
        logger.exception("Could not rewrite %s", path)


def write_dnat_env(
    *,
    bind_ip: str,
    ovpn_udp_enabled: bool,
    ovpn_tcp_enabled: bool,
    wg_enabled: bool,
    ovpn_udp_port: int,
    ovpn_tcp_port: int,
    wg_port: int,
    ephemeral_min: int = 45000,
    ephemeral_max: int = 45099,
) -> None:
    DNAT_ENV.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"BIND_IP={bind_ip}\n"
        "BIND_IFACE=popout-bind\n"
        f"OVPN_UDP_ENABLED={'1' if ovpn_udp_enabled else '0'}\n"
        f"OVPN_TCP_ENABLED={'1' if ovpn_tcp_enabled else '0'}\n"
        f"WG_ENABLED={'1' if wg_enabled else '0'}\n"
        f"OVPN_UDP_PORT={int(ovpn_udp_port)}\n"
        f"OVPN_TCP_PORT={int(ovpn_tcp_port)}\n"
        f"WG_PORT={int(wg_port)}\n"
        "EPHEMERAL_SET=ephemeral-ports\n"
        f"EPHEMERAL_PORT_MIN={int(ephemeral_min)}\n"
        f"EPHEMERAL_PORT_MAX={int(ephemeral_max)}\n"
    )
    DNAT_ENV.write_text(body, encoding="utf-8")


def apply_dnat() -> None:
    script = DNAT_SCRIPT if DNAT_SCRIPT.is_file() else Path(
        os.environ.get("PANEL_ROOT", "/opt/popout-vpn")
    ) / "scripts" / "popout-dnat.sh"
    if not script.is_file():
        logger.warning("DNAT script missing: %s", script)
        return
    proc = subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        logger.error("popout-dnat failed: %s", proc.stderr or proc.stdout)


def apply_vpn_servers(data, *, touch_units: bool = True) -> dict:
    """Apply site-settings server toggles: systemd units + DNAT + WG params."""
    nic = "wg0"
    try:
        from app.services.wireguard import _nic, update_server_params, wg_available

        if wg_available():
            nic = _nic()
            update_server_params(
                endpoint=(data.wg_endpoint_host or data.ovpn_remote_host or "").strip()
                or None,
                port=int(data.wg_listen_port),
                dns=data.wg_dns or None,
                allowed_ips=data.wg_allowed_ips or None,
                mtu=int(data.wg_mtu) if data.wg_mtu else None,
                keepalive=int(data.wg_keepalive) if data.wg_keepalive is not None else None,
            )
    except Exception:
        logger.exception("Could not update WireGuard server params")

    bind_ip = (data.vpn_bind_ip or "10.255.255.1").strip()
    if touch_units:
        rewrite_openvpn_instance("udp", bind_ip=bind_ip, port=int(data.ovpn_udp_port))
        rewrite_openvpn_instance("tcp", bind_ip=bind_ip, port=int(data.ovpn_tcp_port))
        units = {
            "ovpn_udp": "openvpn-server@udp",
            "ovpn_tcp": "openvpn-server@tcp",
            "wireguard": f"wg-quick@{nic}",
        }
        set_unit_enabled(units["ovpn_udp"], bool(data.ovpn_udp_enabled))
        set_unit_enabled(units["ovpn_tcp"], bool(data.ovpn_tcp_enabled))
        set_unit_enabled(units["wireguard"], bool(data.wg_enabled))
        if data.ovpn_udp_enabled:
            _systemctl("restart", units["ovpn_udp"])
        if data.ovpn_tcp_enabled:
            _systemctl("restart", units["ovpn_tcp"])
        if data.wg_enabled:
            _systemctl("restart", units["wireguard"])

    write_dnat_env(
        bind_ip=bind_ip,
        ovpn_udp_enabled=bool(data.ovpn_udp_enabled),
        ovpn_tcp_enabled=bool(data.ovpn_tcp_enabled),
        wg_enabled=bool(data.wg_enabled),
        ovpn_udp_port=int(data.ovpn_udp_port),
        ovpn_tcp_port=int(data.ovpn_tcp_port),
        wg_port=int(data.wg_listen_port),
        ephemeral_min=int(data.ovpn_remote_port_min or 45000),
        ephemeral_max=int(data.ovpn_remote_port_max or 45099),
    )
    apply_dnat()
    return server_status(data)


def server_status(data=None) -> dict:
    nic = "wg0"
    wg_ok = False
    try:
        from app.services.wireguard import _nic, wg_available

        wg_ok = wg_available()
        if wg_ok:
            nic = _nic()
    except Exception:
        pass
    bind = getattr(data, "vpn_bind_ip", None) or "10.255.255.1"
    return {
        "bind_ip": bind,
        "ovpn_udp": {
            "enabled": bool(getattr(data, "ovpn_udp_enabled", True)) if data else True,
            "active": unit_active("openvpn-server@udp"),
            "unit": "openvpn-server@udp",
            "port": int(getattr(data, "ovpn_udp_port", 1194)) if data else 1194,
        },
        "ovpn_tcp": {
            "enabled": bool(getattr(data, "ovpn_tcp_enabled", True)) if data else True,
            "active": unit_active("openvpn-server@tcp"),
            "unit": "openvpn-server@tcp",
            "port": int(getattr(data, "ovpn_tcp_port", 1195)) if data else 1195,
        },
        "wireguard": {
            "enabled": bool(getattr(data, "wg_enabled", True)) if data else True,
            "active": unit_active(f"wg-quick@{nic}"),
            "unit": f"wg-quick@{nic}",
            "port": int(getattr(data, "wg_listen_port", 51820)) if data else 51820,
            "installed": wg_ok,
        },
    }
