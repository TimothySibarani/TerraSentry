"""Strands tool functions over the shared source layer.

The LLM chooses *what* to look up; every value comes from the M1 clients or the
seed datasets. Tools accept ids only, never numbers, which is what makes the
agent path structurally comparable to the reference pipeline. Each call appends
a step to the run trace so the cockpit can show it later (M5).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from strands import tool
from strands.types.tools import AgentTool
from terrasentry_integrations.sources.firms import FirmsClient
from terrasentry_integrations.sources.gfw import GfwClient
from terrasentry_integrations.sources.gfw_layers import ContextLayer
from terrasentry_integrations.sources.media import AdverseMediaReport, MediaSearch

from terrasentry_core.agents.investigation import screening_signals
from terrasentry_core.scoring import concession_commodity, holder_matches
from terrasentry_core.tools.datasets import SeedDatasets
from terrasentry_core.tools.sources import LossWindow, PolygonSources, fetch_polygon_sources
from terrasentry_core.tools.trace import TraceCollector

if TYPE_CHECKING:
    from terrasentry_core.agents.verification import VerificationReport
    from terrasentry_core.assessment.pipeline import RecordAssessment

_MODEL_LAYER_BYTES = 8 * 1024
_CONCESSION_FEATURE_LIMIT = 20


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
    #: Optional adverse-media lookup. Context only: it never reaches the ledger or the rubric.
    media: MediaSearch | None = None
    _media_reports: dict[str, AdverseMediaReport] = field(default_factory=dict, init=False, repr=False)
    _media_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _sources: dict[str, PolygonSources] = field(default_factory=dict, init=False, repr=False)
    # ponytail: one acquisition lock per run; per-polygon locks if runs gain multiple parcels.
    _source_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def polygon_sources(self, polygon_id: str, *, refresh: bool = False) -> PolygonSources:
        """Share one accepted snapshot; refresh bypasses upstream cache on acquisition only."""
        async with self._source_lock:
            if polygon_id in self._sources:
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

    async def adverse_media(self, supplier_id: str) -> AdverseMediaReport | None:
        """One adverse-media lookup per supplier per run; ``None`` when the layer is disabled."""
        if self.media is None:
            return None
        async with self._media_lock:
            if supplier_id not in self._media_reports:
                record = self.datasets.record_for_supplier(supplier_id)
                self._media_reports[supplier_id] = await self.media.search(
                    record.legality.legal_name,
                    record.polygon.country,
                    as_of=self.as_of,
                    refresh=self.refresh,
                )
            return self._media_reports[supplier_id]

    @property
    def collected_sources(self) -> list[PolygonSources]:
        return list(self._sources.values())


def _layer_payload(layer: ContextLayer) -> dict[str, Any]:
    """Keep investigation facts; full source geometry lives in the persisted ledger."""
    payload = layer.model_dump(mode="json", exclude={"features": {"__all__": {"geometry"}}})
    payload["feature_count"] = len(layer.features)
    if len(json.dumps(payload).encode()) > _MODEL_LAYER_BYTES:
        payload["features"] = []
        payload["feature_details_error"] = (
            "Feature details exceed the model payload budget; inspect the full evidence artifact. "
            "Aggregate overlap and source status remain available."
        )
    return payload


def _context_payload(sources: PolygonSources) -> dict[str, Any] | None:
    return {"layers": [_layer_payload(layer) for layer in sources.layers.layers]} if sources.layers else None


def _context_summary(sources: PolygonSources) -> list[dict[str, Any]] | None:
    """Per-layer status and overlap only; feature detail comes from the deep-dive tools."""
    if sources.layers is None:
        return None
    return [
        {
            "name": layer.name,
            "status": layer.status,
            "overlap_ha": layer.overlap_ha,
            "feature_count": len(layer.features),
            "error": layer.error,
        }
        for layer in sources.layers.layers
    ]


def _loss_payload(polygon_id: str, sources: PolygonSources) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "polygon_id": polygon_id,
        "context_summary": _context_summary(sources),
        "screening_signals": screening_signals(sources),
        "errors": list(sources.errors),
    }
    loss = sources.loss
    if loss is None:
        reason = "; ".join(sources.errors)
        return {**payload, "error": f"tree cover loss unavailable: {reason}"}
    return {
        **payload,
        "dataset": loss.dataset,
        "version": loss.version,
        "date_window": loss.date_window,
        "total_loss_ha": loss.total_loss_ha,
        "by_year": [item.model_dump(mode="json") for item in loss.by_year],
        "cached": loss.cached,
    }


def _hotspot_payload(polygon_id: str, sources: PolygonSources) -> dict[str, Any]:
    hotspots = sources.hotspots
    signals = screening_signals(sources)
    if hotspots is None:
        reason = "; ".join(sources.errors)
        return {
            "polygon_id": polygon_id,
            "screening_signals": signals,
            "error": f"fire hotspots unavailable: {reason}",
        }
    dates = [item.acq_date for item in hotspots.detections]
    return {
        "polygon_id": polygon_id,
        "source": hotspots.source,
        "date_window": hotspots.date_window,
        "window_start": hotspots.window_start.isoformat(),
        "window_end": hotspots.window_end.isoformat(),
        "first_detection": min(dates).isoformat() if dates else None,
        "last_detection": max(dates).isoformat() if dates else None,
        "detection_count": hotspots.detection_count,
        "total_frp": hotspots.total_frp,
        "cached": hotspots.cached,
        "screening_signals": signals,
    }


def _concession_payload(
    polygon_id: str, supplier_id: str, sources: PolygonSources, declared_holder: str, commodity: str | None
) -> dict[str, Any]:
    """Each intersecting concession feature compared with the declared holder and commodity."""
    layers = {layer.name: layer for layer in sources.layers.layers} if sources.layers else {}
    concessions: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for name, layer in layers.items():
        if not name.endswith("_concessions"):
            continue
        if layer.status == "unavailable":
            unavailable.append(name)
            continue
        if layer.status != "success" or layer.overlap_ha <= 0:
            continue
        features = [
            {
                "feature_id": feature.feature_id,
                "company": feature.properties.get("company"),
                "overlap_ha": feature.overlap_ha,
                "holder_matches": holder_matches(feature.properties.get("company"), declared_holder),
            }
            for feature in layer.features
        ]
        # Surface the conflicts first so truncation can never hide one.
        features.sort(key=lambda item: item["holder_matches"] is True)
        concessions.append(
            {
                "layer": name,
                "dataset": layer.dataset,
                "overlap_ha": layer.overlap_ha,
                "commodity_authorised": concession_commodity(name),
                "commodity_matches": commodity == concession_commodity(name),
                "feature_count": len(features),
                "mismatched_holders": sum(item["holder_matches"] is False for item in features),
                "unknown_holders": sum(item["holder_matches"] is None for item in features),
                "features": features[:_CONCESSION_FEATURE_LIMIT],
                "features_truncated": len(features) > _CONCESSION_FEATURE_LIMIT,
            }
        )
    return {
        "polygon_id": polygon_id,
        "supplier_id": supplier_id,
        "declared_holder": declared_holder,
        "declared_commodity": commodity,
        "concessions": concessions,
        "unavailable_layers": unavailable,
        "overlap_found": bool(concessions),
    }


def _media_payload(supplier_id: str, report: AdverseMediaReport) -> dict[str, Any]:
    """Model- and trace-facing view of the report: findings with URLs, no scoring semantics."""
    body = report.model_dump(mode="json", exclude={"query_hash", "prompt_revision"})
    payload: dict[str, Any] = {
        "supplier_id": supplier_id,
        "context_only": True,
        "note": "Background context with source URLs, not rubric evidence. Quote claims with their URLs.",
        "report": body,
    }
    if report.status != "success":
        payload["error"] = report.error or "adverse media unavailable"
    if len(json.dumps(payload).encode()) > _MODEL_LAYER_BYTES:
        body["findings"] = body["findings"][:3]
        body["truncated"] = True
    return payload


def _status(payload: dict[str, Any]) -> str:
    return "error" if "error" in payload else "ok"


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
        context.trace.add(
            "tool",
            "get_tree_cover_loss",
            detail,
            payload={"polygon_id": polygon_id, "status": _status(payload)},
        )
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
            payload={"polygon_id": polygon_id, "status": _status(payload)},
        )
        return payload

    @tool
    async def get_legality_record(supplier_id: str) -> dict[str, Any]:
        """Read the declared HGU/PBPH permit and entity record for a supplier.

        Args:
            supplier_id: Seed supplier identifier, for example SUP-001.
        """
        record = context.datasets.record_for_supplier(supplier_id)
        legality = record.legality
        context.trace.add(
            "tool",
            "get_legality_record",
            f"{supplier_id}: permit {legality.permit_status!r}",
            payload={"supplier_id": supplier_id, "status": "ok"},
        )
        return {
            "supplier_id": supplier_id,
            "legal_name": legality.legal_name,
            "permit_status": legality.permit_status,
            "permit_expiry": legality.permit_expiry.isoformat() if legality.permit_expiry else None,
            "declared_holder": legality.declared_holder or legality.legal_name,
            "provenance": legality.provenance,
            "hgu_number": legality.hgu_number,
            "pbp_number": legality.pbp_number,
            "sanctions": legality.sanctions,
            "certifications": legality.certifications,
            "synthetic": legality.synthetic,
            "disclosure": legality.disclosure,
        }

    @tool
    async def get_consignment(record_id: str) -> dict[str, Any]:
        """Read the declared consignment declared in the DDS for a record.

        Args:
            record_id: Seed batch record identifier, for example REC-001.
        """
        record = context.datasets.get_record(record_id)
        consignment = record.consignment
        context.trace.add(
            "tool",
            "get_consignment",
            f"{record_id}: HS {consignment.hs_heading}",
            payload={"record_id": record_id, "status": "ok"},
        )
        return {
            "record_id": record_id,
            "commodity": consignment.commodity,
            "description": consignment.description,
            "hs_heading": consignment.hs_heading,
            "net_weight_kg": consignment.net_weight_kg,
            "synthetic": consignment.synthetic,
            "provenance": consignment.provenance,
            "disclosure": consignment.disclosure,
        }

    @tool
    async def get_context_layers(polygon_id: str) -> dict[str, Any]:
        """Deep dive: read feature-level context layers (protected areas, moratorium, peat, concessions).

        Args:
            polygon_id: Seed polygon identifier, for example PLY-001.
        """
        sources = await context.polygon_sources(polygon_id)
        payload: dict[str, Any] = {"polygon_id": polygon_id, **(_context_payload(sources) or {})}
        if sources.layers is None or any(layer.status == "unavailable" for layer in sources.layers.layers):
            payload["error"] = "context layers unavailable: " + (
                "; ".join(sources.errors) or "partial result"
            )
        layers = sources.layers.layers if sources.layers else []
        context.trace.add(
            "tool",
            "get_context_layers",
            f"{polygon_id}: {len(layers)} layer(s), "
            f"{sum(layer.overlap_ha > 0 for layer in layers)} with overlap",
            payload={"polygon_id": polygon_id, "status": _status(payload)},
        )
        return payload

    @tool
    async def check_concession_overlap(polygon_id: str, supplier_id: str) -> dict[str, Any]:
        """Deep dive: compare intersecting concessions with the supplier's declared holder and commodity.

        Args:
            polygon_id: Seed polygon identifier, for example PLY-001.
            supplier_id: Seed supplier identifier that owns the polygon, for example SUP-001.
        """
        record = context.datasets.record_for_polygon(polygon_id)
        if record.legality.supplier_id != supplier_id:
            payload: dict[str, Any] = {
                "polygon_id": polygon_id,
                "supplier_id": supplier_id,
                "error": f"polygon {polygon_id} does not belong to supplier {supplier_id}",
            }
        else:
            sources = await context.polygon_sources(polygon_id)
            payload = _concession_payload(
                polygon_id,
                supplier_id,
                sources,
                record.legality.declared_holder or record.legality.legal_name,
                record.consignment.commodity,
            )
            if sources.layers is None or payload["unavailable_layers"]:
                payload["error"] = "concession layers unavailable: " + (
                    "; ".join(sources.errors) or ", ".join(payload["unavailable_layers"])
                )
        context.trace.add(
            "tool",
            "check_concession_overlap",
            f"{polygon_id}/{supplier_id}: "
            + (
                payload["error"]
                if "error" in payload
                else f"{len(payload['concessions'])} concession layer(s)"
            ),
            payload={"polygon_id": polygon_id, "supplier_id": supplier_id, "status": _status(payload)},
        )
        return payload

    @tool
    async def search_adverse_media(supplier_id: str) -> dict[str, Any]:
        """Search public web reporting about a supplier for adverse media (context only).

        The result is background context with source URLs. It never changes the verdict or score.

        Args:
            supplier_id: Seed supplier identifier, for example SUP-001.
        """
        report = await context.adverse_media(supplier_id)
        if report is None:
            return {"supplier_id": supplier_id, "error": "adverse media search is not enabled"}
        payload = _media_payload(supplier_id, report)
        context.trace.add(
            "tool",
            "search_adverse_media",
            f"{supplier_id}: {len(report.findings)} cited finding(s)"
            if report.status == "success"
            else f"{supplier_id}: adverse media unavailable",
            payload={"supplier_id": supplier_id, "status": _status(payload), "report": payload["report"]},
        )
        return payload

    tools: list[AgentTool] = [
        get_tree_cover_loss,
        get_fire_hotspots,
        get_legality_record,
        get_consignment,
        get_context_layers,
        check_concession_overlap,
    ]
    if context.media is not None:
        tools.append(search_adverse_media)
    return tools


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
        loss = _loss_payload(polygon_id, sources)
        loss.pop("context_summary", None)
        return {
            "polygon_id": polygon_id,
            "loss": loss,
            "hotspots": _hotspot_payload(polygon_id, sources),
            "context_layers": _context_payload(sources),
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
                payload = entry.model_dump(mode="json")
                if entry.claim.startswith("context."):
                    payload["value"] = _layer_payload(ContextLayer.model_validate(entry.value))
                return payload
        return {"evidence_id": evidence_id, "error": "evidence id is not in the ledger"}

    return [get_source_claims, get_assessment, list_evidence_claims, get_evidence_entry]


__all__ = ["ToolContext", "build_source_tools", "build_verifier_tools"]
