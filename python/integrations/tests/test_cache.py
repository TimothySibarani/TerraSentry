import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest
from terrasentry_integrations.cache import (
    CacheEntry,
    MemoryCache,
    SQLiteCache,
    _enable_wal,
    build_cache,
    geometry_hash,
)
from terrasentry_integrations.errors import CacheMissError, IntegrationError
from terrasentry_integrations.settings import IntegrationSettings


def test_geometry_identity_preserves_query_precision_and_versions_old_keys() -> None:
    import hashlib
    import json

    a = {"type": "Point", "coordinates": [101.0000001, 0.0]}
    b = {"coordinates": [101.0000001, 0.0], "type": "Point"}
    assert geometry_hash(a) == geometry_hash(b)
    assert geometry_hash(a) != geometry_hash({**a, "coordinates": [101.0000004, 0.0]})
    old = json.dumps({"coordinates": [101.0, 0.0], "type": "Point"}, separators=(",", ":"), sort_keys=True)
    assert geometry_hash(a) != hashlib.sha256(old.encode()).hexdigest()


def _entry(source: str = "gfw") -> CacheEntry:
    return CacheEntry(
        source=source,
        geometry_hash="a" * 64,
        date_window="2019-2024",
        request={"method": "POST"},
        fetched_at=datetime(2026, 9, 11, tzinfo=UTC),
        payload={"rows": [1, 2, 3]},
    )


async def test_memory_cache_roundtrip() -> None:
    cache = MemoryCache()
    entry = _entry()
    await cache.set(entry)
    cached = await cache.get(entry.source, entry.geometry_hash, entry.date_window)
    assert cached is not None
    assert cached.payload == {"rows": [1, 2, 3]}
    assert cache.stats().writes == 1
    assert cache.stats().hits == 1


async def test_memory_cache_offline_miss_raises() -> None:
    cache = MemoryCache(offline=True)
    with pytest.raises(CacheMissError):
        await cache.get("gfw", "missing", "2024")
    assert cache.stats().misses == 1
    assert cache.stats().offline_misses == 1


async def test_memory_cache_clear_source() -> None:
    cache = MemoryCache()
    await cache.set(_entry("gfw"))
    await cache.set(_entry("firms"))
    assert await cache.clear_source("gfw") == 1
    assert await cache.get("gfw", "a" * 64, "2019-2024") is None


async def test_sqlite_cache_survives_reopen_and_updates(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "cache.db"
    cache = SQLiteCache(path)
    entry = _entry()
    await cache.set(entry)
    await cache.set(entry.model_copy(update={"payload": "latitude,longitude\n1,2"}))
    assert cache.stats().writes == 2
    await cache.close()
    await cache.close()
    reopened = SQLiteCache(path, offline=True)
    try:
        cached = await reopened.get(entry.source, entry.geometry_hash, entry.date_window)
        assert cached is not None and cached.payload == "latitude,longitude\n1,2"
        assert reopened.stats().hits == 1
        assert not await reopened.delete("missing", entry.geometry_hash, entry.date_window)
        assert await reopened.delete(entry.source, entry.geometry_hash, entry.date_window)
        with pytest.raises(CacheMissError):
            await reopened.get(entry.source, entry.geometry_hash, entry.date_window)
        assert reopened.stats().misses == reopened.stats().offline_misses == 1
    finally:
        await reopened.close()


@pytest.mark.parametrize("ttl", [0, -1, 60])
async def test_sqlite_ttl_and_offline_expiration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ttl: int
) -> None:
    now = 1000.0
    monkeypatch.setattr("terrasentry_integrations.cache.time.time", lambda: now)
    cache = SQLiteCache(tmp_path / "cache.db", ttl_seconds=ttl, offline=True)
    entry = _entry()
    try:
        await cache.set(entry)
        now = 1059
        assert await cache.get(entry.source, entry.geometry_hash, entry.date_window) == entry
        now = 1060
        if ttl > 0:
            assert not await cache.delete(entry.source, entry.geometry_hash, entry.date_window)
            assert await cache.clear_source(entry.source) == 0
            with pytest.raises(CacheMissError):
                await cache.get(entry.source, entry.geometry_hash, entry.date_window)
            assert cache.stats().misses == cache.stats().offline_misses == 1
            assert await cache.iter_entries() == []
        else:
            assert await cache.get(entry.source, entry.geometry_hash, entry.date_window) == entry
    finally:
        await cache.close()


