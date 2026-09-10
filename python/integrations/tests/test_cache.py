from datetime import UTC, datetime

import fakeredis.aioredis
import pytest
from terrasentry_integrations.cache import CacheEntry, MemoryCache, RedisCache
from terrasentry_integrations.errors import CacheMissError


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


async def test_redis_cache_roundtrip_with_fakeredis() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache = RedisCache(redis, prefix="test:cache", ttl_seconds=60)
    entry = _entry()
    await cache.set(entry)
    cached = await cache.get(entry.source, entry.geometry_hash, entry.date_window)
    assert cached is not None
    assert cached.payload == {"rows": [1, 2, 3]}
    assert cache.stats().writes == 1
    await cache.close()


async def test_redis_cache_offline_miss_raises() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache = RedisCache(redis, prefix="test:cache", offline=True)
    with pytest.raises(CacheMissError):
        await cache.get("firms", "missing", "2026-01-01..2026-01-07")
    await cache.close()
