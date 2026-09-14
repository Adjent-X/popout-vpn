"""Simple in-memory sliding-window rate limiter (per key, typically client IP)."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str, *, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        window_start = now - window_seconds

        async with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < window_start:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please try again later.",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)


auth_rate_limiter = SlidingWindowRateLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def enforce_auth_rate_limit(request: Request) -> None:
    """Per-source (client IP) limit for unauthenticated auth endpoints."""
    settings = get_settings()
    ip = client_ip(request)
    await auth_rate_limiter.hit(
        f"auth:ip:{ip}",
        limit=max(1, int(settings.AUTH_RATE_LIMIT_REQUESTS)),
        window_seconds=max(1, int(settings.AUTH_RATE_LIMIT_WINDOW_SECONDS)),
    )


async def enforce_auth_email_rate_limit(email: str) -> None:
    """Per-email limit so a single mailbox cannot be brute-forced across IPs."""
    settings = get_settings()
    key = (email or "").strip().lower()
    if not key:
        return
    await auth_rate_limiter.hit(
        f"auth:email:{key}",
        limit=max(1, int(settings.AUTH_RATE_LIMIT_EMAIL_REQUESTS)),
        window_seconds=max(1, int(settings.AUTH_RATE_LIMIT_EMAIL_WINDOW_SECONDS)),
    )
