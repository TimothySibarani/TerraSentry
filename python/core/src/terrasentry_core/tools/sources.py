"""Shared GFW/FIRMS fetch used by the reference pipeline and the agent tools.

Architecture cross-cutting rule 5: the deterministic reference run and the M3
agent path must call the same source code, so their structured outputs can be
compared field for field. Nothing here invents values; the functions wrap the
M1 clients and tolerate per-source failures exactly like the reference did.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, Field
from terrasentry_integrations.errors import MissingCredentialError, SourceError
from terrasentry_integrations.sources.firms import FirmsClient, FirmsHotspotResult
from terrasentry_integrations.sources.gfw import GfwClient, TreeCoverLossResult
from terrasentry_integrations.sources.gfw_layers import ContextLayersResult

from terrasentry_core.seed.schemas import SeedPolygon


class LossWindow(BaseModel):
    """Resolved GFW tree-cover-loss query window.

    The dataset lags one calendar year, so ``from_now`` resolves the window once
    per run and callers pass it explicitly to keep multi-polygon runs consistent
    across a year boundary.
    """

    start_year: int
    end_year: int

    @classmethod
    def from_now(cls, years: int = 5, *, now: datetime | None = None) -> LossWindow:
        if years < 1:
            raise ValueError("years must be >= 1")
        end_year = (now or datetime.now(tz=UTC)).year - 1
        return cls(start_year=end_year - years + 1, end_year=end_year)


def resolve_loss_window(
    years: int = 5, *, as_of: date | None = None, now: datetime | None = None
) -> LossWindow:
    """Resolve a loss window, honouring a pinned ``as_of`` date when given."""
    if as_of is not None:
        return LossWindow.from_now(years, now=datetime(as_of.year, 1, 1, tzinfo=UTC))
    return LossWindow.from_now(years, now=now)


class PolygonSources(BaseModel):
    """One polygon's real source results plus any per-source failures."""

    polygon_id: str
    loss: TreeCoverLossResult | None = None
    hotspots: FirmsHotspotResult | None = None
    layers: ContextLayersResult | None = None
    errors: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when all required sources and annual coverage are available."""
        return (
            not self.errors
            and self.loss is not None
            and self.hotspots is not None
            and self.layers is not None
            and self.layers.complete
        )


async def fetch_polygon_sources(
    polygon: SeedPolygon,
    *,
    gfw: GfwClient,
    firms: FirmsClient,
    window_days: int = 30,
    loss_window: LossWindow | None = None,
    loss_years: int = 5,
    refresh: bool = False,
    as_of: date | None = None,
) -> PolygonSources:
    """Fetch sources with the full post-2020 cutoff through verified annual coverage.

    Legacy rolling-window arguments remain accepted for callers; compliance
    always uses 2021 onward. ``as_of`` also pins the FIRMS end date.
    """
    assessment_date = as_of or datetime.now(tz=UTC).date()
    sources = PolygonSources(polygon_id=polygon.id)
    try:
        required_end = assessment_date.year - 1
        verified_end = gfw.coverage_end_year
        covered_end = min(required_end, verified_end)
        if required_end < 2021:
            sources.errors.append("gfw:loss: assessment date precedes the supported post-2020 annual window")
        else:
            if required_end > verified_end:
                sources.errors.append(
                    f"gfw:loss: annual coverage unavailable for {max(2021, verified_end + 1)}-{required_end}"
                )
            if covered_end >= 2021:
                sources.loss = await gfw.tree_cover_loss(
                    polygon.geometry,
                    start_year=2021,
                    end_year=covered_end,
                    refresh=refresh,
                )
    except (SourceError, MissingCredentialError) as exc:
        sources.errors.append(str(exc))
    try:
        sources.hotspots = await firms.hotspots_in_polygon(
            polygon.geometry,
            days=window_days,
            end_date=assessment_date,
            refresh=refresh,
        )
    except (SourceError, MissingCredentialError) as exc:
        sources.errors.append(str(exc))
    sources.layers = await gfw.context_layers(polygon.geometry, country=polygon.country, refresh=refresh)
    sources.errors.extend(
        f"gfw:{layer.name}: {layer.error}" for layer in sources.layers.layers if layer.status == "unavailable"
    )
    return sources


__all__ = [
    "LossWindow",
    "PolygonSources",
    "fetch_polygon_sources",
    "resolve_loss_window",
]
