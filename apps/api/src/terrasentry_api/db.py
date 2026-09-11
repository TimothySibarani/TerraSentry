"""Async engine and session factory.

The engine is created once per application process in the lifespan (see
``terrasentry_api.services``) rather than at import time, so tests can swap in a
different backend and ``app.openapi()`` never opens a connection.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_and_session(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Build the async engine and session factory for ``database_url``."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


__all__ = ["create_engine_and_session"]
