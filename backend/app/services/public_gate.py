"""Sync nginx basic-auth gate for the public Cloudflare admin hostname."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SYNC_SCRIPT = Path(
    os.environ.get(
        "PUBLIC_GATE_SYNC_SCRIPT",
        "/opt/popout-vpn/config/sync-public-gate.sh",
    )
)
# Fallback to /usr/local if panel path missing
SYNC_SCRIPT_ALT = Path("/usr/local/sbin/sync-popout-public-gate.sh")


def sync_public_access_gate(
    *,
    enabled: bool,
    password: str | None = None,
) -> None:
    """Update nginx auth snippet (+ optional htpasswd) and reload nginx."""
    script = SYNC_SCRIPT if SYNC_SCRIPT.is_file() else SYNC_SCRIPT_ALT
    if not script.is_file():
        logger.warning("Public gate sync script missing: %s", script)
        return
    if not os.access(script, os.X_OK):
        try:
            script.chmod(script.stat().st_mode | 0o111)
        except OSError:
            logger.warning("Cannot chmod public gate sync script %s", script)

    cmd = [str(script), "1" if enabled else "0"]
    if password:
        cmd.append(password)
    try:
        result = subprocess.run(
            cmd,
            check=False,
            timeout=30,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(
                "Public gate sync failed rc=%s out=%s err=%s",
                result.returncode,
                (result.stdout or "")[:300],
                (result.stderr or "")[:300],
            )
        else:
            logger.info(
                "Public gate sync ok enabled=%s password_rotated=%s",
                enabled,
                bool(password),
            )
    except Exception:
        logger.exception("Public gate sync raised")


def ensure_sync_script_installed() -> None:
    """Copy panel script to /usr/local/sbin for reliable root execution."""
    src = Path("/opt/popout-vpn/config/sync-public-gate.sh")
    if not src.is_file():
        return
    try:
        SYNC_SCRIPT_ALT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, SYNC_SCRIPT_ALT)
        SYNC_SCRIPT_ALT.chmod(0o755)
    except OSError:
        logger.exception("Could not install public gate sync script")
