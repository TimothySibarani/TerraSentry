"""Startup preflight: unreachable, unmigrated, and migrated store paths."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from terrasentry_api.db import CacheNotReadyError, DatabaseNotReadyError, check_cache, check_database
from terrasentry_api.models import Base
from terrasentry_integrations.cache import MemoryCache


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


async def test_check_database_rejects_unreachable_store(tmp_path: Path) -> None:
    url = _sqlite_url(tmp_path / "missing" / "terrasentry.db")
    engine = create_async_engine(url)
    try:
        with pytest.raises(DatabaseNotReadyError, match="unreachable"):
            await check_database(engine, url)
    finally:
        await engine.dispose()


async def test_check_database_requires_migrations(tmp_path: Path) -> None:
    url = _sqlite_url(tmp_path / "empty.db")
    engine = create_async_engine(url)
    try:
        with pytest.raises(DatabaseNotReadyError, match="db:upgrade"):
            await check_database(engine, url)
    finally:
        await engine.dispose()


async def test_check_database_accepts_migrated_store(tmp_path: Path) -> None:
    url = _sqlite_url(tmp_path / "migrated.db")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await check_database(engine, url)
    finally:
        await engine.dispose()


class _DownCache(MemoryCache):
    async def ping(self) -> None:
        raise ConnectionError("refused")


async def test_check_cache_rejects_unreachable_cache() -> None:
    with pytest.raises(CacheNotReadyError, match="db:up"):
        await check_cache(_DownCache(), "redis://localhost:6379/0")


async def test_check_cache_accepts_memory_cache() -> None:
    await check_cache(MemoryCache(), "redis://localhost:6379/0")
