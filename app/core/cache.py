"""Redis-compatible asynchronous cache abstraction.

The application talks to a single :class:`CacheBackend` interface. Two concrete
implementations are provided:

* :class:`RedisCache` — used whenever ``REDIS_URL`` is configured. Suitable for
  sharing cache state across Vercel serverless instances.
* :class:`InMemoryCache` — a TTL-aware, process-local fallback used for local
  development and as a graceful degradation path when Redis is unreachable.

Values are serialised with ``orjson`` for speed and cross-language compatibility.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

import orjson

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger("cache")


class CacheBackend(ABC):
    """Abstract async cache contract (Redis-compatible semantics)."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Return the decoded value for ``key`` or ``None`` if absent/expired."""

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store ``value`` under ``key`` with a positive ``ttl_seconds`` expiry."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove ``key`` if present."""

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying resources."""

    @staticmethod
    def _encode(value: Any) -> bytes:
        return orjson.dumps(value)

    @staticmethod
    def _decode(raw: bytes | str | None) -> Any | None:
        if raw is None:
            return None
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return orjson.loads(raw)


class InMemoryCache(CacheBackend):
    """Thread-/coroutine-safe in-process cache with per-key TTL."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, bytes]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, raw = entry
            if expires_at <= time.monotonic():
                self._store.pop(key, None)
                return None
            return self._decode(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        ttl = max(1, int(ttl_seconds))
        async with self._lock:
            self._store[key] = (time.monotonic() + ttl, self._encode(value))

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def close(self) -> None:  # noqa: D102 - nothing to release
        async with self._lock:
            self._store.clear()


class RedisCache(CacheBackend):
    """Cache backed by a Redis-compatible server via ``redis.asyncio``.

    Any connectivity failure degrades gracefully (logged, treated as a cache
    miss) so that a Redis outage never takes down the API.
    """

    def __init__(self, url: str) -> None:
        # Imported lazily so the dependency is only required when configured.
        from redis.asyncio import Redis  # type: ignore import-not-found

        self._redis: Redis = Redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=False,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            health_check_interval=30,
        )

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(key)
            return self._decode(raw)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("redis_get_failed", extra={"error": str(exc)})
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            await self._redis.set(key, self._encode(value), ex=max(1, int(ttl_seconds)))
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("redis_set_failed", extra={"error": str(exc)})

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("redis_delete_failed", extra={"error": str(exc)})

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except Exception:  # pragma: no cover - best effort
            pass


def build_cache(settings: Settings) -> CacheBackend:
    """Construct the appropriate cache backend for the current configuration."""
    if settings.redis_url:
        logger.info("cache_backend_selected", extra={"backend": "redis"})
        return RedisCache(settings.redis_url)
    logger.info("cache_backend_selected", extra={"backend": "in_memory"})
    return InMemoryCache()
