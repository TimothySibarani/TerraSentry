"""Strands tool functions over the shared source layer.

The LLM chooses *what* to look up; every value comes from the M1 clients or the
seed datasets. Tools accept ids only, never numbers, which is what makes the
agent path structurally comparable to the reference pipeline. Each call appends
a step to the run trace so the cockpit can show it later (M5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from strands import tool
from strands.types.tools import AgentTool
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient

from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.sources import LossWindow, PolygonSources, fetch_polygon_sources
from terrasentry_core.tools.trace import TraceCollector

if TYPE_CHECKING:
    from terrasentry_core.agents.verification import VerificationReport
    from terrasentry_core.assessment.pipeline import RecordAssessment


@dataclass
class ToolContext:
    """Per-run dependencies, collected sources, and the computed candidate."""

    gfw: GfwClient
    firms: FirmsClient
    datasets: SeedDatasets
    trace: TraceCollector
    window_days: int = 30
    loss_window: LossWindow = field(default_factory=LossWindow.from_now)
    as_of: date | None = None
    retrieved_at: datetime | None = None
    refresh: bool = False
    candidate: RecordAssessment | None = None
    verification: VerificationReport | None = None
    summary: str = ""
    _sources: dict[str, PolygonSources] = field(default_factory=dict, init=False, repr=False)

    async def polygon_sources(self, polygon_id: str, *, refresh: bool = False) -> PolygonSources:
        """Return the sources already fetched for a polygon, fetching once otherwise."""
        if not refresh and polygon_id in self._sources:
            return self._sources[polygon_id]
        record = self.datasets.record_for_polygon(polygon_id)
        sources = await fetch_polygon_sources(
            record.polygon,
            gfw=self.gfw,
            firms=self.firms,
            window_days=self.window_days,
            loss_window=self.loss_window,
            refresh=refresh or self.refresh,
            as_of=self.as_of,
        )
        self._sources[polygon_id] = sources
        return sources

    @property
    def collected_sources(self) -> list[PolygonSources]:
        return list(self._sources.values())


def _loss_payload(polygon_id: str, sources: PolygonSources) -> dict[str, Any]:
    loss = sources.loss
    if loss is None:
        reason = "; ".join(sources.errors)
        return {"polygon_id": polygon_id, "error": f"tree cover loss unavailable: {reason}"}
    return {
        "polygon_id": polygon_id,
        "dataset": loss.dataset,
        "version": loss.version,
        "date_window": loss.date_window,
        "total_loss_ha": loss.total_loss_ha,
        "by_year": [item.model_dump(mode="json") for item in loss.by_year],
        "cached": loss.cached,
    }


def _hotspot_payload(polygon_id: str, sources: PolygonSources) -> dict[str, Any]:
    hotspots = sources.hotspots
    if hotspots is None:
        reason = "; ".join(sources.errors)
        return {"polygon_id": polygon_id, "error": f"fire hotspots unavailable: {reason}"}
    return {
        "polygon_id": polygon_id,
        "source": hotspots.source,
        "date_window": hotspots.date_window,
        "detection_count": hotspots.detection_count,
        "total_frp": hotspots.total_frp,
        "cached": hotspots.cached,
    }


def build_source_tools(context: ToolContext) -> list[AgentTool]:
    """Tools for the geospatial, thermal, and legality specialists."""

    @tool
    async def get_tree_cover_loss(polygon_id: str) -> dict[str, Any]:
        """Fetch Hansen Global Forest Watch annual tree cover loss for a seed polygon.

        Args:
            polygon_id: Seed polygon identifier, for example PLY-001.
        """
        sources = await context.polygon_sources(polygon_id)
        payload = _loss_payload(polygon_id, sources)
        detail = (
            f"{polygon_id}: {payload.get('total_loss_ha', 'no')} ha loss "
            f"{payload.get('date_window', '')}".strip()
        )
        context.trace.add("tool", "get_tree_cover_loss", detail, payload={"polygon_id": polygon_id})
        return payload

    @tool
    async def get_fire_hotspots(polygon_id: str) -> dict[str, Any]:
        """Fetch NASA FIRMS thermal anomalies (hotspots) inside a seed polygon.

        Args:
            polygon_id: Seed polygon identifier, for example PLY-001.
        """
        sources = await context.polygon_sources(polygon_id)
        payload = _hotspot_payload(polygon_id, sources)
        context.trace.add(
            "tool",
            "get_fire_hotspots",
            f"{polygon_id}: {payload.get('detection_count', 'no')} detection(s)",
            payload={"polygon_id": polygon_id},
        )
        return payload

    @tool
    async def get_legality_record(supplier_id: str) -> dict[str, Any]:
        """Read the synthetic HGU/PBPH permit and entity record for a supplier.

        Args:
            supplier_id: Seed supplier identifier, for example SUP-001.
        """
        record = context.datasets.record_for_supplier(supplier_id)
        legality = record.legality
        context.trace.add(
            "tool",
            "get_legality_record",
            f"{supplier_id}: permit {legality.permit_status!r}",
            payload={"supplier_id": supplier_id},
        )
        return {
            "supplier_id": supplier_id,
            "legal_name": legality.legal_name,
            "permit_status": legality.permit_status,
            "hgu_number": legality.hgu_number,
            "pbp_number": legality.pbp_number,
            "sanctions": legality.sanctions,
            "certifications": legality.certifications,
            "synthetic": legality.synthetic,
            "disclosure": legality.disclosure,
        }

    @tool
    async def get_consignment(record_id: str) -> dict[str, Any]:
        """Read the synthetic consignment declared in the DDS for a record.

        Args:
            record_id: Seed batch record identifier, for example REC-001.
        """
        record = context.datasets.get_record(record_id)
        consignment = record.consignment
        context.trace.add(
            "tool",
            "get_consignment",
            f"{record_id}: HS {consignment.hs_heading}",
            payload={"record_id": record_id},
        )
        return {
            "record_id": record_id,
            "commodity": consignment.commodity,
            "description": consignment.description,
            "hs_heading": consignment.hs_heading,
            "net_weight_kg": consignment.net_weight_kg,
            "synthetic": consignment.synthetic,
            "disclosure": consignment.disclosure,
        }

    return [get_tree_cover_loss, get_fire_hotspots, get_legality_record, get_consignment]


def build_verifier_tools(context: ToolContext) -> list[AgentTool]:
    """Read-only inspection tools for the independent verifier; no writes."""

    @tool
    async def get_source_claims(polygon_id: str) -> dict[str, Any]:
        """Read the raw GFW/FIRMS claims collected for a polygon.

        Args:
            polygon_id: Seed polygon identifier, for example PLY-001.
        """
        sources = await context.polygon_sources(polygon_id)
        context.trace.add(
            "verifier",
            "get_source_claims",
            polygon_id,
            payload={"polygon_id": polygon_id},
        )
        return {
            "polygon_id": polygon_id,
            "loss": _loss_payload(polygon_id, sources),
            "hotspots": _hotspot_payload(polygon_id, sources),
            "errors": list(sources.errors),
        }

    @tool
    async def get_assessment(supplier_id: str) -> dict[str, Any]:
        """Read the deterministic assessment candidate for a supplier.

        Args:
            supplier_id: Seed supplier identifier, for example SUP-001.
        """
        candidate = context.candidate
        if candidate is None or candidate.supplier_id != supplier_id:
            return {"supplier_id": supplier_id, "error": "no candidate assessment is available"}
        context.trace.add(
            "verifier",
            "get_assessment",
            f"{supplier_id}: {candidate.assessment.verdict}",
            payload={"supplier_id": supplier_id},
        )
        return {
            "supplier_id": supplier_id,
            "score": candidate.assessment.score,
            "verdict": candidate.assessment.verdict.value,
            "findings": [finding.model_dump(mode="json") for finding in candidate.assessment.findings],
            "data_gaps": candidate.assessment.data_gaps,
            "fingerprint": candidate.fingerprint,
        }

    @tool
    async def list_evidence_claims() -> list[dict[str, str]]:
        """List the ledger claims and evidence ids behind the candidate assessment."""
        candidate = context.candidate
        if candidate is None:
            return []
        context.trace.add("verifier", "list_evidence_claims", "ledger inspection")
        return [{"evidence_id": entry.evidence_id, "claim": entry.claim} for entry in candidate.evidence]

    @tool
    async def get_evidence_entry(evidence_id: str) -> dict[str, Any]:
        """Read one ledger entry by id so a claim can be checked against its source.

        Args:
            evidence_id: Ledger id such as EV-global_forest_watch-0123456789ab.
        """
        candidate = context.candidate
        if candidate is None:
            return {"evidence_id": evidence_id, "error": "no candidate assessment is available"}
        for entry in candidate.evidence:
            if entry.evidence_id == evidence_id:
                context.trace.add("verifier", "get_evidence_entry", evidence_id)
                return entry.model_dump(mode="json")
        return {"evidence_id": evidence_id, "error": "evidence id is not in the ledger"}

    return [get_source_claims, get_assessment, list_evidence_claims, get_evidence_entry]


__all__ = ["ToolContext", "build_source_tools", "build_verifier_tools"]
