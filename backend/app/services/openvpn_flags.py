"""Detect OpenVPN server.conf flags used by the panel."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVER_CONF_CANDIDATES = (
    Path("/etc/openvpn/server/server.conf"),
    Path("/etc/openvpn/server.conf"),
)


def detect_duplicate_cn(server_conf: Path | None = None) -> bool:
    """True when OpenVPN allows multiple clients with the same certificate CN."""
    paths = (server_conf,) if server_conf is not None else _SERVER_CONF_CANDIDATES
    for path in paths:
        if path is None or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
            continue
        if re.search(r"(?im)^\s*duplicate-cn\b", text):
            return True
    return False