async def test_sqlite_concurrent_use_and_namespace_isolation(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    first = SQLiteCache(path, prefix="one")
    second = SQLiteCache(path, prefix="two")
    try:
        await asyncio.gather(*(first.set(_entry()) for _ in range(20)), second.set(_entry()))
        await first.set(_entry("firms"))
        assert [entry.source for entry in await first.iter_entries()] == ["firms", "gfw"]
        assert await first.clear_source("gfw") == 1
        assert await first.clear_source("gfw") == 0
        assert [entry.source for entry in await first.iter_entries()] == ["firms"]
        assert await second.iter_entries() == [_entry()]
        # Separate instances in the same namespace update the same row atomically.
        third = SQLiteCache(path, prefix="two")
        try:
            await asyncio.gather(second.set(_entry("firms")), third.set(_entry("firms")))
            assert len(await third.iter_entries()) == 2
        finally:
            await third.close()
    finally:
        await first.close()
        await second.close()


async def test_sqlite_failed_write_rolls_back_and_corruption_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    cache = SQLiteCache(path)
    try:
        await cache.ping()
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TRIGGER reject_cache BEFORE INSERT ON cache_entries "
                "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        with pytest.raises(IntegrationError, match="permissions"):
            await cache.set(_entry())
        assert cache.stats().writes == 0
        assert await cache.iter_entries() == []
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TRIGGER reject_cache")
        await cache.set(_entry())
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE cache_entries SET entry='broken json'")
        with pytest.raises(IntegrationError, match="corrupt"):
            await cache.get("gfw", "a" * 64, "2019-2024")
        with pytest.raises(IntegrationError, match="corrupt"):
            await cache.iter_entries()
    finally:
        await cache.close()


async def test_sqlite_initialization_failure_and_close(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    cache = SQLiteCache(blocker / "cache.db")
    with pytest.raises(IntegrationError, match="permissions"):
        await cache.ping()
    await cache.close()
    await cache.close()
    with pytest.raises(IntegrationError, match="closed"):
        await cache.ping()


async def test_cache_factory_and_path_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = IntegrationSettings(cache_backend="sqlite")
    assert settings.cache_sqlite_path.is_absolute()
    assert settings.cache_sqlite_path.name == "cache.db"
    assert not (tmp_path / "data").exists()
    cache = build_cache(settings.model_copy(update={"cache_sqlite_path": tmp_path / "cache.db"}))
    assert isinstance(cache, SQLiteCache)
    await cache.close()
    assert not (tmp_path / "cache.db").exists()


async def test_wal_initialization_retries_only_sqlite_busy(tmp_path: Path) -> None:
    connection = await aiosqlite.connect(tmp_path / "wal.db")
    busy = sqlite3.OperationalError("database is locked")
    busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
    io_error = sqlite3.OperationalError("disk I/O error")
    io_error.sqlite_errorcode = sqlite3.SQLITE_IOERR
    try:
        with patch.object(connection, "execute") as execute:
            execute.side_effect = [busy, busy, MagicMock()]
            await _enable_wal(connection)
            assert execute.call_count == 3
        with patch.object(connection, "execute") as execute:
            execute.side_effect = io_error
            with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
                await _enable_wal(connection)
            assert execute.call_count == 1
    finally:
        await connection.close()


async def test_many_cache_instances_can_initialize_the_same_new_file(tmp_path: Path) -> None:
    for index in range(12):
        caches = [SQLiteCache(tmp_path / f"race-{index}.db", prefix=str(i)) for i in range(4)]
        try:
            await asyncio.gather(*(cache.set(_entry()) for cache in caches))
            assert await asyncio.gather(*(cache.iter_entries() for cache in caches)) == [[_entry()]] * 4
        finally:
            await asyncio.gather(*(cache.close() for cache in caches))
