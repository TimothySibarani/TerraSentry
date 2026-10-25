"""Async engine, session factory, and the startup preflight.

The engine is created once per application process in the lifespan (see
``terrasentry_api.services``) rather than at import time, so tests can swap in a
different backend and ``app.openapi()`` never opens a connection.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry
from terrasentry_integrations.cache import CacheBackend

from terrasentry_api.models import Supplier


class DatabaseNotReadyError(RuntimeError):
    """The audit store is unreachable or unmigrated; the message carries remediation."""


class CacheNotReadyError(RuntimeError):
    """The source cache is unreachable; the message carries remediation."""


async def check_cache(cache: CacheBackend, target: str) -> None:
    """Fail fast with operator guidance when the configured cache is down."""
    try:
        await cache.ping()
    except Exception as exc:
        raise CacheNotReadyError(
            f"the source cache at {target} is unreachable. Check CACHE_SQLITE_PATH and directory"
            " permissions, or set CACHE_BACKEND=memory in .env."
        ) from exc


async def check_database(engine: AsyncEngine, database_url: str) -> None:
    """Fail fast with operator guidance when the audit store is unusable.

    Separates "cannot connect" from "connected but schema missing" so the
    operator knows whether to fix the storage path or run the migrations.
    """
    target = make_url(database_url).render_as_string(hide_password=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            has_schema = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).has_table(Supplier.__tablename__)
            )
    except (OSError, SQLAlchemyError) as exc:
        raise DatabaseNotReadyError(
            f"the audit database at {target} is unreachable. Check DATABASE_URL and directory"
            " permissions, then run `pnpm db:upgrade`."
        ) from exc
    if not has_schema:
        raise DatabaseNotReadyError(
            f"the audit database at {target} has no schema. Run `pnpm db:upgrade`"
            " (Alembic) before starting the API."
        )


def create_engine_and_session(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Build the async engine and session factory for ``database_url``."""
    url = make_url(database_url)
    if url.database and url.database != ":memory:":
        try:
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DatabaseNotReadyError(
                "cannot create audit database directory; check DATABASE_URL and directory permissions"
            ) from exc
    engine = create_async_engine(database_url, connect_args={"timeout": 30}, pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "connect")
    def configure_connection(connection: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine, async_sessionmaker(engine, expire_on_commit=False)


__all__ = [
    "CacheNotReadyError",
    "DatabaseNotReadyError",
    "check_cache",
    "check_database",
    "create_engine_and_session",
]
