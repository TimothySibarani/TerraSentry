import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from terrasentry_integrations.cache import CacheEntry, MemoryCache, SQLiteCache
from terrasentry_integrations.errors import CacheMissError, IntegrationError
from terrasentry_integrations.fixtures import (
    export_fixtures,
    fixture_path,
    load_fixtures,
    prime_fixtures,
    write_fixture,
)


def _entry(source: str = "gfw") -> CacheEntry:
    return CacheEntry(
        source=source,
        geometry_hash="b" * 64,
        date_window="2021-01-01..2021-01-31",
        request={"method": "POST"},
        fetched_at=datetime(2026, 9, 11, tzinfo=UTC),
        payload={"rows": [{"loss_ha": 12.5}]},
    )


def test_fixture_path_is_deterministic_and_safe() -> None:
    entry = _entry("firms")
    path = fixture_path(Path("data/fixtures"), entry)
    assert path.name == "firms__bbbbbbbbbbbbbbbb__2021-01-01_2021-01-31.json"
    assert fixture_path(Path("data/fixtures"), entry) == path


async def test_export_then_prime_round_trips_through_files(tmp_path: Path) -> None:
    source = MemoryCache()
    await source.set(_entry("gfw"))
    await source.set(_entry("firms"))
    written = await export_fixtures(source, tmp_path / "fixtures")
    assert written == 2
    assert len(list((tmp_path / "fixtures").glob("*.json"))) == 2
    assert len(load_fixtures(tmp_path / "fixtures")) == 2

    offline = MemoryCache(offline=True)
    primed = await prime_fixtures(offline, tmp_path / "fixtures")
    assert primed == 2
    cached = await offline.get("gfw", "b" * 64, "2021-01-01..2021-01-31")
    assert cached is not None
    assert cached.payload == {"rows": [{"loss_ha": 12.5}]}

    with pytest.raises(CacheMissError):
        await offline.get("gfw", "c" * 64, "2021-01-01..2021-01-31")


async def test_sqlite_fixtures_survive_reopen_and_namespace_isolation(tmp_path: Path) -> None:
    cache = SQLiteCache(tmp_path / "cache.db", prefix="test:cache")
    await cache.set(_entry("gfw"))
    entries = await cache.iter_entries()
    assert [entry.source for entry in entries] == ["gfw"]
    written = await export_fixtures(cache, tmp_path / "fixtures")
    assert written == 1
    await cache.close()
    restored = SQLiteCache(tmp_path / "restored.db", prefix="test:cache", offline=True, ttl_seconds=60)
    assert await prime_fixtures(restored, tmp_path / "fixtures") == 1
    await restored.close()
    reopened = SQLiteCache(tmp_path / "restored.db", prefix="test:cache", offline=True)
    try:
        assert await reopened.get("gfw", "b" * 64, "2021-01-01..2021-01-31") == _entry()
    finally:
        await reopened.close()


def test_invalid_fixture_reports_the_file(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(IntegrationError, match=r"broken\.json"):
        load_fixtures(tmp_path)


def test_write_fixture_creates_the_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "fixtures"
    path = write_fixture(target, _entry())
    assert path.exists()
    assert path.parent == target


async def test_fixture_cli_exports_and_primes_separate_processes(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    destination_path = tmp_path / "destination.db"
    fixtures = tmp_path / "fixtures"
    cache = SQLiteCache(source_path)
    try:
        await cache.set(_entry())
    finally:
        await cache.close()
    for command, path in [("export", source_path), ("prime", destination_path)]:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "terrasentry_integrations.fixtures", command, "--dir", str(fixtures)],
            env={
                **os.environ,
                "CACHE_BACKEND": "sqlite",
                "CACHE_SQLITE_PATH": str(path),
                "CACHE_PREFIX": "ts:cache:v1",
                "CACHE_TTL_SECONDS": "60",
            },
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    restored = SQLiteCache(destination_path, offline=True)
    try:
        assert await restored.get("gfw", "b" * 64, "2021-01-01..2021-01-31") == _entry()
    finally:
        await restored.close()
