"""Persistent cache for external source responses.

Cache keys are ``(source, geometry_hash, date_window)`` and every entry stores the
original request description plus a local snapshot of the raw payload, so a cached
re-run makes zero external calls and stays auditable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import aiosqlite
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, retry_if_exception, stop_after_delay, wait_fixed

from terrasentry_integrations.errors import CacheMissError, IntegrationError
from terrasentry_integrations.settings import IntegrationSettings


def geometry_hash(geometry: dict[str, Any]) -> str:
    """Versioned identity of the exact query geometry; never round derived buffers."""
    canonical = json.dumps(geometry, separators=(",", ":"), sort_keys=True, allow_nan=False)
    return hashlib.sha256(f"geometry-v2:{canonical}".encode()).hexdigest()


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
    """Storage contract shared by the SQLite and in-memory implementations."""

    offline: bool

    async def get(self, source: str, geometry_hash: str, date_window: str) -> CacheEntry | None: ...

    async def set(self, entry: CacheEntry) -> None: ...

    async def delete(self, source: str, geometry_hash: str, date_window: str) -> bool: ...

    async def clear_source(self, source: str) -> int: ...

    async def iter_entries(self) -> list[CacheEntry]: ...

    def stats(self) -> CacheStats: ...

    async def ping(self) -> None: ...

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

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        self._entries.clear()


# Switching a new file to WAL can return SQLITE_BUSY without invoking SQLite's busy timeout.
@retry(
    retry=retry_if_exception(
        lambda exc: (
            isinstance(exc, sqlite3.OperationalError)
            and getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY
        )
    ),
    wait=wait_fixed(0.05),
    stop=stop_after_delay(30),
    reraise=True,
)
async def _enable_wal(connection: aiosqlite.Connection) -> None:
    async with connection.execute("PRAGMA journal_mode=WAL"):
        pass


class SQLiteCache(BaseCache):
    """Persistent response snapshots in a disposable SQLite file."""

    def __init__(
        self,
        path: Path,
        *,
        prefix: str = "ts:cache:v1",
        ttl_seconds: int = 0,
        offline: bool = False,
    ) -> None:
        super().__init__(offline=offline, ttl_seconds=ttl_seconds)
        self._path = path
        self._prefix = prefix
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._lock:
            if self._closed:
                raise IntegrationError("SQLite cache is closed")
            try:
                if self._connection is None:
                    await asyncio.to_thread(self._path.parent.mkdir, parents=True, exist_ok=True)
                    connection = await aiosqlite.connect(self._path, timeout=30)
                    try:
                        await _enable_wal(connection)
                        async with connection.execute(
                            "CREATE TABLE IF NOT EXISTS cache_entries ("
                            "namespace TEXT NOT NULL, source TEXT NOT NULL, geometry_hash TEXT NOT NULL, "
                            "date_window TEXT NOT NULL, entry TEXT NOT NULL, expires_at REAL, "
                            "PRIMARY KEY (namespace, source, geometry_hash, date_window))"
                        ):
                            pass
                        await connection.commit()
                    except BaseException:
                        await connection.close()
                        raise
                    self._connection = connection
                yield self._connection
                await self._connection.commit()
            except BaseException as exc:
                if self._connection is not None:
                    await self._connection.rollback()
                if isinstance(exc, (OSError, sqlite3.Error)):
                    raise IntegrationError(
                        f"SQLite cache at {self._path} operation failed; "
                        "check directory permissions and database integrity"
                    ) from exc
                raise

    @staticmethod
    def _decode(raw: str) -> CacheEntry:
        try:
            return CacheEntry.model_validate_json(raw)
        except ValidationError as exc:
            raise IntegrationError(f"corrupt SQLite cache entry: {exc}") from exc

    async def get(self, source: str, geometry_hash: str, date_window: str) -> CacheEntry | None:
        key = (self._prefix, source, geometry_hash, date_window)
        async with self._transaction() as connection:
            await connection.execute(
                "DELETE FROM cache_entries WHERE namespace=? AND source=? AND geometry_hash=? "
                "AND date_window=? AND expires_at<=?",
                (*key, time.time()),
            )
            async with connection.execute(
                "SELECT entry FROM cache_entries WHERE namespace=? AND source=? "
                "AND geometry_hash=? AND date_window=?",
                key,
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            self._record_miss(source, geometry_hash, date_window)
            return None
        return self._record_hit(self._decode(row[0]))

    async def set(self, entry: CacheEntry) -> None:
        async with self._transaction() as connection:
            expires_at = time.time() + self.ttl_seconds if self.ttl_seconds > 0 else None
            await connection.execute(
                "INSERT INTO cache_entries VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (namespace, source, geometry_hash, date_window) "
                "DO UPDATE SET entry=excluded.entry, expires_at=excluded.expires_at",
                (
                    self._prefix,
                    entry.source,
                    entry.geometry_hash,
                    entry.date_window,
                    entry.model_dump_json(),
                    expires_at,
                ),
            )
        self._stats.writes += 1

    async def delete(self, source: str, geometry_hash: str, date_window: str) -> bool:
        async with (
            self._transaction() as connection,
            connection.execute(
                "DELETE FROM cache_entries WHERE namespace=? AND source=? AND geometry_hash=? "
                "AND date_window=? AND (expires_at IS NULL OR expires_at>?)",
                (self._prefix, source, geometry_hash, date_window, time.time()),
            ) as cursor,
        ):
            return cursor.rowcount > 0

    async def clear_source(self, source: str) -> int:
        async with (
            self._transaction() as connection,
            connection.execute(
                "DELETE FROM cache_entries WHERE namespace=? AND source=? "
                "AND (expires_at IS NULL OR expires_at>?)",
                (self._prefix, source, time.time()),
            ) as cursor,
        ):
            return cursor.rowcount

    async def iter_entries(self) -> list[CacheEntry]:
        async with self._transaction() as connection:
            await connection.execute(
                "DELETE FROM cache_entries WHERE namespace=? AND expires_at<=?",
                (self._prefix, time.time()),
            )
            async with connection.execute(
                "SELECT entry FROM cache_entries WHERE namespace=? "
                "ORDER BY source, geometry_hash, date_window",
                (self._prefix,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._decode(row[0]) for row in rows]

    async def ping(self) -> None:
        async with self._transaction() as connection, connection.execute("SELECT 1"):
            pass

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                await self._connection.close()
                self._connection = None
            self._closed = True


def build_cache(settings: IntegrationSettings, *, offline: bool = False) -> CacheBackend:
    """SQLite by default; memory for isolated tests and ephemeral runs."""
    if settings.cache_backend == "memory":
        return MemoryCache(offline=offline, ttl_seconds=settings.cache_ttl_seconds)
    return SQLiteCache(
        settings.cache_sqlite_path,
        prefix=settings.cache_prefix,
        ttl_seconds=settings.cache_ttl_seconds,
        offline=offline,
    )
