"""Periodic zip backups of the panel, utilities, OpenVPN PKI, and Mongo data."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = "/root/backups"
DEFAULT_PANEL_ROOT = "/opt/popout-vpn"
BACKUP_PREFIX = "popout-vpn-backup_"
BACKUP_SUFFIX = ".zip"

# Rebuildable / noisy paths — keep zips lean and avoid locking issues.
EXCLUDE_DIR_NAMES = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".turbo",
    "cache",
}
EXCLUDE_FILE_SUFFIXES = (".pyc", ".pyo", ".log")

# Critical Mongo collections for restore (skip host_metrics — large & regenerable).
MONGO_BACKUP_COLLECTIONS = (
    "admins",
    "client_configs",
    "site_settings",
    "invite_tokens",
    "bandwidth_monthly",
    "bandwidth_totals",
    "attack_events",
    "connection_events",
)

OPENVPN_SERVER_DIR = Path("/etc/openvpn/server")
OPENVPN_BACKUP_FILES = (
    "ca.crt",
    "ca.key",
    "server.crt",
    "server.key",
    "dh.pem",
    "tc.key",
    "tls-crypt.key",
    "tls-crypt-v2.key",
    "tls-auth.key",
    "ta.key",
    "crl.pem",
    "server.conf",
    "ipp.txt",
    "client-common.txt",
    "client-template.txt",
)


def backup_dir() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "BACKUP_DIR", None) or DEFAULT_BACKUP_DIR)


def panel_root() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "PANEL_ROOT", None) or DEFAULT_PANEL_ROOT)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _should_skip(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    for part in rel.parts:
        if part in EXCLUDE_DIR_NAMES:
            return True
    if path.is_file() and path.name.endswith(EXCLUDE_FILE_SUFFIXES):
        return True
    # Frontend .next/cache only; keep the rest of .next when present
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == ".next" and parts[1] == "cache":
        return True
    if len(parts) >= 3 and parts[0] == "frontend" and parts[1] == ".next" and parts[2] == "cache":
        return True
    return False


def _add_path_to_zip(zf: zipfile.ZipFile, source: Path, arc_prefix: str) -> int:
    """Add a file or directory under arc_prefix. Returns file count."""
    if not source.exists():
        logger.warning("Backup skip missing path: %s", source)
        return 0
    count = 0
    if source.is_file():
        zf.write(source, arcname=f"{arc_prefix}/{source.name}")
        return 1
    root = source.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        # Prune excluded dirs in-place
        dirnames[:] = [
            d
            for d in dirnames
            if d not in EXCLUDE_DIR_NAMES
            and not _should_skip(current / d, root)
        ]
        for name in filenames:
            path = current / name
            if _should_skip(path, root):
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            arcname = f"{arc_prefix}/{rel.as_posix()}"
            try:
                zf.write(path, arcname=arcname)
                count += 1
            except OSError:
                logger.warning("Could not add %s to backup", path, exc_info=True)
    return count


def _add_openvpn_pki(zf: zipfile.ZipFile) -> int:
    """Include OpenVPN server PKI + config needed to rebuild the VPN."""
    count = 0
    for name in OPENVPN_BACKUP_FILES:
        path = OPENVPN_SERVER_DIR / name
        if not path.is_file():
            logger.warning("Backup skip missing OpenVPN file: %s", path)
            continue
        try:
            zf.write(path, arcname=f"openvpn/{name}")
            count += 1
        except OSError:
            logger.warning("Could not add OpenVPN file %s", path, exc_info=True)
    easy_rsa = OPENVPN_SERVER_DIR / "easy-rsa"
    if easy_rsa.is_dir():
        count += _add_path_to_zip(zf, easy_rsa, "openvpn/easy-rsa")
    return count


def _dump_mongo_collections(dest: Path) -> dict[str, int]:
    """
    Dump critical collections as Extended JSON (bson.json_util).
    Returns {collection: doc_count}.
    """
    from bson import json_util
    from pymongo import MongoClient

    settings = get_settings()
    uri = settings.mongodb_connection_uri
    db_name = getattr(settings, "MONGODB_DB_NAME", "popout_vpn") or "popout_vpn"

    client = MongoClient(uri, serverSelectionTimeoutMS=12000)
    db = client[db_name]
    dest.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name in MONGO_BACKUP_COLLECTIONS:
        out = dest / f"{name}.json"
        docs = list(db[name].find({}))
        out.write_text(
            json_util.dumps(docs, indent=2),
            encoding="utf-8",
        )
        counts[name] = len(docs)
    manifest = {
        "created_at": _utcnow().isoformat(),
        "database": db_name,
        "collections": counts,
    }
    (dest / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    client.close()
    return counts


def list_backup_zips(directory: Path | None = None) -> list[Path]:
    root = directory or backup_dir()
    if not root.is_dir():
        return []
    files = [
        p
        for p in root.iterdir()
        if p.is_file()
        and p.name.startswith(BACKUP_PREFIX)
        and p.name.endswith(BACKUP_SUFFIX)
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def prune_backups(keep: int, directory: Path | None = None) -> list[str]:
    keep = max(1, int(keep))
    removed: list[str] = []
    for path in list_backup_zips(directory)[keep:]:
        try:
            path.unlink()
            removed.append(path.name)
            logger.info("Pruned old backup %s", path.name)
        except OSError:
            logger.exception("Failed to prune backup %s", path)
    return removed


def create_backup_zip(*, keep_count: int = 3) -> dict[str, Any]:
    """
    Write a timestamped zip under /root/backups and prune older copies.

    Includes:
    - panel tree (+ .next, env)
    - monitor scripts + popout-vpn config + systemd unit
    - OpenVPN PKI / server config / easy-rsa
    - MongoDB dump of critical collections (not host_metrics)
    """
    dest_dir = backup_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dest_dir, 0o700)
    except OSError:
        pass

    stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = dest_dir / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"
    tmp_path = dest_dir / f".{BACKUP_PREFIX}{stamp}.partial.zip"

    sources: list[tuple[Path, str]] = [
        (panel_root(), "vpn-panel"),
        (Path("/root/monitor"), "monitor"),
        (Path("/etc/popout-vpn"), "etc-popout-vpn"),
        (Path("/etc/systemd/system/popout-attacks.service"), "systemd"),
    ]

    total_files = 0
    mongo_counts: dict[str, int] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="popout-mongo-backup-") as tmp_mongo:
            mongo_dir = Path(tmp_mongo) / "mongodb"
            try:
                mongo_counts = _dump_mongo_collections(mongo_dir)
            except Exception:
                logger.exception("MongoDB dump failed; continuing with filesystem backup")
                mongo_counts = {}

            with zipfile.ZipFile(
                tmp_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as zf:
                for source, prefix in sources:
                    total_files += _add_path_to_zip(zf, source, prefix)
                total_files += _add_openvpn_pki(zf)
                if mongo_dir.is_dir():
                    total_files += _add_path_to_zip(zf, mongo_dir, "mongodb")
                host = os.uname().nodename if hasattr(os, "uname") else "unknown"
                meta = (
                    f"created_at={_utcnow().isoformat()}\n"
                    f"host={host}\n"
                    f"files={total_files}\n"
                    f"mongo_collections={json.dumps(mongo_counts)}\n"
                )
                zf.writestr("BACKUP_META.txt", meta)
        tmp_path.replace(out_path)
        try:
            os.chmod(out_path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    removed = prune_backups(max(1, int(keep_count)), dest_dir)
    size = out_path.stat().st_size if out_path.is_file() else 0
    logger.info(
        "Backup written %s (%s bytes, %s files, mongo=%s); pruned=%s",
        out_path.name,
        size,
        total_files,
        mongo_counts,
        removed,
    )
    return {
        "path": str(out_path),
        "name": out_path.name,
        "size_bytes": size,
        "files": total_files,
        "mongo_collections": mongo_counts,
        "pruned": removed,
    }


async def run_scheduled_backup() -> dict[str, Any] | None:
    """Load retention from site settings and create a backup off the event loop."""
    import asyncio

    keep = 3
    try:
        from app.db import is_connected
        from app.services.site_settings import get_site_settings

        if is_connected():
            data, _ = await get_site_settings(use_cache=True)
            keep = max(1, int(data.backup_keep_count or 3))
    except Exception:
        logger.exception("Could not load backup_keep_count; using %s", keep)

    try:
        return await asyncio.to_thread(create_backup_zip, keep_count=keep)
    except Exception:
        logger.exception("Scheduled backup failed")
        return None
