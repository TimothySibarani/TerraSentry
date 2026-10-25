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
    with pytest.raises(CacheNotReadyError, match="CACHE_SQLITE_PATH"):
        await check_cache(_DownCache(), "memory")


async def test_check_cache_accepts_memory_cache() -> None:
    await check_cache(MemoryCache(), "memory")


async def test_shared_engine_pragmas_integrity_and_persistence(tmp_path: Path) -> None:
    from sqlalchemy import delete
    from sqlalchemy.exc import IntegrityError
    from terrasentry_api.db import create_engine_and_session
    from terrasentry_api.models import Run, RunStep
    from terrasentry_core.tools.trace import utc_now

    url = _sqlite_url(tmp_path / "nested" / "audit.db")
    engine, sessions = create_engine_and_session(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar() == 1
                assert (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar() == 30000
                assert (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar() == "wal"
        async with sessions() as session:
            session.add(Run(id="invalid", kind="scenario", supplier_id="missing"))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
            session.add(Run(id="parent", kind="batch"))
            await session.flush()
            session.add(
                RunStep(run_id="parent", step_id="STEP-001", seq=1, kind="test", name="test", at=utc_now())
            )
            await session.commit()
    finally:
        await engine.dispose()
    engine, sessions = create_engine_and_session(url)
    try:
        async with sessions() as session:
            assert await session.get(Run, "parent") is not None
            await session.execute(delete(Run).where(Run.id == "parent"))
            await session.commit()
            assert await session.get(RunStep, 1) is None
    finally:
        await engine.dispose()


def test_settings_resolve_paths_without_opening_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import ValidationError
    from terrasentry_api.config import Settings

    monkeypatch.chdir(tmp_path)
    settings = Settings(database_url="sqlite+aiosqlite:///data/sqlite/audit.db")
    assert settings.database_url.startswith("sqlite+aiosqlite:////")
    assert not (tmp_path / "data").exists()
    assert Settings(database_url="sqlite+aiosqlite:///:memory:").database_url.endswith(":memory:")
    with pytest.raises(ValidationError, match="DATABASE_URL must be"):
        Settings(database_url="postgresql+asyncpg://localhost/old")


async def test_timestamps_normalize_offsets_on_reload(tmp_path: Path) -> None:
    from datetime import UTC, date, datetime, timedelta, timezone

    from sqlalchemy.exc import StatementError
    from terrasentry_api.db import create_engine_and_session
    from terrasentry_api.models import OperatorSetting, Run

    engine, sessions = create_engine_and_session(_sqlite_url(tmp_path / "audit.db"))
    instant = datetime(2026, 10, 25, 14, 30, tzinfo=timezone(timedelta(hours=7)))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(OperatorSetting(id=1, profile={}, updated_at=instant))
            session.add(
                Run(id="utc", kind="scenario", created_at=instant, assessment_date=date(2026, 10, 25))
            )
            await session.commit()
        async with sessions() as session:
            operator = await session.get(OperatorSetting, 1)
            run = await session.get(Run, "utc")
            assert operator is not None and run is not None
            assert operator.updated_at == instant.astimezone(UTC)
            assert operator.updated_at.tzinfo is UTC
            assert run.created_at == operator.updated_at
            assert run.started_at is None
            assert run.assessment_date == date(2026, 10, 25)
            operator.updated_at = instant.replace(tzinfo=None)
            with pytest.raises(StatementError, match="timezone"):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


def test_shared_engine_reports_invalid_parent(tmp_path: Path) -> None:
    from terrasentry_api.db import create_engine_and_session

    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(DatabaseNotReadyError, match="directory permissions"):
        create_engine_and_session(_sqlite_url(blocker / "audit.db"))
