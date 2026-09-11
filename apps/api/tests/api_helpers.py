"""Shared builders for the M4 API tests.

Mirrors ``python/core/tests/agent_helpers.py``: no credentials, no network, and
a hand-built four-record seed whose deterministic outcomes cover compliant,
high-risk, and ambiguous verdicts.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from terrasentry_api.config import Settings
from terrasentry_api.db import create_engine_and_session
from terrasentry_api.mock_sap import MockSapStore
from terrasentry_api.models import Base
from terrasentry_api.runner import RunManager
from terrasentry_api.seed_loader import seed_if_empty
from terrasentry_api.services import AppServices, ServicesFactory
from terrasentry_api.store import RunStore
from terrasentry_core.domain.models import PermitStatus
from terrasentry_core.seed.schemas import (
    AmbiguityReason,
    Archetype,
    BatchDataset,
    BatchRecord,
    ConsignmentRecord,
    ExpectedSignal,
    LegalityRecord,
    OperatorRecord,
    Scenario,
    SeedPolygon,
)
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_integrations.cache import CacheBackend, MemoryCache
from terrasentry_integrations.settings import IntegrationSettings
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

GFW_URL = "https://data-api.globalforestwatch.org/dataset/umd_tree_cover_loss/v1.13/query/json"
FIRMS_REGEX = r"https://firms\.modaps\.eosdis\.nasa\.gov/api/area/csv/TESTKEY/VIIRS_SNPP_NRT/.*"
REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = REPO_ROOT / "data" / "seed"
POLYGON_GEOMETRY: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[101.0, 0.0], [101.02, 0.0], [101.02, 0.02], [101.0, 0.02], [101.0, 0.0]]],
}


def make_operator() -> OperatorRecord:
    return OperatorRecord(
        operator_id="OP-SYNTH-TEST",
        legal_name="SYNTH EU Imports B.V.",
        identifier_type="eori",
        identifier_value="NL998877665544332",
        address_line="SYNTH-Port 1",
        postal_code="3011 XX",
        city="Rotterdam",
        country="NL",
        email="ops@synth.terrasentry.example",
        phone="+31 10 000 0000",
        activity_type="IMPORT",
        country_of_activity="NL",
        border_cross_country="NL",
        synthetic=True,
        disclosure="SYNTHETIC TEST DATA — API fixture",
    )


def make_record(
    index: int,
    *,
    archetype: Archetype = "compliant",
    scenario: Scenario | None = None,
    permit_status: PermitStatus = "active",
    hgu: bool = True,
    sanctions: list[str] | None = None,
    expected_signal: ExpectedSignal | None = None,
    expected_ambiguity: AmbiguityReason | None = None,
) -> BatchRecord:
    supplier_id = f"SUP-{index:03d}"
    polygon = SeedPolygon(
        id=f"POLY-{index:03d}",
        label=f"Test parcel {index}",
        region="Riau peat forests",
        province="Riau",
        archetype=archetype,
        scenario=scenario,
        is_demo=index <= 2,
        area_ha=500.0,
        centroid_lat=0.01,
        centroid_lon=101.01,
        geometry=POLYGON_GEOMETRY,
    )
    legality = LegalityRecord(
        supplier_id=supplier_id,
        legal_name=f"PT Test {index}",
        trading_name=f"Test {index} (SYNTH)",
        group="Test Group",
        nib="1234567890123",
        npwp="12.345.678.9-012.345",
        hgu_number="HGU No. 42/HGU/BPN/2019" if hgu else None,
        pbp_number=None,
        permit_status=permit_status,
        concession_area_ha=9000.0,
        province="Riau",
        kabupaten="Siak",
        beneficial_owners=["Test Owner"],
        certifications=["ISPO"],
        sanctions=list(sanctions or []),
        synthetic=True,
        disclosure="SYNTHETIC TEST DATA — API fixture",
    )
    consignment = ConsignmentRecord(
        supplier_id=supplier_id,
        commodity="oil_palm",
        description="Crude palm oil (synthetic)",
        hs_heading="1511",
        species_scientific="Elaeis guineensis",
        species_common="Kelapa sawit",
        net_weight_kg=4_500_000.0,
        production_place="Block 01",
        harvest_year=2025,
        synthetic=True,
        disclosure="SYNTHETIC TEST DATA — API fixture",
    )
    return BatchRecord(
        record_id=f"REC-{index:03d}",
        supplier_id=supplier_id,
        polygon=polygon,
        legality=legality,
        consignment=consignment,
        expected_archetype=archetype,
        expected_signal=expected_signal,
        expected_ambiguity=expected_ambiguity,
    )


def build_datasets() -> SeedDatasets:
    records = [
        make_record(1, scenario="compliant_live", archetype="compliant"),
        make_record(
            2,
            scenario="high_risk_live",
            archetype="high_risk",
            permit_status="expired",
            sanctions=["SAP sanction list"],
            expected_signal="legal",
        ),
        make_record(3, archetype="ambiguous", hgu=False, expected_ambiguity="permit_gap"),
        make_record(4, archetype="compliant"),
    ]
    batch = BatchDataset(
        rng_seed=7,
        distribution={"compliant": 2, "high_risk": 1, "ambiguous": 1},
        records=records,
    )
    return SeedDatasets(batch, make_operator())


def test_settings(
    tmp_path: Path,
    *,
    batch_concurrency: int = 2,
    auto_seed: bool = True,
) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'terrasentry-test.db'}",
        auto_seed=auto_seed,
        batch_concurrency=batch_concurrency,
        run_timeout_seconds=30,
        sse_ping_seconds=0,
        agent_model="scripted",
    )


async def _create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def load_seed_datasets() -> SeedDatasets:
    """The committed 50-record seed, used by the M6 full-batch tests."""
    return SeedDatasets.load(
        batch_path=SEED_DIR / "batch_50.json",
        operator_path=SEED_DIR / "operator.json",
    )


def test_services_factory(
    tmp_path: Path,
    datasets: SeedDatasets | None = None,
    *,
    batch_concurrency: int = 2,
    auto_seed: bool = True,
    cache: CacheBackend | None = None,
    offline: bool = False,
) -> ServicesFactory:
    """A lifespan-compatible factory that never touches Postgres or Redis."""
    resolved = datasets or build_datasets()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AppServices]:
        settings = test_settings(tmp_path, batch_concurrency=batch_concurrency, auto_seed=auto_seed)
        integration = IntegrationSettings(
            gfw_api_key="test-key",
            gfw_rate_limit_per_min=100_000,
            firms_map_key="TESTKEY",
            firms_rate_limit_per_10min=100_000,
            cache_backend="memory",
        )
        engine, session_factory = create_engine_and_session(settings.database_url)
        await _create_all(engine)
        cache_backend = cache or MemoryCache()
        gfw = GfwClient(integration, cache=cache_backend)
        firms = FirmsClient(integration, cache=cache_backend)
        if settings.auto_seed:
            async with session_factory() as session:
                await seed_if_empty(RunStore(session), resolved)
        manager = RunManager(
            settings=settings,
            session_factory=session_factory,
            datasets=resolved,
            gfw=gfw,
            firms=firms,
            cache=cache_backend,
        )
        services = AppServices(
            settings=settings,
            integration=integration,
            engine=engine,
            session_factory=session_factory,
            cache=cache_backend,
            gfw=gfw,
            firms=firms,
            datasets=resolved,
            run_manager=manager,
            mock_sap=MockSapStore(record.supplier_id for record in resolved.records),
            offline=offline,
        )
        try:
            yield services
        finally:
            await services.aclose()

    return factory


def wait_for_state(
    client: TestClient,
    run_id: str,
    states: set[str],
    *,
    timeout: float = 20.0,
    path: str = "/runs",
) -> dict[str, Any]:
    """Poll a run (or batch) until it reaches one of ``states``."""
    deadline = time.monotonic() + timeout
    payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"{path}/{run_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["state"] in states:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {states}; last payload {payload}")


def read_sse(
    client: TestClient,
    url: str,
    *,
    stop_event: str = "done",
) -> list[dict[str, Any]]:
    """Consume an SSE endpoint until ``stop_event`` and return parsed events."""
    events: list[dict[str, Any]] = []
    name = "message"
    with client.stream("GET", url) as response:
        assert response.status_code == 200, response.read()
        for raw in response.iter_lines():
            line = raw.rstrip("\r")
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append({"event": name, "data": json.loads(line.split(":", 1)[1].strip())})
                if name == stop_event:
                    return events
    return events


__all__ = [
    "FIRMS_REGEX",
    "GFW_URL",
    "SEED_DIR",
    "build_datasets",
    "load_seed_datasets",
    "make_operator",
    "make_record",
    "read_sse",
    "test_services_factory",
    "test_settings",
    "wait_for_state",
]
