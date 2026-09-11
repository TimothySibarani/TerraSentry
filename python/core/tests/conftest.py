"""Deterministic fixtures for the M2 deterministic-core tests.

Everything here is hand-built in code so no source credentials, network access,
or committed API responses are needed. Timestamps are fixed constants, which is
what makes byte-for-byte determinism assertions possible.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import agent_helpers
import pytest
import respx
from terrasentry_core.domain.models import (
    AssessmentInput,
    Consignment,
    OperatorProfile,
    Parcel,
    SupplierProfile,
)
from terrasentry_core.seed.schemas import (
    Archetype,
    BatchRecord,
    ConsignmentRecord,
    LegalityRecord,
    SeedPolygon,
)
from terrasentry_integrations.cache import MemoryCache
from terrasentry_integrations.sources.firms import FireDetection, FirmsClient, FirmsHotspotResult
from terrasentry_integrations.sources.gfw import GfwClient, TreeCoverLossResult, TreeCoverLossYear

FIXED_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
WINDOW_END = date(2026, 9, 1)

BIG_POLYGON: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[101.0, 0.0], [101.02, 0.0], [101.02, 0.02], [101.0, 0.02], [101.0, 0.0]]],
}
SMALL_POLYGON: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [
            [101.0, 0.0],
            [101.0005, 0.0],
            [101.0005, 0.0005],
            [101.0, 0.0005],
            [101.0, 0.0],
        ]
    ],
}


def make_parcel(
    *,
    polygon_id: str = "PLY-TEST",
    area_ha: float = 500.0,
    geometry: dict[str, Any] | None = None,
    centroid_lon: float = 101.01,
    centroid_lat: float = 0.01,
) -> Parcel:
    return Parcel(
        polygon_id=polygon_id,
        label=f"Test parcel {polygon_id}",
        region="Riau peat forests",
        province="Riau",
        area_ha=area_ha,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        geometry=geometry if geometry is not None else BIG_POLYGON,
    )


def make_supplier(**overrides: Any) -> SupplierProfile:
    payload: dict[str, Any] = {
        "supplier_id": "SUP-TEST",
        "legal_name": "PT Uji Lestari Nusantara",
        "trading_name": "Uji Lestari Nusantara (SYNTH-TEST)",
        "group": "Grup Nusantara",
        "nib": "1234567890123",
        "npwp": "12.345.678.9-012.345",
        "hgu_number": "HGU No. 42/HGU/BPN/2019",
        "pbp_number": None,
        "permit_status": "active",
        "concession_area_ha": 9000.0,
        "province": "Riau",
        "kabupaten": "Siak",
        "beneficial_owners": ["Sari Wijaya"],
        "certifications": ["ISPO"],
        "sanctions": [],
        "synthetic": True,
        "disclosure": "SYNTHETIC TEST DATA — fixture",
    }
    payload.update(overrides)
    return SupplierProfile(**payload)


def make_legality(**overrides: Any) -> LegalityRecord:
    return LegalityRecord(**make_supplier(**overrides).model_dump())


def make_consignment(**overrides: Any) -> Consignment:
    payload: dict[str, Any] = {
        "supplier_id": "SUP-TEST",
        "commodity": "oil_palm",
        "description": "Crude palm oil (synthetic consignment)",
        "hs_heading": "1511",
        "species_scientific": "Elaeis guineensis",
        "species_common": "Kelapa sawit",
        "net_weight_kg": 4_500_000.0,
        "production_place": "Block 01 — Test (SYNTH)",
        "harvest_year": 2025,
        "synthetic": True,
        "disclosure": "SYNTHETIC TEST DATA — fixture",
    }
    payload.update(overrides)
    return Consignment(**payload)


def make_seed_consignment(**overrides: Any) -> ConsignmentRecord:
    return ConsignmentRecord(**make_consignment(**overrides).model_dump())


def make_operator(**overrides: Any) -> OperatorProfile:
    payload: dict[str, Any] = {
        "operator_id": "OP-SYNTH-TEST",
        "legal_name": "SYNTH EU Imports B.V.",
        "identifier_type": "eori",
        "identifier_value": "NL998877665544332",
        "address_line": "SYNTH-Port 1",
        "postal_code": "3011 XX",
        "city": "Rotterdam",
        "country": "NL",
        "email": "ops@synth.terrasentry.example",
        "phone": "+31 10 000 0000",
        "activity_type": "IMPORT",
        "country_of_activity": "NL",
        "border_cross_country": "NL",
        "synthetic": True,
        "disclosure": "SYNTHETIC TEST DATA — fixture",
    }
    payload.update(overrides)
    return OperatorProfile(**payload)


def make_loss(
    *,
    total_ha: float = 0.0,
    year: int = 2022,
    by_year: list[TreeCoverLossYear] | None = None,
    fetched_at: datetime | None = FIXED_TIME,
    cached: bool = False,
) -> TreeCoverLossResult:
    if by_year is None:
        by_year = [TreeCoverLossYear(year=year, loss_ha=total_ha)] if total_ha else []
    return TreeCoverLossResult(
        dataset="umd_tree_cover_loss",
        version="v1.13",
        geometry_hash="a" * 64,
        date_window="2021-2025",
        start_year=2021,
        end_year=2025,
        total_loss_ha=sum(item.loss_ha for item in by_year),
        by_year=by_year,
        cached=cached,
        fetched_at=fetched_at,
    )


def make_hotspots(
    *,
    count: int = 0,
    total_frp: float = 0.0,
    last_detection: date | None = None,
    window_end: date = WINDOW_END,
    fetched_at: datetime | None = FIXED_TIME,
    cached: bool = False,
) -> FirmsHotspotResult:
    provided = last_detection or window_end
    detections = [
        FireDetection(
            latitude=0.01,
            longitude=101.01,
            acq_date=provided,
            frp=total_frp / count if count else 0.0,
        )
        for _ in range(count)
    ]
    return FirmsHotspotResult(
        source="VIIRS_SNPP_NRT",
        geometry_hash="a" * 64,
        date_window=f"{window_end.isoformat()}..{window_end.isoformat()}",
        window_start=window_end,
        window_end=window_end,
        detection_count=count,
        total_frp=total_frp,
        detections=detections,
        cached=cached,
        fetched_at=fetched_at,
    )


_UNSET: Any = object()


def make_input(
    *,
    parcel: Parcel | None = None,
    supplier: SupplierProfile | None = None,
    loss: TreeCoverLossResult | None = _UNSET,
    hotspots: FirmsHotspotResult | None = _UNSET,
    consignment: Consignment | None = _UNSET,
    operator: OperatorProfile | None = _UNSET,
    record_id: str = "REC-TEST",
) -> AssessmentInput:
    return AssessmentInput(
        record_id=record_id,
        parcel=parcel or make_parcel(),
        supplier=supplier or make_supplier(),
        loss=make_loss() if loss is _UNSET else loss,
        hotspots=make_hotspots() if hotspots is _UNSET else hotspots,
        consignment=make_consignment() if consignment is _UNSET else consignment,
        operator=make_operator() if operator is _UNSET else operator,
    )


def make_batch_record(
    *,
    index: int = 1,
    expected_archetype: Archetype = "compliant",
    parcel: Parcel | None = None,
    supplier: SupplierProfile | None = None,
    **overrides: Any,
) -> BatchRecord:
    domain_parcel = parcel or make_parcel(polygon_id=f"PLY-{index:03d}")
    domain_supplier = supplier or make_supplier(supplier_id=f"SUP-{index:03d}")
    polygon = SeedPolygon(
        id=domain_parcel.polygon_id,
        label=domain_parcel.label,
        region=domain_parcel.region,
        province=domain_parcel.province,
        archetype=expected_archetype,
        is_demo=index <= 8,
        area_ha=domain_parcel.area_ha,
        centroid_lat=domain_parcel.centroid_lat,
        centroid_lon=domain_parcel.centroid_lon,
        geometry=domain_parcel.geometry,
    )
    legality = LegalityRecord(**domain_supplier.model_dump())
    consignment = make_seed_consignment(supplier_id=domain_supplier.supplier_id)
    payload: dict[str, Any] = {
        "record_id": f"REC-{index:03d}",
        "supplier_id": domain_supplier.supplier_id,
        "polygon": polygon,
        "legality": legality,
        "consignment": consignment,
        "expected_archetype": expected_archetype,
    }
    payload.update(overrides)
    return BatchRecord(**payload)


@pytest.fixture
def factories() -> dict[str, Callable[..., Any]]:
    return {
        "parcel": make_parcel,
        "supplier": make_supplier,
        "legality": make_legality,
        "consignment": make_consignment,
        "operator": make_operator,
        "loss": make_loss,
        "hotspots": make_hotspots,
        "input": make_input,
        "batch_record": make_batch_record,
        "seed_consignment": make_seed_consignment,
    }


@pytest.fixture
def source_router():
    """respx router with deterministic GFW/FIRMS responses for agent tests."""
    with respx.mock(assert_all_called=False) as router:
        router.post(agent_helpers.GFW_URL).mock(side_effect=agent_helpers.gfw_side_effect)
        router.get(url__regex=re.compile(agent_helpers.FIRMS_REGEX)).mock(
            side_effect=agent_helpers.firms_side_effect
        )
        yield router


@pytest.fixture
async def source_clients():
    """Live clients with test credentials; HTTP must be mocked by the caller."""
    cache = MemoryCache()
    gfw = GfwClient(agent_helpers.settings(), cache=cache)
    firms = FirmsClient(agent_helpers.settings(), cache=cache)
    try:
        yield SimpleNamespace(gfw=gfw, firms=firms, cache=cache)
    finally:
        await gfw.close()
        await firms.close()
