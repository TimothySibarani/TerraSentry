"""Application services: one object graph per process, built in the lifespan.

Routers get an :class:`AsyncSession` through ``get_session``; background work
uses the same session factory through :class:`RunManager`. Tests construct
their own :class:`AppServices` and pass a factory to ``create_app``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_integrations.cache import CacheBackend, build_cache
from terrasentry_integrations.fixtures import prime_fixtures
from terrasentry_integrations.sap import (
    SapGateway,
    StubSapService,
    build_sap_gateway,
    resolve_sap_mode,
    sap_mode_is_real,
)
from terrasentry_integrations.settings import IntegrationSettings, get_integration_settings
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

from terrasentry_api.config import Settings
from terrasentry_api.config import settings as default_settings
from terrasentry_api.db import check_database, create_engine_and_session
from terrasentry_api.runner import RunManager
from terrasentry_api.sap_actions import SapActionService
from terrasentry_api.seed_loader import seed_if_empty
from terrasentry_api.store import RunStore

logger = logging.getLogger(__name__)


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
    sap: SapGateway
    sap_stub: StubSapService
    sap_actions: SapActionService
    sap_mode: str
    sap_real: bool
    offline: bool = False
    fixtures_loaded: int = 0

    async def aclose(self) -> None:
        await self.run_manager.shutdown()
        await self.sap.close()
        await self.gfw.close()
        await self.firms.close()
        await self.cache.close()
        await self.engine.dispose()


ServicesFactory = Callable[[], AbstractAsyncContextManager[AppServices]]


@asynccontextmanager
async def build_services(
    settings: Settings = default_settings,
    integration: IntegrationSettings | None = None,
) -> AsyncIterator[AppServices]:
    """Build the real services: Postgres engine, Redis cache, live source clients.

    ``integration`` is an optional override so the rehearsal CLI can force an
    offline cache/fixture directory without mutating process env.
    """
    resolved = integration or get_integration_settings()
    engine, session_factory = create_engine_and_session(settings.database_url)
    cache = build_cache(resolved, offline=resolved.cache_offline)
    gfw = GfwClient(resolved, cache=cache)
    firms = FirmsClient(resolved, cache=cache)
    sap: SapGateway | None = None
    try:
        await check_database(engine, settings.database_url)
        fixtures_loaded = 0
        if resolved.cache_fixtures_dir:
            fixtures_loaded = await prime_fixtures(cache, Path(resolved.cache_fixtures_dir))
        datasets = SeedDatasets.load(
            batch_path=Path(settings.seed_data_dir) / "batch_50.json",
            operator_path=Path(settings.seed_data_dir) / "operator.json",
        )
        if settings.auto_seed:
            async with session_factory() as session:
                await seed_if_empty(RunStore(session), datasets)
        # Replay the persisted ERP action log into the stub so a status flip
        # survives an API restart, then select the configured SAP transport.
        sap_stub = StubSapService(record.supplier_id for record in datasets.records)
        async with session_factory() as session:
            sap_stub.restore(await RunStore(session).latest_vendor_states())
        sap_mode = resolve_sap_mode(resolved)
        sap_real = sap_mode_is_real(sap_mode)
        if sap_real and not resolved.has_sap_credentials:
            logger.warning(
                "SAP_MODE=%s is selected but its credentials are incomplete; "
                "ERP actions will be recorded as failed until they are configured",
                sap_mode,
            )
        sap = build_sap_gateway(resolved, stub=sap_stub)
        sap_actions = SapActionService(gateway=sap, mode=sap_mode)
        run_manager = RunManager(
            settings=settings,
            session_factory=session_factory,
            datasets=datasets,
            gfw=gfw,
            firms=firms,
            cache=cache,
            sap=sap_actions,
        )
        services = AppServices(
            settings=settings,
            integration=resolved,
            engine=engine,
            session_factory=session_factory,
            cache=cache,
            gfw=gfw,
            firms=firms,
            datasets=datasets,
            run_manager=run_manager,
            sap=sap,
            sap_stub=sap_stub,
            sap_actions=sap_actions,
            sap_mode=sap_mode,
            sap_real=sap_real,
            offline=resolved.cache_offline,
            fixtures_loaded=fixtures_loaded,
        )
    except BaseException:
        if sap is not None:
            await sap.close()
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
