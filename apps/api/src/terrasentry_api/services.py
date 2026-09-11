"""Application services: one object graph per process, built in the lifespan.

Routers get an :class:`AsyncSession` through ``get_session``; background work
uses the same session factory through :class:`RunManager`. Tests construct
their own :class:`AppServices` and pass a factory to ``create_app``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_integrations.cache import CacheBackend, build_cache
from terrasentry_integrations.settings import IntegrationSettings, get_integration_settings
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

from terrasentry_api.config import Settings
from terrasentry_api.config import settings as default_settings
from terrasentry_api.db import create_engine_and_session
from terrasentry_api.mock_sap import MockSapStore
from terrasentry_api.runner import RunManager
from terrasentry_api.seed_loader import seed_if_empty
from terrasentry_api.store import RunStore


@dataclass
class AppServices:
    """Everything the API needs, owned by the application lifespan."""

    settings: Settings
    integration: IntegrationSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    cache: CacheBackend
    gfw: GfwClient
    firms: FirmsClient
    datasets: SeedDatasets
    run_manager: RunManager
    mock_sap: MockSapStore

    async def aclose(self) -> None:
        await self.run_manager.shutdown()
        await self.gfw.close()
        await self.firms.close()
        await self.cache.close()
        await self.engine.dispose()


ServicesFactory = Callable[[], AbstractAsyncContextManager[AppServices]]


@asynccontextmanager
async def build_services(settings: Settings = default_settings) -> AsyncIterator[AppServices]:
    """Build the real services: Postgres engine, Redis cache, live source clients."""
    integration = get_integration_settings()
    engine, session_factory = create_engine_and_session(settings.database_url)
    cache = build_cache(integration)
    gfw = GfwClient(integration, cache=cache)
    firms = FirmsClient(integration, cache=cache)
    try:
        datasets = SeedDatasets.load(
            batch_path=Path(settings.seed_data_dir) / "batch_50.json",
            operator_path=Path(settings.seed_data_dir) / "operator.json",
        )
        if settings.auto_seed:
            async with session_factory() as session:
                await seed_if_empty(RunStore(session), datasets)
        run_manager = RunManager(
            settings=settings,
            session_factory=session_factory,
            datasets=datasets,
            gfw=gfw,
            firms=firms,
        )
        services = AppServices(
            settings=settings,
            integration=integration,
            engine=engine,
            session_factory=session_factory,
            cache=cache,
            gfw=gfw,
            firms=firms,
            datasets=datasets,
            run_manager=run_manager,
            mock_sap=MockSapStore(record.supplier_id for record in datasets.records),
        )
    except BaseException:
        await gfw.close()
        await firms.close()
        await cache.close()
        await engine.dispose()
        raise
    try:
        yield services
    finally:
        await services.aclose()


def get_services(request: Request) -> AppServices:
    """The lifespan-installed services; tests may replace ``app.state.services``."""
    services: AppServices | None = getattr(request.app.state, "services", None)
    if services is None:
        raise RuntimeError("application services are not initialised")
    return services


async def get_session(
    services: Annotated[AppServices, Depends(get_services)],
) -> AsyncIterator[AsyncSession]:
    async with services.session_factory() as session:
        yield session


__all__ = [
    "AppServices",
    "ServicesFactory",
    "build_services",
    "get_services",
    "get_session",
]
