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
    errors: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when both real sources answered for this polygon."""
        return self.loss is not None and self.hotspots is not None


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
    """Fetch real GFW/FIRMS data for one polygon, tolerating per-source failures.

    ``as_of`` pins the FIRMS end date and (when no explicit ``loss_window`` is
    given) the GFW year window, so a live prefetch and a later offline rehearsal
    resolve the same cache keys even on different days.
    """
    resolved = loss_window if loss_window is not None else resolve_loss_window(loss_years, as_of=as_of)
    sources = PolygonSources(polygon_id=polygon.id)
    try:
        sources.loss = await gfw.tree_cover_loss(
            polygon.geometry,
            start_year=resolved.start_year,
            end_year=resolved.end_year,
            refresh=refresh,
        )
    except (SourceError, MissingCredentialError) as exc:
        sources.errors.append(str(exc))
    try:
        sources.hotspots = await firms.hotspots_in_polygon(
            polygon.geometry,
            days=window_days,
            end_date=as_of,
            refresh=refresh,
        )
    except (SourceError, MissingCredentialError) as exc:
        sources.errors.append(str(exc))
    return sources


__all__ = [
    "LossWindow",
    "PolygonSources",
    "fetch_polygon_sources",
    "resolve_loss_window",
]
