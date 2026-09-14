"""Manage OpenVPN client membership in the warp-routing ipset."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

WARP_IPSET_NAME = "warp-routing"
IPSET_SAVE_PATH = Path("/etc/iptables/ipsets")
_VPN_IP_RE = re.compile(r"^10\.8\.0\.(\d{1,3})$")


class WarpRoutingError(RuntimeError):
    pass


def is_vpn_tunnel_ip(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    raw = value.strip()
    if not _VPN_IP_RE.match(raw):
        return False
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return addr in ipaddress.ip_network("10.8.0.0/24") and str(addr) != "10.8.0.1"


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return (
        int(proc.returncode or 0),
        out_b.decode("utf-8", errors="replace"),
        err_b.decode("utf-8", errors="replace"),
    )


async def ensure_warp_ipset() -> None:
    code, _, err = await _run(
        ["ipset", "create", WARP_IPSET_NAME, "hash:ip", "family", "inet", "-exist"]
    )
    if code != 0:
        # Set may already exist with compatible type; list to confirm
        code2, _, err2 = await _run(["ipset", "list", WARP_IPSET_NAME, "-name"])
        if code2 != 0:
            raise WarpRoutingError(
                f"ipset create/list failed: {err.strip() or err2.strip()}"
            )


async def save_ipsets() -> None:
    code, out, err = await _run(["ipset", "save"])
    if code != 0:
        raise WarpRoutingError(f"ipset save failed: {err.strip()}")
    IPSET_SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(IPSET_SAVE_PATH.write_text, out, encoding="utf-8")


async def add_to_warp_routing(vpn_ip: str) -> None:
    if not is_vpn_tunnel_ip(vpn_ip):
        raise WarpRoutingError(f"Invalid VPN tunnel IP for warp routing: {vpn_ip!r}")
    await ensure_warp_ipset()
    code, _, err = await _run(
        ["ipset", "add", WARP_IPSET_NAME, vpn_ip.strip(), "-exist"]
    )
    if code != 0:
        raise WarpRoutingError(f"ipset add failed: {err.strip()}")
    await save_ipsets()
    logger.info("Added %s to ipset %s", vpn_ip, WARP_IPSET_NAME)


async def remove_from_warp_routing(vpn_ip: str | None) -> None:
    if not is_vpn_tunnel_ip(vpn_ip):
        return
    assert vpn_ip is not None
    await ensure_warp_ipset()
    code, _, err = await _run(
        ["ipset", "del", WARP_IPSET_NAME, vpn_ip.strip(), "-exist"]
    )
    if code != 0:
        # -exist should make missing members a no-op; still log unexpected failures
        logger.warning("ipset del %s: %s", vpn_ip, err.strip())
        return
    await save_ipsets()
    logger.info("Removed %s from ipset %s", vpn_ip, WARP_IPSET_NAME)


async def sync_warp_routing(*, vpn_ip: str | None, enabled: bool) -> None:
    """Ensure ipset membership matches the desired warp_routing_enabled flag."""
    if enabled:
        if not is_vpn_tunnel_ip(vpn_ip):
            raise WarpRoutingError(
                "Client must connect once (VPN IP assigned) before enabling Warp routing"
            )
        await add_to_warp_routing(vpn_ip)  # type: ignore[arg-type]
    else:
        await remove_from_warp_routing(vpn_ip)
