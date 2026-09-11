"""Async engine, session factory, and the startup preflight.

The engine is created once per application process in the lifespan (see
``terrasentry_api.services``) rather than at import time, so tests can swap in a
different backend and ``app.openapi()`` never opens a connection.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from terrasentry_api.models import Supplier


class DatabaseNotReadyError(RuntimeError):
    """The audit store is unreachable or unmigrated; the message carries remediation."""


async def check_database(engine: AsyncEngine, database_url: str) -> None:
    """Fail fast with operator guidance when the audit store is unusable.

    Separates "cannot connect" from "connected but schema missing" so the
    operator knows whether to start infrastructure or run the migrations.
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
            f"the audit database at {target} is unreachable. Start local infrastructure"
            " with `pnpm db:up` (Postgres + Redis) or point DATABASE_URL in .env at a"
            " running Postgres, then run `pnpm db:upgrade`."
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
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


__all__ = ["DatabaseNotReadyError", "check_database", "create_engine_and_session"]
