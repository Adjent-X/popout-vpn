"""OpenVPN integration for Nyr and Angristan openvpn-install layouts.

Calls easy-rsa directly (never the interactive installer menu). Assembles
.ovpn from site-settings template + certs + tls-crypt / tls-crypt-v2 / tls-auth.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.services.openvpn_layout import resolve_layout

logger = logging.getLogger(__name__)

# Same charset Nyr/Angristan use when sanitizing client names
_CLIENT_NAME_RE = re.compile(r"[^0-9a-zA-Z_-]+")


class OpenVPNError(Exception):
    """Raised when an easy-rsa / OpenVPN shell operation fails."""


@dataclass(frozen=True)
class BuiltClient:
    client_name: str
    cert_serial: str
    ovpn_content: str


def sanitize_client_name(label: str) -> str:
    """Installer-compatible CN plus a short suffix so labels can collide safely."""
    base = _CLIENT_NAME_RE.sub("_", label.strip())
    if not base:
        base = "client"
    base = base[:40]
    suffix = uuid.uuid4().hex[:8]
    return f"{base}-{suffix}"


def _easyrsa_dir() -> Path:
    return Path(get_settings().EASYRSA_PATH)


def _pki_dir() -> Path:
    return _easyrsa_dir() / "pki"


def _inline_path(client_name: str) -> Path:
    return _pki_dir() / "inline" / "private" / f"{client_name}.inline"


async def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> str:
    env = os.environ.copy()
    env.setdefault("EASYRSA_BATCH", "1")
    if env_extra:
        env.update(env_extra)

    logger.info("Running: %s (cwd=%s)", " ".join(args), cwd or ".")
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        logger.error(
            "Command failed (%s): %s\nstdout=%s\nstderr=%s",
            proc.returncode,
            args,
            stdout,
            stderr,
        )
        raise OpenVPNError(f"Command failed: {' '.join(args)}")
    return stdout


async def _run_easyrsa(*easyrsa_args: str) -> str:
    settings = get_settings()
    cwd = _easyrsa_dir()
    if not cwd.is_dir():
        raise OpenVPNError(f"EASYRSA_PATH does not exist: {cwd}")
    return await _run([settings.EASYRSA_BIN, *easyrsa_args], cwd=cwd)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OpenVPNError(f"Unable to read {path}") from exc


def _strip_hash_comments(text: str) -> str:
    """Match Nyr: grep -vh '^#' …"""
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    return "\n".join(lines).rstrip() + "\n"


async def _client_common_header() -> str:
    """Portal site settings drive the .ovpn header (synced to client template)."""
    from app.services.ovpn_template import build_client_common_text
    from app.services.site_settings import get_site_settings

    data, _ = await get_site_settings()
    return _strip_hash_comments(build_client_common_text(data))


async def _generate_tls_crypt_v2_client_block(server_key: Path) -> str:
    """Angristan-style per-client tls-crypt-v2 key wrapped for .ovpn."""
    openvpn = shutil.which("openvpn")
    if not openvpn:
        raise OpenVPNError(
            "openvpn binary not found (needed for tls-crypt-v2 client keys)"
        )

    tmp = Path(f"/tmp/tls-crypt-v2-client-{uuid.uuid4().hex}.key")
    try:
        await _run(
            [
                openvpn,
                "--tls-crypt-v2",
                str(server_key),
                "--genkey",
                "tls-crypt-v2-client",
                str(tmp),
            ]
        )
        key_body = _read_text(tmp).strip()
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return f"<tls-crypt-v2>\n{key_body}\n</tls-crypt-v2>\n"


def _pem_body(path: Path) -> str:
    """Return PEM contents (strip non-PEM preamble if present)."""
    text = _read_text(path)
    match = re.search(
        r"(-----BEGIN [^-]+-----.*?-----END [^-]+-----)",
        text,
        flags=re.S,
    )
    if match:
        return match.group(1).strip()
    return text.strip()


def _inline_usable(inline_text: str) -> bool:
    if "TLS Key not found" in inline_text:
        return False
    return any(
        tag in inline_text
        for tag in ("<tls-crypt-v2>", "<tls-crypt>", "<tls-auth>", "<secret>")
    )


async def assemble_ovpn(*, client_name: str) -> str:
    """
    Assemble .ovpn from site-settings client template + certs + TLS material.

    Angristan (tls-crypt-v2): always generate a fresh per-client key — Easy-RSA
    inline files usually lack it.
    Nyr (tls-crypt): prefer Easy-RSA inline when it includes <tls-crypt>.
    """
    layout = resolve_layout()
    header = await _client_common_header()
    pki = _pki_dir()
    cert_path = pki / "issued" / f"{client_name}.crt"
    key_path = pki / "private" / f"{client_name}.key"
    if not cert_path.is_file() or not key_path.is_file():
        raise OpenVPNError(f"Client cert/key missing for {client_name}")

    ca = _pem_body(layout.ca_cert)
    cert = _pem_body(cert_path)
    key = _pem_body(key_path)

    if layout.tls_mode == "tls-crypt-v2":
        if layout.tls_crypt_v2_key is None:
            raise OpenVPNError("tls-crypt-v2 enabled but server key file is missing")
        tls_block = await _generate_tls_crypt_v2_client_block(layout.tls_crypt_v2_key)
        return (
            f"{header.rstrip()}\n\n"
            f"<ca>\n{ca}\n</ca>\n\n"
            f"<cert>\n{cert}\n</cert>\n\n"
            f"<key>\n{key}\n</key>\n\n"
            f"{tls_block}"
        )

    inline = _inline_path(client_name)
    if inline.is_file():
        inline_text = _strip_hash_comments(_read_text(inline))
        if _inline_usable(inline_text):
            return header.rstrip() + "\n" + inline_text

    if layout.tls_mode == "tls-crypt":
        if layout.tls_crypt_key is None:
            raise OpenVPNError("tls-crypt enabled but key file is missing")
        tls_crypt = _read_text(layout.tls_crypt_key).strip()
        return (
            f"{header.rstrip()}\n\n"
            f"<ca>\n{ca}\n</ca>\n\n"
            f"<cert>\n{cert}\n</cert>\n\n"
            f"<key>\n{key}\n</key>\n\n"
            f"<tls-crypt>\n{tls_crypt}\n</tls-crypt>\n"
        )

    if layout.tls_mode == "tls-auth":
        if layout.tls_auth_key is None:
            raise OpenVPNError("tls-auth enabled but key file is missing")
        ta = _read_text(layout.tls_auth_key).strip()
        return (
            f"{header.rstrip()}\n\n"
            f"<ca>\n{ca}\n</ca>\n\n"
            f"<cert>\n{cert}\n</cert>\n\n"
            f"<key>\n{key}\n</key>\n\n"
            f"<tls-auth>\n{ta}\n</tls-auth>\n"
            f"key-direction 1\n"
        )

    logger.warning("Assembling .ovpn for %s without TLS wrap key", client_name)
    return (
        f"{header.rstrip()}\n\n"
        f"<ca>\n{ca}\n</ca>\n\n"
        f"<cert>\n{cert}\n</cert>\n\n"
        f"<key>\n{key}\n</key>\n"
    )


async def read_cert_serial(client_name: str) -> str:
    cert_path = _pki_dir() / "issued" / f"{client_name}.crt"
    if not cert_path.is_file():
        raise OpenVPNError(f"Client cert not found: {cert_path}")

    openssl = shutil.which("openssl")
    if openssl:
        out = await _run(
            [openssl, "x509", "-in", str(cert_path), "-noout", "-serial"],
        )
        value = out.strip()
        if "=" in value:
            return value.split("=", 1)[1].strip().lower()
        return value.lower()

    text = _read_text(cert_path)
    match = re.search(
        r"Serial Number:\s*(?:([0-9A-Fa-f:]+)|(?:\n\s+)([0-9A-Fa-f:]+))",
        text,
    )
    if not match:
        raise OpenVPNError("Could not determine certificate serial")
    raw = (match.group(1) or match.group(2)).replace(":", "").lower()
    return raw


async def build_client(label: str) -> BuiltClient:
    """easyrsa --batch --days=3650 build-client-full … nopass (Nyr + Angristan)."""
    client_name = sanitize_client_name(label)
    await _run_easyrsa(
        "--batch", "--days=3650", "build-client-full", client_name, "nopass"
    )
    serial = await read_cert_serial(client_name)
    ovpn = await assemble_ovpn(client_name=client_name)
    return BuiltClient(client_name=client_name, cert_serial=serial, ovpn_content=ovpn)


def _chown_crl(path: Path) -> None:
    """Chown CRL so OpenVPN can re-read it after drop-privs."""
    settings = get_settings()
    user = settings.OPENVPN_CRL_OWNER
    group = settings.OPENVPN_CRL_GROUP
    if not user:
        return
    try:
        shutil.chown(path, user=user, group=group or None)
    except (LookupError, OSError, NotImplementedError) as exc:
        logger.warning("Could not chown CRL %s to %s:%s (%s)", path, user, group, exc)


async def revoke_client(client_name: str) -> None:
    """
    easyrsa revoke → gen-crl → install crl.pem → chown.
    CRL is re-read on connect; restart is optional via OPENVPN_RELOAD_CMD.
    """
    layout = resolve_layout()
    pki = _pki_dir()
    pki_crl = pki / "crl.pem"
    dest_crl = layout.crl

    await _run_easyrsa("--batch", "revoke", client_name)
    await _run_easyrsa("--batch", "--days=3650", "gen-crl")

    if not pki_crl.is_file():
        raise OpenVPNError(f"CRL not found after gen-crl: {pki_crl}")

    try:
        if dest_crl.exists():
            dest_crl.unlink()
        for leftover in (
            pki / "reqs" / f"{client_name}.req",
            pki / "private" / f"{client_name}.key",
        ):
            if leftover.exists():
                leftover.unlink()
        shutil.copy2(pki_crl, dest_crl)
    except OSError as exc:
        raise OpenVPNError(f"Failed to install CRL at {dest_crl}") from exc

    _chown_crl(dest_crl)

    reload_cmd = get_settings().OPENVPN_RELOAD_CMD.strip()
    if reload_cmd:
        await _run(reload_cmd.split())

    logger.info("Revoked OpenVPN client %s; CRL updated at %s", client_name, dest_crl)


async def rebuild_ovpn(client_name: str) -> str:
    return await assemble_ovpn(client_name=client_name)


@dataclass(frozen=True)
class PkiClientInfo:
    """A client certificate present on disk (easy-rsa PKI)."""

    client_name: str
    cert_serial: str
    revoked: bool
    has_key: bool
    not_before: str | None = None  # ISO-ish from openssl when available


def _parse_index_txt(index_path: Path) -> dict[str, str]:
    """Map CN -> status letter (V/R/E) from Easy-RSA index.txt."""
    out: dict[str, str] = {}
    if not index_path.is_file():
        return out
    try:
        text = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        status, dn = parts[0].strip(), parts[-1].strip()
        cn = None
        for piece in dn.split("/"):
            if piece.startswith("CN="):
                cn = piece[3:]
                break
        if cn:
            out[cn] = status
    return out


def _server_cn_basenames() -> set[str]:
    """CNs / stems that must never be imported as VPN clients."""
    names = {"ca", "server"}
    layout = resolve_layout()
    if layout.server_cn:
        names.add(layout.server_cn)
    server_dir = layout.server_dir
    conf = server_dir / "server.conf"
    if conf.is_file():
        try:
            text = conf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for match in re.finditer(r"(?im)^\s*cert\s+(\S+)", text):
            stem = Path(match.group(1)).stem
            if stem:
                names.add(stem)
    for cert in server_dir.glob("server_*.crt"):
        names.add(cert.stem)
    easyrsa = _easyrsa_dir()
    for marker in ("SERVER_NAME_GENERATED", "SERVER_CN_GENERATED"):
        path = easyrsa / marker
        if path.is_file():
            try:
                value = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            except OSError:
                value = ""
            if value:
                names.add(value)
    return names


async def _cert_not_before(cert_path: Path) -> str | None:
    openssl = shutil.which("openssl")
    if not openssl:
        return None
    try:
        out = await _run(
            [openssl, "x509", "-in", str(cert_path), "-noout", "-startdate"],
        )
    except OpenVPNError:
        return None
    # notBefore=Aug 27 17:14:37 2026 GMT
    value = out.strip()
    if "=" in value:
        return value.split("=", 1)[1].strip()
    return value or None


async def list_pki_clients() -> list[PkiClientInfo]:
    """
    Scan easy-rsa PKI for client certs (issued/*.crt with matching private key),
    excluding CA / server CNs. Includes revoked entries still present on disk.
    """
    pki = _pki_dir()
    issued = pki / "issued"
    private = pki / "private"
    if not issued.is_dir():
        return []

    index_status = _parse_index_txt(pki / "index.txt")
    exclude = {n.lower() for n in _server_cn_basenames()}
    clients: list[PkiClientInfo] = []

    for cert_path in sorted(issued.glob("*.crt")):
        name = cert_path.stem
        if not name or name.lower() in exclude:
            continue
        if name.lower().startswith("server_"):
            continue
        key_path = private / f"{name}.key"
        has_key = key_path.is_file()
        status = index_status.get(name, "V")
        revoked = status == "R"
        try:
            serial = await read_cert_serial(name)
        except OpenVPNError:
            logger.warning("Skipping PKI cert without readable serial: %s", name)
            continue
        not_before = await _cert_not_before(cert_path)
        clients.append(
            PkiClientInfo(
                client_name=name,
                cert_serial=serial,
                revoked=revoked,
                has_key=has_key,
                not_before=not_before,
            )
        )
    return clients


def parse_ipp_map(ipp_path: Path | None = None) -> dict[str, str]:
    """CN -> VPN IP from OpenVPN ifconfig-pool-persist file."""
    path = ipp_path or Path(get_settings().OPENVPN_IPP_PATH)
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        cn, ip = line.split(",", 1)
        cn, ip = cn.strip(), ip.strip()
        if cn and ip:
            out[cn] = ip
    return out
