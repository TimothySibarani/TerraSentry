"""Reference pipeline: deterministic, cache-aware GFW + FIRMS lookup per polygon.

This is the baseline the M3 agent must match (architecture cross-cutting rule 5). It
contains no model calls and no scoring; it fetches real source data and records it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import uuid4

from pydantic import BaseModel, Field
from terrasentry_integrations.cache import CacheBackend
from terrasentry_integrations.sources.firms import FirmsClient, FirmsHotspotResult
from terrasentry_integrations.sources.gfw import GfwClient, TreeCoverLossResult
from terrasentry_integrations.sources.gfw_layers import ContextLayersResult

from terrasentry_core.seed.schemas import SeedPolygon
from terrasentry_core.tools.sources import fetch_polygon_sources


class PolygonReport(BaseModel):
    polygon_id: str
    label: str
    region: str
    archetype: str | None = None
    area_ha: float
    loss: TreeCoverLossResult | None = None
    hotspots: FirmsHotspotResult | None = None
    layers: ContextLayersResult | None = None
    errors: list[str] = Field(default_factory=list)


class ReferenceRun(BaseModel):
    assessment_date: date | None = None
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
    as_of: date | None = None,
) -> ReferenceRun:
    """Fetch real GFW/FIRMS data for every polygon, tolerating per-source failures."""
    started = datetime.now(tz=UTC)
    assessment_date = as_of or started.date()

    reports: list[PolygonReport] = []
    for polygon in polygons:
        sources = await fetch_polygon_sources(
            polygon,
            gfw=gfw,
            firms=firms,
            window_days=window_days,
            as_of=assessment_date,
        )
        reports.append(
            PolygonReport(
                polygon_id=polygon.id,
                label=polygon.label,
                region=polygon.region,
                archetype=polygon.archetype,
                area_ha=polygon.area_ha,
                loss=sources.loss,
                hotspots=sources.hotspots,
                layers=sources.layers,
                errors=sources.errors,
            )
        )

    finished = datetime.now(tz=UTC)
    return ReferenceRun(
        assessment_date=assessment_date,
        run_id=f"ref-{started:%Y%m%dT%H%M%S}-{uuid4().hex[:6]}",
        started_at=started,
        finished_at=finished,
        window_days=window_days,
        years=years,
        offline=offline,
        cache_stats=cache.stats().as_dict(),
        reports=reports,
    )
