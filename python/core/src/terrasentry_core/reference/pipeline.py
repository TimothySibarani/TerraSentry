"""Reference pipeline: deterministic, cache-aware GFW + FIRMS lookup per polygon.

This is the baseline the M3 agent must match (architecture cross-cutting rule 5). It
contains no model calls and no scoring; it fetches real source data and records it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field
from terrasentry_integrations.cache import CacheBackend
from terrasentry_integrations.errors import SourceError
from terrasentry_integrations.sources.firms import FirmsClient, FirmsHotspotResult
from terrasentry_integrations.sources.gfw import GfwClient, TreeCoverLossResult

from terrasentry_core.seed.schemas import SeedPolygon


class PolygonReport(BaseModel):
    polygon_id: str
    label: str
    region: str
    archetype: str
    area_ha: float
    loss: TreeCoverLossResult | None = None
    hotspots: FirmsHotspotResult | None = None
    errors: list[str] = Field(default_factory=list)


class ReferenceRun(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    window_days: int
    years: int
    offline: bool
    cache_stats: dict[str, int]
    reports: list[PolygonReport]


async def run_reference_pipeline(
    polygons: Sequence[SeedPolygon],
    *,
    gfw: GfwClient,
    firms: FirmsClient,
    cache: CacheBackend,
    window_days: int = 30,
    years: int = 5,
    offline: bool = False,
) -> ReferenceRun:
    """Fetch real GFW/FIRMS data for every polygon, tolerating per-source failures."""
    started = datetime.now(tz=UTC)
    end_year = started.year - 1
    start_year = end_year - years + 1

    reports: list[PolygonReport] = []
    for polygon in polygons:
        report = PolygonReport(
            polygon_id=polygon.id,
            label=polygon.label,
            region=polygon.region,
            archetype=polygon.archetype,
            area_ha=polygon.area_ha,
        )
        try:
            report.loss = await gfw.tree_cover_loss(
                polygon.geometry, start_year=start_year, end_year=end_year
            )
        except SourceError as exc:
            report.errors.append(str(exc))
        try:
            report.hotspots = await firms.hotspots_in_polygon(polygon.geometry, days=window_days)
        except SourceError as exc:
            report.errors.append(str(exc))
        reports.append(report)

    finished = datetime.now(tz=UTC)
    return ReferenceRun(
        run_id=f"ref-{started:%Y%m%dT%H%M%S}-{uuid4().hex[:6]}",
        started_at=started,
        finished_at=finished,
        window_days=window_days,
        years=years,
        offline=offline,
        cache_stats=cache.stats().as_dict(),
        reports=reports,
    )
