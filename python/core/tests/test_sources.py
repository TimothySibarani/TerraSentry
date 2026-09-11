"""Source-window resolution and pinned rehearsals (M6)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast

from terrasentry_core.seed.schemas import SeedPolygon
from terrasentry_core.tools.sources import (
    LossWindow,
    fetch_polygon_sources,
    resolve_loss_window,
)


class FakeGfw:
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
