"""Apply per-VPN-client CAKE shaping (10.8.0.0/24 on tun0)."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SHAPE_SCRIPT = Path(
    os.environ.get("VPN_SHAPE_SCRIPT", "/usr/local/sbin/vpn-shape-10.8.sh")
)
SHAPE_ENV = Path("/etc/default/vpn-shape-10.8")
SHAPE_SERVICE = "vpn-shape-10.8.service"
VPN_IFACE = os.environ.get("VPN_IFACE", "tun0")
IFB_DEV = os.environ.get("IFB_DEV", "ifb0")


def _write_env(*, down_mbit: int, up_mbit: int, enabled: bool) -> None:
    SHAPE_ENV.parent.mkdir(parents=True, exist_ok=True)
    SHAPE_ENV.write_text(
        "\n".join(
            [
                f"VPN_IFACE={VPN_IFACE}",
                f"IFB_DEV={IFB_DEV}",
                f"DOWN_MBIT={int(down_mbit)}",
                f"UP_MBIT={int(up_mbit)}",
                f"ENABLED={'1' if enabled else '0'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        SHAPE_ENV.chmod(0o644)
    except OSError:
        pass


def _clear_shaping() -> None:
    for cmd in (
        ["tc", "qdisc", "del", "dev", VPN_IFACE, "root"],
        ["tc", "qdisc", "del", "dev", VPN_IFACE, "ingress"],
        ["tc", "qdisc", "del", "dev", IFB_DEV, "root"],
    ):
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=15)


def apply_client_shaping(
    *,
    enabled: bool,
    down_mbit: int,
    up_mbit: int,
) -> dict[str, object]:
    """Persist rates and apply (or clear) live CAKE qdiscs."""
    down_mbit = max(1, min(10000, int(down_mbit)))
    up_mbit = max(1, min(10000, int(up_mbit)))
    _write_env(down_mbit=down_mbit, up_mbit=up_mbit, enabled=enabled)

    # Keep systemd unit args in sync for reboot / tun0 path triggers
    try:
        unit = Path(f"/etc/systemd/system/{SHAPE_SERVICE}")
        if unit.is_file():
            text = unit.read_text(encoding="utf-8")
            text = re.sub(
                r"ExecStart=.*",
                f"ExecStart={SHAPE_SCRIPT} {down_mbit} {up_mbit}",
                text,
            )
            if "EnvironmentFile=" not in text:
                text = text.replace(
                    "Environment=VPN_IFACE=tun0",
                    "Environment=VPN_IFACE=tun0\n"
                    f"EnvironmentFile=-{SHAPE_ENV}",
                )
            unit.write_text(text, encoding="utf-8")
            subprocess.run(
                ["systemctl", "daemon-reload"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
    except Exception:
        logger.exception("Could not refresh vpn-shape systemd unit")

    if not enabled:
        _clear_shaping()
        logger.info("Client shaping disabled; qdiscs cleared")
        return {
            "ok": True,
            "enabled": False,
            "down_mbit": down_mbit,
            "up_mbit": up_mbit,
            "message": "Shaping disabled (limits cleared on tun0)",
        }

    if not SHAPE_SCRIPT.is_file():
        logger.error("Shape script missing: %s", SHAPE_SCRIPT)
        return {
            "ok": False,
            "enabled": True,
            "down_mbit": down_mbit,
            "up_mbit": up_mbit,
            "message": f"Shape script missing: {SHAPE_SCRIPT}",
        }

    try:
        result = subprocess.run(
            [str(SHAPE_SCRIPT), str(down_mbit), str(up_mbit)],
            check=False,
            timeout=45,
            capture_output=True,
            text=True,
            env={**os.environ, "VPN_IFACE": VPN_IFACE, "IFB_DEV": IFB_DEV},
        )
    except Exception as exc:
        logger.exception("Shaping apply failed")
        return {
            "ok": False,
            "enabled": True,
            "down_mbit": down_mbit,
            "up_mbit": up_mbit,
            "message": f"Shaping apply failed: {exc}",
        }

    out = (result.stdout or "") + (result.stderr or "")
    # Script may exit 141 (SIGPIPE) from `head` even after successful apply
    ok = result.returncode == 0 or "OK:" in out
    if not ok:
        logger.error(
            "vpn-shape failed rc=%s out=%s err=%s",
            result.returncode,
            (result.stdout or "")[:400],
            (result.stderr or "")[:400],
        )
    else:
        logger.info(
            "Client shaping applied down=%s up=%s mbit", down_mbit, up_mbit
        )

    return {
        "ok": ok,
        "enabled": True,
        "down_mbit": down_mbit,
        "up_mbit": up_mbit,
        "message": (
            f"Shaping applied: {down_mbit}/{up_mbit} Mbps per client on {VPN_IFACE}"
            if ok
            else (result.stderr or result.stdout or "tc apply failed").strip()[:300]
        ),
    }


def read_live_cake_bandwidth(dev: str) -> str | None:
    try:
        out = subprocess.run(
            ["tc", "qdisc", "show", "dev", dev],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    m = re.search(r"bandwidth\s+(\S+)", out.stdout or "")
    return m.group(1) if m else None


def get_shaping_status() -> dict[str, object]:
    return {
        "iface": VPN_IFACE,
        "download": read_live_cake_bandwidth(VPN_IFACE),
        "upload": read_live_cake_bandwidth(IFB_DEV),
        "env_file": str(SHAPE_ENV) if SHAPE_ENV.is_file() else None,
    }
