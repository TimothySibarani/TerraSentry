"""Source-window resolution and pinned rehearsals (M6)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from conftest import make_hotspots, make_input, make_loss
from terrasentry_core.dds import build_dds
from terrasentry_core.evidence import build_source_ledger
from terrasentry_core.scoring import assess
from terrasentry_core.seed.schemas import SeedPolygon
from terrasentry_core.tools.sources import (
    LossWindow,
    fetch_polygon_sources,
    resolve_loss_window,
)


class FakeGfw:
    coverage_end_year = 2025

    async def context_layers(self, geometry: Any, **kwargs: Any) -> Any:
        from conftest import clear_layers

        return clear_layers()

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, bool]] = []

    async def tree_cover_loss(
        self, geometry: Any, *, start_year: int, end_year: int, refresh: bool = False
    ) -> Any:
        self.calls.append((start_year, end_year, refresh))
        return None


class FakeFirms:
    def __init__(self) -> None:
        self.calls: list[tuple[int, date | None, bool]] = []

    async def hotspots_in_polygon(
        self, geometry: Any, *, days: int, end_date: date | None = None, refresh: bool = False
    ) -> Any:
        self.calls.append((days, end_date, refresh))
        return None


POLYGON = SeedPolygon(
    id="PLY-TEST",
    label="Pinned parcel",
    region="Riau peat forests",
    province="Riau",
    archetype="compliant",
    area_ha=100.0,
    centroid_lat=0.0,
    centroid_lon=101.0,
    geometry={
        "type": "Polygon",
        "coordinates": [[[101.0, 0.0], [101.01, 0.0], [101.0, 0.01], [101.0, 0.0]]],
    },
)


def test_resolve_loss_window_uses_the_wall_clock_by_default() -> None:
    now = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
    assert resolve_loss_window(5, now=now) == LossWindow(start_year=2021, end_year=2025)
    assert resolve_loss_window(2, now=now) == LossWindow(start_year=2024, end_year=2025)


def test_resolve_loss_window_pins_to_the_as_of_year() -> None:
    assert resolve_loss_window(5, as_of=date(2026, 9, 11)) == LossWindow(start_year=2021, end_year=2025)
    assert resolve_loss_window(2, as_of=date(2030, 1, 1)) == LossWindow(start_year=2028, end_year=2029)


async def test_fetch_polygon_sources_threads_the_pinned_as_of() -> None:
    gfw, firms = FakeGfw(), FakeFirms()
    sources = await fetch_polygon_sources(
        POLYGON,
        gfw=cast(Any, gfw),
        firms=cast(Any, firms),
        window_days=10,
        refresh=True,
        as_of=date(2026, 9, 11),
    )
    assert sources.errors == []
    assert gfw.calls == [(2021, 2025, True)]
    assert firms.calls == [(10, date(2026, 9, 11), True)]


async def test_future_runs_keep_the_full_cutoff_and_verified_coverage() -> None:
    gfw, firms = FakeGfw(), FakeFirms()
    sources = await fetch_polygon_sources(
        POLYGON,
        gfw=cast(Any, gfw),
        firms=cast(Any, firms),
        as_of=date(2027, 1, 1),
        loss_years=2,
        loss_window=LossWindow(start_year=2025, end_year=2026),
    )
    assert gfw.calls == [(2021, 2025, False)]
    assert sources.errors == ["gfw:loss: annual coverage unavailable for 2026-2026"]
    assert not sources.complete


@pytest.mark.parametrize(
    "as_of,expected", [(date(2026, 10, 2), "compliant"), (date(2027, 1, 1), "ambiguous")]
)
async def test_annual_coverage_gap_reaches_assessment_and_dds(as_of: date, expected: str) -> None:
    class CompleteGfw(FakeGfw):
        async def tree_cover_loss(
            self, geometry: Any, *, start_year: int, end_year: int, refresh: bool = False
        ) -> Any:
            self.calls.append((start_year, end_year, refresh))
            return make_loss()

    class CompleteFirms(FakeFirms):
        async def hotspots_in_polygon(self, geometry: Any, **kwargs: Any) -> Any:
            return make_hotspots()

    gfw, firms = CompleteGfw(), CompleteFirms()
    sources = await fetch_polygon_sources(POLYGON, gfw=cast(Any, gfw), firms=cast(Any, firms), as_of=as_of)
    assert gfw.calls == [(2021, 2025, False)]
    assert sources.complete == (expected == "compliant")
    inputs = make_input(loss=sources.loss, hotspots=sources.hotspots)
    inputs.assessment_date, inputs.layers, inputs.source_errors = as_of, sources.layers, sources.errors
    ledger = build_source_ledger(inputs)
    result = assess(inputs, ledger)
    assert result.verdict == expected
    assert result.data_gaps == sources.errors
    dds = build_dds(inputs, result, ledger)
    assert dds.assessment.data_gaps == sources.errors
    if expected == "ambiguous":
        assert inputs.layers is not None
        inputs.layers.layers[0].overlap_ha = 1
        assert assess(inputs, build_source_ledger(inputs)).verdict == "high_risk"


@pytest.mark.parametrize("as_of", [date(2020, 1, 1), date(2021, 12, 31)])
async def test_dates_before_supported_loss_window_skip_invalid_query(as_of: date) -> None:
    gfw, firms = FakeGfw(), FakeFirms()
    sources = await fetch_polygon_sources(POLYGON, gfw=cast(Any, gfw), firms=cast(Any, firms), as_of=as_of)
    assert gfw.calls == [] and len(firms.calls) == 1
    assert sources.layers is not None and sources.layers.complete
    assert not sources.complete and "precedes" in sources.errors[0]
