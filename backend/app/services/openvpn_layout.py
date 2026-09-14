"""Detect OpenVPN installer layout (Nyr vs Angristan) and resolve paths."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.config import get_settings

logger = logging.getLogger(__name__)

OpenVpnFlavor = Literal["nyr", "angristan", "unknown"]
TlsMode = Literal["tls-crypt-v2", "tls-crypt", "tls-auth", "none"]

_SERVER_DIR = Path("/etc/openvpn/server")


@dataclass(frozen=True)
class OpenVpnLayout:
    flavor: OpenVpnFlavor
    server_dir: Path
    client_template: Path
    ca_cert: Path
    crl: Path
    tls_mode: TlsMode
    tls_crypt_key: Path | None
    tls_crypt_v2_key: Path | None
    tls_auth_key: Path | None
    server_cn: str | None


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _read_server_cn(easyrsa: Path) -> str | None:
    for name in ("SERVER_NAME_GENERATED", "SERVER_CN_GENERATED"):
        path = easyrsa / name
        if not path.is_file():
            continue
        try:
            value = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        except OSError:
            continue
        if value:
            return value
    for cert in sorted(_SERVER_DIR.glob("server_*.crt")):
        return cert.stem
    return None


def _tls_mode_from_server_conf(server_dir: Path) -> TlsMode:
    conf = server_dir / "server.conf"
    if not conf.is_file():
        return "none"
    try:
        text = conf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "none"
    if re.search(r"(?im)^\s*tls-crypt-v2\s+", text):
        return "tls-crypt-v2"
    if re.search(r"(?im)^\s*tls-crypt\s+", text):
        return "tls-crypt"
    if re.search(r"(?im)^\s*tls-auth\s+", text):
        return "tls-auth"
    return "none"


def detect_flavor(server_dir: Path | None = None) -> OpenVpnFlavor:
    """Infer installer flavor from on-disk markers."""
    settings = get_settings()
    configured = (getattr(settings, "OPENVPN_FLAVOR", "auto") or "auto").strip().lower()
    if configured in ("nyr", "angristan"):
        return configured  # type: ignore[return-value]

    root = server_dir or _SERVER_DIR
    if (root / "client-template.txt").is_file():
        return "angristan"
    if (root / "tls-crypt-v2.key").is_file():
        return "angristan"
    if (root / "client-common.txt").is_file() or (root / "tc.key").is_file():
        return "nyr"
    install_script = Path("/root/openvpn-install.sh")
    if install_script.is_file():
        try:
            head = install_script.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            head = ""
        if "angristan" in head.lower() or "tls-crypt-v2" in head:
            return "angristan"
    return "unknown"


def resolve_layout() -> OpenVpnLayout:
    """Resolve paths for the active OpenVPN server install."""
    settings = get_settings()
    server_dir = Path(settings.OPENVPN_CA_CERT_PATH).parent
    if not server_dir.is_dir():
        server_dir = _SERVER_DIR

    flavor = detect_flavor(server_dir)
    tls_mode = _tls_mode_from_server_conf(server_dir)

    configured_template = Path(settings.OPENVPN_CLIENT_COMMON_PATH)
    template = configured_template if configured_template.is_file() else None
    if template is None:
        if flavor == "angristan":
            template = _first_existing(
                server_dir / "client-template.txt",
                server_dir / "client-common.txt",
            )
        else:
            template = _first_existing(
                server_dir / "client-common.txt",
                server_dir / "client-template.txt",
            )
    if template is None:
        template = configured_template

    ca = Path(settings.OPENVPN_CA_CERT_PATH)
    if not ca.is_file():
        ca = server_dir / "ca.crt"

    crl = Path(settings.OPENVPN_CRL_PATH)
    if not crl.is_file():
        crl = server_dir / "crl.pem"

    v2_configured = (settings.OPENVPN_TLS_CRYPT_V2_KEY_PATH or "").strip()
    v2_candidates: list[Path] = []
    if v2_configured:
        v2_candidates.append(Path(v2_configured))
    v2_candidates.append(server_dir / "tls-crypt-v2.key")
    v2_key = _first_existing(*v2_candidates)

    tls_crypt = _first_existing(
        Path(settings.OPENVPN_TLS_CRYPT_KEY_PATH),
        server_dir / "tc.key",
        server_dir / "tls-crypt.key",
    )
    tls_auth = _first_existing(
        server_dir / "tls-auth.key",
        server_dir / "ta.key",
    )

    if tls_mode == "none":
        if v2_key is not None:
            tls_mode = "tls-crypt-v2"
        elif tls_crypt is not None:
            tls_mode = "tls-crypt"
        elif tls_auth is not None:
            tls_mode = "tls-auth"

    easyrsa = Path(settings.EASYRSA_PATH)
    server_cn = _read_server_cn(easyrsa)

    layout = OpenVpnLayout(
        flavor=flavor,
        server_dir=server_dir,
        client_template=template,
        ca_cert=ca,
        crl=crl,
        tls_mode=tls_mode,
        tls_crypt_key=tls_crypt,
        tls_crypt_v2_key=v2_key,
        tls_auth_key=tls_auth,
        server_cn=server_cn,
    )
    logger.debug(
        "OpenVPN layout flavor=%s tls=%s template=%s cn=%s",
        layout.flavor,
        layout.tls_mode,
        layout.client_template,
        layout.server_cn,
    )
    return layout


def angristan_default_extra(server_cn: str | None) -> str:
    """Cipher / TLS lines Angristan puts in client-template beyond basic remotes."""
    lines = ["explicit-exit-notify"]
    if server_cn:
        lines.append(f"verify-x509-name {server_cn} name")
    lines.extend(
        [
            "auth-nocache",
            "cipher AES-128-GCM",
            "ignore-unknown-option data-ciphers",
            "data-ciphers AES-128-GCM",
            "ncp-ciphers AES-128-GCM",
            "tls-client",
            "tls-version-min 1.2",
            "tls-cipher TLS-ECDHE-ECDSA-WITH-AES-128-GCM-SHA256",
            "tls-ciphersuites TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256:TLS_CHACHA20_POLY1305_SHA256",
            "setenv opt block-outside-dns",
        ]
    )
    return "\n".join(lines)
