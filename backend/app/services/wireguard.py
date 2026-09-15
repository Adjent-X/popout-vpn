"""WireGuard peer management (Angristan /etc/wireguard layout)."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from ipaddress import ip_interface
from pathlib import Path

logger = logging.getLogger(__name__)

PARAMS = Path("/etc/wireguard/params")
CLIENTS_DIR = Path("/etc/wireguard/clients")


class WireGuardError(Exception):
    """Raised when a WireGuard peer operation fails."""


def wg_available() -> bool:
    return PARAMS.is_file() and shutil_which("wg")


def shutil_which(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def _read_params() -> dict[str, str]:
    if not PARAMS.is_file():
        raise WireGuardError(f"Missing {PARAMS} — run the Angristan WireGuard installer")
    data: dict[str, str] = {}
    for line in PARAMS.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, val = line.split("=", 1)
        data[key.strip()] = val.strip()
    return data


def _write_params(data: dict[str, str]) -> None:
    PARAMS.write_text("".join(f"{k}={v}\n" for k, v in data.items()), encoding="utf-8")
    os.chmod(PARAMS, 0o600)


def _nic() -> str:
    return _read_params().get("SERVER_WG_NIC", "wg0")


def _conf_path() -> Path:
    return Path("/etc/wireguard") / f"{_nic()}.conf"


def _run(args: list[str], *, stdin: str | None = None) -> str:
    proc = subprocess.run(
        args,
        input=stdin,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise WireGuardError(
            (proc.stderr or proc.stdout or " ".join(args)).strip() or "command failed"
        )
    return proc.stdout


def _next_client_ipv4(params: dict[str, str], used: set[str]) -> str:
    server = params.get("SERVER_WG_IPV4") or "10.66.66.1"
    network = ip_interface(f"{server}/24").network
    for host in network.hosts():
        ip = str(host)
        if ip == server or ip in used:
            continue
        return ip
    raise WireGuardError("WireGuard IPv4 pool exhausted")


def _used_peer_ipv4s(conf_text: str) -> set[str]:
    return set(re.findall(r"(?im)^AllowedIPs\s*=\s*([0-9.]+)/32", conf_text))


def add_peer(client_name: str) -> tuple[str, str]:
    """Create a peer and return (client_conf_body, assigned_ipv4)."""
    if not wg_available():
        raise WireGuardError("WireGuard is not installed on this host")
    params = _read_params()
    conf_path = _conf_path()
    if not conf_path.is_file():
        raise WireGuardError(f"Missing {conf_path}")

    priv = _run(["wg", "genkey"]).strip()
    pub = _run(["wg", "pubkey"], stdin=priv).strip()
    psk = _run(["wg", "genpsk"]).strip()

    text = conf_path.read_text(encoding="utf-8")
    ipv4 = _next_client_ipv4(params, _used_peer_ipv4s(text))
    ipv6_base = params.get("SERVER_WG_IPV6") or "fd42:42:42::1"
    last = ipv4.split(".")[-1]
    ipv6 = re.sub(r":[^:]+$", f":{last}", ipv6_base)

    block = (
        f"\n### Client {client_name}\n"
        f"[Peer]\n"
        f"PublicKey = {pub}\n"
        f"PresharedKey = {psk}\n"
        f"AllowedIPs = {ipv4}/32,{ipv6}/128\n"
    )
    conf_path.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    os.chmod(conf_path, 0o600)

    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CLIENTS_DIR, 0o700)
    (CLIENTS_DIR / f"{client_name}.key").write_text(priv, encoding="utf-8")
    (CLIENTS_DIR / f"{client_name}.psk").write_text(psk, encoding="utf-8")
    os.chmod(CLIENTS_DIR / f"{client_name}.key", 0o600)
    os.chmod(CLIENTS_DIR / f"{client_name}.psk", 0o600)

    _sync_conf()
    body = build_client_conf(client_name, ipv4=ipv4, ipv6=ipv6, priv=priv, psk=psk)
    (CLIENTS_DIR / f"{client_name}.conf").write_text(body, encoding="utf-8")
    os.chmod(CLIENTS_DIR / f"{client_name}.conf", 0o600)
    logger.info("Added WireGuard peer %s (%s)", client_name, ipv4)
    return body, ipv4


def build_client_conf(
    client_name: str,
    *,
    ipv4: str,
    ipv6: str | None = None,
    priv: str,
    psk: str,
) -> str:
    params = _read_params()
    host = params.get("SERVER_PUB_IP") or "vpn.example.com"
    port = params.get("SERVER_PORT") or "51820"
    dns1 = params.get("CLIENT_DNS_1") or "1.1.1.1"
    dns2 = params.get("CLIENT_DNS_2") or dns1
    allowed = params.get("ALLOWED_IPS") or "0.0.0.0/0,::/0"
    mtu = params.get("CLIENT_MTU") or "1420"
    keepalive = params.get("CLIENT_KEEPALIVE") or "25"
    dns_line = dns1 if dns1 == dns2 else f"{dns1},{dns2}"
    address = f"{ipv4}/32"
    if ipv6 and ":" in str(ipv6):
        address = f"{ipv4}/32,{ipv6}/128"
    _ = client_name
    return (
        "[Interface]\n"
        f"PrivateKey = {priv}\n"
        f"Address = {address}\n"
        f"DNS = {dns_line}\n"
        f"MTU = {mtu}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {params.get('SERVER_PUB_KEY', '')}\n"
        f"PresharedKey = {psk}\n"
        f"Endpoint = {host}:{port}\n"
        f"AllowedIPs = {allowed}\n"
        f"PersistentKeepalive = {keepalive}\n"
    )


def rebuild_client_conf(client_name: str) -> str:
    path = CLIENTS_DIR / f"{client_name}.conf"
    if not path.is_file():
        raise WireGuardError(f"WireGuard client {client_name} not found")
    existing = path.read_text(encoding="utf-8")
    priv_m = re.search(r"(?m)^PrivateKey\s*=\s*(\S+)", existing)
    addr_m = re.search(r"(?m)^Address\s*=\s*(.+)$", existing)
    psk_m = re.search(r"(?m)^PresharedKey\s*=\s*(\S+)", existing)
    if not (priv_m and addr_m and psk_m):
        return existing
    addr = addr_m.group(1).strip()
    ipv4 = addr.split(",")[0].split("/")[0]
    ipv6 = addr.split(",")[1].split("/")[0] if "," in addr else None
    body = build_client_conf(
        client_name,
        ipv4=ipv4,
        ipv6=ipv6,
        priv=priv_m.group(1),
        psk=psk_m.group(1),
    )
    path.write_text(body, encoding="utf-8")
    return body


def revoke_peer(client_name: str) -> None:
    if not wg_available():
        return
    conf_path = _conf_path()
    if not conf_path.is_file():
        return
    text = conf_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(?ms)^### Client {re.escape(client_name)}\n\[Peer\].*?(?=^### Client |\Z)"
    )
    new, n = pattern.subn("", text)
    if n:
        conf_path.write_text(new.rstrip() + "\n", encoding="utf-8")
        _sync_conf()
    for suffix in (".conf", ".key", ".psk"):
        p = CLIENTS_DIR / f"{client_name}{suffix}"
        if p.is_file():
            p.unlink()
    logger.info("Removed WireGuard peer %s", client_name)


def _sync_conf() -> None:
    nic = _nic()
    strip = subprocess.run(
        ["wg-quick", "strip", nic],
        check=False,
        capture_output=True,
        text=True,
    )
    if strip.returncode != 0:
        logger.warning("wg-quick strip failed: %s", strip.stderr)
        return
    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        handle.write(strip.stdout)
        tmp = handle.name
    try:
        proc = subprocess.run(
            ["wg", "syncconf", nic, tmp],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            logger.warning("wg syncconf failed: %s", proc.stderr)
    finally:
        os.unlink(tmp)


def update_server_params(
    *,
    endpoint: str | None = None,
    port: int | None = None,
    dns: str | None = None,
    allowed_ips: str | None = None,
    mtu: int | None = None,
    keepalive: int | None = None,
) -> None:
    if not PARAMS.is_file():
        return
    params = _read_params()
    if endpoint:
        params["SERVER_PUB_IP"] = endpoint
    if port is not None:
        params["SERVER_PORT"] = str(int(port))
        conf_path = _conf_path()
        if conf_path.is_file():
            text = conf_path.read_text(encoding="utf-8")
            text = re.sub(
                r"(?m)^ListenPort\s*=.*$",
                f"ListenPort = {int(port)}",
                text,
                count=1,
            )
            conf_path.write_text(text, encoding="utf-8")
        _sync_conf()
    if dns:
        parts = [p.strip() for p in dns.split(",") if p.strip()]
        if parts:
            params["CLIENT_DNS_1"] = parts[0]
            params["CLIENT_DNS_2"] = parts[1] if len(parts) > 1 else parts[0]
    if allowed_ips:
        params["ALLOWED_IPS"] = allowed_ips
    if mtu is not None:
        params["CLIENT_MTU"] = str(int(mtu))
    if keepalive is not None:
        params["CLIENT_KEEPALIVE"] = str(int(keepalive))
    _write_params(params)
    if CLIENTS_DIR.is_dir():
        for conf in CLIENTS_DIR.glob("*.conf"):
            try:
                rebuild_client_conf(conf.stem)
            except WireGuardError:
                logger.warning("Could not refresh %s", conf)
