from __future__ import annotations

import asyncio
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_connect_lock = asyncio.Lock()


def get_client() -> AsyncIOMotorClient:
    if _client is None:
        raise RuntimeError("MongoDB client is not initialized")
    return _client


def get_db() -> AsyncIOMotorDatabase:
    settings = get_settings()
    return get_client()[settings.MONGODB_DB_NAME]


def is_connected() -> bool:
    return _client is not None


def _build_client() -> AsyncIOMotorClient:
    settings = get_settings()
    return AsyncIOMotorClient(
        settings.mongodb_connection_uri,
        serverSelectionTimeoutMS=5_000,
        connectTimeoutMS=5_000,
        # Localhost admin panel — lean pool, still enough for concurrent UI polls
        maxPoolSize=16,
        minPoolSize=1,
        maxIdleTimeMS=60_000,
        waitQueueTimeoutMS=5_000,
        retryWrites=True,
        directConnection=True,
    )


async def connect_db(*, retries: int = 12, delay_seconds: float = 1.0) -> None:
    """
    Connect to the local MongoDB. Retries so panel boot survives brief mongod restarts.
    """
    global _client
    async with _connect_lock:
        last_exc: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
            client: AsyncIOMotorClient | None = None
            try:
                if _client is not None:
                    try:
                        await _client.admin.command("ping")
                        return
                    except Exception:
                        try:
                            _client.close()
                        except Exception:
                            pass
                        _client = None

                client = _build_client()
                await client.admin.command("ping")
                _client = client
                logger.info(
                    "MongoDB connected on attempt %s/%s (%s)",
                    attempt,
                    retries,
                    get_settings().MONGODB_URI,
                )
                return
            except Exception as exc:
                last_exc = exc
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
                logger.warning(
                    "MongoDB connect attempt %s/%s failed: %s",
                    attempt,
                    retries,
                    exc,
                )
                if attempt < retries:
                    await asyncio.sleep(delay_seconds)
        assert last_exc is not None
        raise last_exc


async def ensure_connected() -> bool:
    """Best-effort reconnect for request handlers after a transient outage."""
    if _client is not None:
        try:
            await _client.admin.command("ping")
            return True
        except Exception:
            logger.warning("MongoDB ping failed; reconnecting")
    try:
        await connect_db(retries=3, delay_seconds=0.5)
        return True
    except Exception:
        logger.exception("MongoDB reconnect failed")
        return False


async def close_db() -> None:
    global _client
    async with _connect_lock:
        if _client is not None:
            _client.close()
            _client = None


async def ensure_indexes() -> None:
    """Create indexes declared for Phase 2 schema. Safe to call on every startup."""
    db = get_db()

    await db.admins.create_index("email", unique=True, name="uniq_email")

    await db.client_configs.create_index(
        "client_name",
        unique=True,
        name="uniq_client_name",
    )
    await db.client_configs.create_index(
        "expires_at",
        name="idx_expires_at",
    )
    await db.client_configs.create_index(
        "status",
        name="idx_status",
    )
    await db.client_configs.create_index(
        "owner_admin_id",
        name="idx_owner_admin_id",
    )
    await db.client_configs.create_index(
        [("status", 1), ("expires_at", 1)],
        name="idx_status_expires_at",
    )

    await db.registration_tokens.create_index(
        "token",
        unique=True,
        name="uniq_token",
    )
    await db.registration_tokens.create_index(
        "expires_at",
        name="idx_expires_at",
    )

    await db.api_keys.create_index(
        [("key_prefix", 1), ("key_hash", 1)],
        unique=True,
        name="uniq_api_key_prefix_hash",
    )
    await db.api_keys.create_index(
        "owner_admin_id",
        name="idx_api_keys_owner",
    )

    await db.host_metrics.create_index("ts", name="idx_host_metrics_ts")
    await db.connection_events.create_index(
        [("client_name", 1), ("at", -1)],
        name="idx_conn_events_client_at",
    )
    await db.connection_events.create_index(
        [("config_id", 1), ("at", -1)],
        name="idx_conn_events_config_at",
    )
    await db.connection_events.create_index(
        [("wan_ip", 1), ("at", -1)],
        name="idx_conn_events_wan_at",
    )
    await db.attack_events.create_index(
        [("detected_at", -1)],
        name="idx_attack_events_detected_at",
    )
    await db.attack_events.create_index(
        [("pcap_file", 1)],
        name="idx_attack_events_pcap_file",
    )


COLLECTION_NAMES: dict[str, str] = {
    "admins": "admins",
    "client_configs": "client_configs",
    "registration_tokens": "registration_tokens",
    "site_settings": "site_settings",
}


def collection(name: str) -> Any:
    return get_db()[COLLECTION_NAMES[name]]
