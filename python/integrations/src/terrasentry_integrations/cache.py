"""Persistent cache for external source responses.

Cache keys are ``(source, geometry_hash, date_window)`` and every entry stores the
original request description plus a local snapshot of the raw payload, so a cached
re-run makes zero external calls and stays auditable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError
from redis.asyncio import Redis

from terrasentry_integrations.errors import CacheMissError, IntegrationError
from terrasentry_integrations.settings import IntegrationSettings


def _canonicalize(value: Any, decimals: int = 6) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize(value[key], decimals) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item, decimals) for item in value]
    if isinstance(value, float):
        return round(value, decimals)
    return value


def geometry_hash(geometry: dict[str, Any]) -> str:
    """Stable SHA-256 over a canonicalized GeoJSON geometry or feature collection."""
    canonical = json.dumps(_canonicalize(geometry), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CacheEntry(BaseModel):
    """One cached source response."""

    schema_version: int = 1
    source: str
    geometry_hash: str
    date_window: str
    request: dict[str, Any] = Field(default_factory=dict)
    status_code: int = 200
    fetched_at: datetime
    payload_format: str = "json"
    payload: Any


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    offline_misses: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "offline_misses": self.offline_misses,
        }


class CacheBackend(Protocol):
    """Storage contract shared by the Redis and in-memory implementations."""

    offline: bool

    async def get(self, source: str, geometry_hash: str, date_window: str) -> CacheEntry | None: ...

    async def set(self, entry: CacheEntry) -> None: ...

    async def delete(self, source: str, geometry_hash: str, date_window: str) -> bool: ...

    async def clear_source(self, source: str) -> int: ...

    async def iter_entries(self) -> list[CacheEntry]: ...

    def stats(self) -> CacheStats: ...

    async def close(self) -> None: ...


class BaseCache:
    """Offline handling and stats shared by cache backends."""

    def __init__(self, *, offline: bool = False, ttl_seconds: int = 0) -> None:
        self.offline = offline
        self.ttl_seconds = ttl_seconds
        self._stats = CacheStats()

    def stats(self) -> CacheStats:
        return self._stats

    def _record_hit(self, entry: CacheEntry) -> CacheEntry:
        self._stats.hits += 1
        return entry

    def _record_miss(self, source: str, geometry_hash: str, date_window: str) -> None:
        self._stats.misses += 1
        if self.offline:
            self._stats.offline_misses += 1
            raise CacheMissError(source, geometry_hash, date_window)

    @staticmethod
    def _key_parts(source: str, geometry_hash: str, date_window: str) -> str:
        return f"{source}:{geometry_hash}:{date_window}"


class MemoryCache(BaseCache):
    """In-process cache for tests and ephemeral dev runs."""

    def __init__(self, *, offline: bool = False, ttl_seconds: int = 0) -> None:
        super().__init__(offline=offline, ttl_seconds=ttl_seconds)
        self._entries: dict[str, CacheEntry] = {}

    async def get(self, source: str, geometry_hash: str, date_window: str) -> CacheEntry | None:
        entry = self._entries.get(self._key_parts(source, geometry_hash, date_window))
        if entry is None:
            self._record_miss(source, geometry_hash, date_window)
            return None
        return self._record_hit(entry)

    async def set(self, entry: CacheEntry) -> None:
        self._entries[self._key_parts(entry.source, entry.geometry_hash, entry.date_window)] = entry
        self._stats.writes += 1

    async def delete(self, source: str, geometry_hash: str, date_window: str) -> bool:
        return self._entries.pop(self._key_parts(source, geometry_hash, date_window), None) is not None

    async def clear_source(self, source: str) -> int:
        keys = [key for key in self._entries if key.startswith(f"{source}:")]
        for key in keys:
            del self._entries[key]
        return len(keys)

    async def iter_entries(self) -> list[CacheEntry]:
        return list(self._entries.values())

    async def close(self) -> None:
        self._entries.clear()


class RedisCache(BaseCache):
    """Redis-backed cache with an optional TTL."""

    def __init__(
        self,
        redis: Redis,
        *,
        prefix: str = "ts:cache:v1",
        ttl_seconds: int = 0,
        offline: bool = False,
    ) -> None:
        super().__init__(offline=offline, ttl_seconds=ttl_seconds)
        self._redis = redis
        self._prefix = prefix

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        prefix: str = "ts:cache:v1",
        ttl_seconds: int = 0,
        offline: bool = False,
    ) -> RedisCache:
        return cls(
            Redis.from_url(url, decode_responses=True),
            prefix=prefix,
            ttl_seconds=ttl_seconds,
            offline=offline,
        )

    def _key(self, source: str, geometry_hash: str, date_window: str) -> str:
        return f"{self._prefix}:{self._key_parts(source, geometry_hash, date_window)}"

    async def get(self, source: str, geometry_hash: str, date_window: str) -> CacheEntry | None:
        raw = await self._redis.get(self._key(source, geometry_hash, date_window))
        if raw is None:
            self._record_miss(source, geometry_hash, date_window)
            return None
        try:
            entry = CacheEntry.model_validate_json(raw)
        except ValidationError as exc:
            raise IntegrationError(f"corrupt cache entry for {source} window={date_window}: {exc}") from exc
        return self._record_hit(entry)

    async def set(self, entry: CacheEntry) -> None:
        key = self._key(entry.source, entry.geometry_hash, entry.date_window)
        raw = entry.model_dump_json()
        if self.ttl_seconds > 0:
            await self._redis.set(key, raw, ex=self.ttl_seconds)
        else:
            await self._redis.set(key, raw)
        self._stats.writes += 1

    async def delete(self, source: str, geometry_hash: str, date_window: str) -> bool:
        removed = await self._redis.delete(self._key(source, geometry_hash, date_window))
        return bool(removed)

    async def clear_source(self, source: str) -> int:
        removed = 0
        async for key in self._redis.scan_iter(match=f"{self._prefix}:{source}:*"):
            await self._redis.delete(key)
            removed += 1
        return removed

    async def iter_entries(self) -> list[CacheEntry]:
        entries: list[CacheEntry] = []
        async for key in self._redis.scan_iter(match=f"{self._prefix}:*"):
            raw = await self._redis.get(key)
            if raw is None:
                continue
            try:
                entries.append(CacheEntry.model_validate_json(raw))
            except ValidationError as exc:
                raise IntegrationError(f"corrupt cache entry at {key!r}: {exc}") from exc
        entries.sort(key=lambda entry: (entry.source, entry.geometry_hash, entry.date_window))
        return entries

    async def close(self) -> None:
        await self._redis.aclose()


def build_cache(settings: IntegrationSettings, *, offline: bool = False) -> CacheBackend:
    """Build the configured cache backend (Redis by default, memory for dev/tests)."""
    if settings.cache_backend == "memory":
        return MemoryCache(offline=offline, ttl_seconds=settings.cache_ttl_seconds)
    return RedisCache.from_url(
        settings.redis_url,
        prefix=settings.cache_prefix,
        ttl_seconds=settings.cache_ttl_seconds,
        offline=offline,
    )
