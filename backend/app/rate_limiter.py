"""Centralized rate limiting and request throttling engine.

Supports Redis/Valkey sliding window with an in-memory fallback for development and offline testing.
"""

from collections import defaultdict
import logging
import time
from typing import Callable

from fastapi import HTTPException, Request, status
from redis import Redis

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

# Fallback in-memory timestamp store: {scope:key -> [timestamp1, timestamp2, ...]}
_MEMORY_RATE_LIMITS: dict[str, list[float]] = defaultdict(list)


def get_client_ip(request: Request) -> str:
    """Return the client IP assigned by the ASGI server or trusted proxy middleware."""
    return request.client.host if request.client else "unknown-client"


def _full_key(key: str, scope: str) -> str:
    return f"ratelimit:{scope}:{key}"


def check_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int,
    scope: str = "default",
) -> tuple[bool, int]:
    """Check if the key is within rate limit.

    Returns (allowed: bool, retry_after_seconds: int).
    """
    settings = get_settings()
    now = time.time()
    full_key = _full_key(key, scope)

    try:
        cache = Redis.from_url(settings.queue_url, decode_responses=True)
        current = cache.incr(full_key)
        if current == 1:
            cache.expire(full_key, window_seconds)
        if current > max_requests:
            ttl = cache.ttl(full_key)
            return False, max(1, ttl)
        return True, 0
    except Exception:
        # Memory fallback
        pass

    timestamps = [t for t in _MEMORY_RATE_LIMITS[full_key] if now - t < window_seconds]
    _MEMORY_RATE_LIMITS[full_key] = timestamps
    if len(timestamps) >= max_requests:
        oldest = timestamps[0]
        retry_after = max(1, int(window_seconds - (now - oldest)))
        return False, retry_after

    timestamps.append(now)
    return True, 0


def rate_limit_retry_after(key: str, max_requests: int, window_seconds: int, scope: str = "default") -> int:
    """Return retry-after seconds if a key is currently limited without recording a hit."""
    settings = get_settings()
    now = time.time()
    full_key = _full_key(key, scope)

    try:
        cache = Redis.from_url(settings.queue_url, decode_responses=True)
        current = int(cache.get(full_key) or 0)
        if current >= max_requests:
            ttl = cache.ttl(full_key)
            return max(1, ttl)
        return 0
    except Exception:
        pass

    timestamps = [t for t in _MEMORY_RATE_LIMITS[full_key] if now - t < window_seconds]
    _MEMORY_RATE_LIMITS[full_key] = timestamps
    if len(timestamps) >= max_requests:
        return max(1, int(window_seconds - (now - timestamps[0])))
    return 0


def reset_rate_limit(key: str, scope: str = "default") -> None:
    """Clear one limiter key, used after successful authentication for that account."""
    settings = get_settings()
    full_key = _full_key(key, scope)
    try:
        Redis.from_url(settings.queue_url, decode_responses=True).delete(full_key)
    except Exception:
        pass
    _MEMORY_RATE_LIMITS.pop(full_key, None)


def rate_limit_dependency(
    max_requests: int,
    window_seconds: int,
    scope: str,
    key_func: Callable[[Request], str] = get_client_ip,
) -> Callable:
    """FastAPI dependency to enforce rate limits on routes."""

    async def _dependency(request: Request) -> None:
        key = key_func(request)
        allowed, retry_after = check_rate_limit(
            key=key,
            max_requests=max_requests,
            window_seconds=window_seconds,
            scope=scope,
        )
        if not allowed:
            logger.warning("Rate limit exceeded for %s in scope %s (retry in %ss)", key, scope, retry_after)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Please try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
