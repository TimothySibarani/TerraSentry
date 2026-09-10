"""The evidence ledger: every claim carries a source, an artifact, and a time.

Determinism rules:

- Ids are content hashes, so recording the same claim twice is idempotent and two
  runs over the same inputs produce the same ids.
- No wall clock is read here. Timestamps come from the source results
  (``fetched_at``) or from a caller-supplied fallback such as the reference run's
  ``started_at``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from terrasentry_core.domain.enums import EvidenceSource
from terrasentry_core.domain.models import AssessmentInput
from terrasentry_core.errors import LedgerLookupError

_RECORD_SCHEMA_VERSION = 1


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


class EvidenceEntry(BaseModel):
    """One auditable claim backing a score, a DDS field, or a narrative sentence."""

    schema_version: int = _RECORD_SCHEMA_VERSION
    evidence_id: str
    claim: str
    value: Any
    unit: str | None = None
    source: EvidenceSource
    artifact: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime | None = None
    synthetic: bool = False
    disclosure: str | None = None


class EvidenceLedger:
    """In-memory ledger; persistence to Postgres arrives with M4."""

    def __init__(self) -> None:
        self._entries: dict[str, EvidenceEntry] = {}

    def record(
        self,
        *,
        claim: str,
        value: Any,
        source: EvidenceSource,
        artifact: Mapping[str, Any] | None = None,
        unit: str | None = None,
        retrieved_at: datetime | None = None,
        synthetic: bool = False,
        disclosure: str | None = None,
    ) -> EvidenceEntry:
        artifact_dict = dict(artifact or {})
        digest = hashlib.sha256(
            _canonical(
                {
                    "claim": claim,
                    "value": value,
                    "unit": unit,
                    "source": str(source),
                    "artifact": artifact_dict,
                }
            ).encode("utf-8")
        ).hexdigest()
        evidence_id = f"EV-{source.value}-{digest[:12]}"
        existing = self._entries.get(evidence_id)
        if existing is not None:
            return existing
        entry = EvidenceEntry(
            evidence_id=evidence_id,
            claim=claim,
            value=value,
            unit=unit,
            source=source,
            artifact=artifact_dict,
            retrieved_at=retrieved_at,
            synthetic=synthetic,
            disclosure=disclosure,
        )
        self._entries[evidence_id] = entry
        return entry

    def get(self, evidence_id: str) -> EvidenceEntry:
        try:
            return self._entries[evidence_id]
        except KeyError as exc:
            raise LedgerLookupError(evidence_id) from exc

    def by_claim(self, claim: str) -> list[EvidenceEntry]:
        return [entry for entry in self.entries if entry.claim == claim]

    def ids_for(self, claim: str) -> list[str]:
        return [entry.evidence_id for entry in self.by_claim(claim)]

    @property
    def entries(self) -> list[EvidenceEntry]:
        return sorted(self._entries.values(), key=lambda entry: entry.evidence_id)

    def verify(self, citations: Mapping[str, Iterable[str]]) -> None:
        """Raise if any cited id is missing from the ledger."""
        for ids in citations.values():
            for evidence_id in ids:
                self.get(evidence_id)

    def snapshot(self) -> list[dict[str, Any]]:
        return [entry.model_dump(mode="json") for entry in self.entries]


def _loss_claim_value(input: AssessmentInput) -> dict[str, Any] | None:
    loss = input.loss
    if loss is None:
        return None
    return {
        "total_loss_ha": loss.total_loss_ha,
        "start_year": loss.start_year,
        "end_year": loss.end_year,
        "date_window": loss.date_window,
    }


def _hotspot_claim_value(input: AssessmentInput) -> dict[str, Any] | None:
    hotspots = input.hotspots
    if hotspots is None:
        return None
    return {
        "detection_count": hotspots.detection_count,
        "total_frp": hotspots.total_frp,
        "date_window": hotspots.date_window,
    }


def build_source_ledger(
    input: AssessmentInput,
    *,
    retrieved_at: datetime | None = None,
) -> EvidenceLedger:
    """Record every source-derived claim for one assessment input.

    ``retrieved_at`` is the deterministic fallback timestamp for synthetic seed
    claims (the real source claims use each result's own ``fetched_at``).
    """
    ledger = EvidenceLedger()
    parcel = input.parcel
    ledger.record(
        claim="parcel.geometry",
        value=parcel.geometry,
        source=EvidenceSource.CONCESSION,
        artifact={"polygon_id": parcel.polygon_id, "region": parcel.region},
        unit="geojson",
        synthetic=True,
        retrieved_at=retrieved_at,
    )
    ledger.record(
        claim="parcel.area_ha",
        value=parcel.area_ha,
        source=EvidenceSource.CONCESSION,
        artifact={"polygon_id": parcel.polygon_id},
        unit="ha",
        synthetic=True,
        retrieved_at=retrieved_at,
    )
    ledger.record(
        claim="parcel.centroid",
        value=[parcel.centroid_lon, parcel.centroid_lat],
        source=EvidenceSource.CONCESSION,
        artifact={"polygon_id": parcel.polygon_id},
        synthetic=True,
        retrieved_at=retrieved_at,
    )
    ledger.record(
        claim="parcel.country",
        value="ID",
        source=EvidenceSource.CONCESSION,
        artifact={"polygon_id": parcel.polygon_id, "province": parcel.province},
        synthetic=True,
        retrieved_at=retrieved_at,
    )

    loss = input.loss
    if loss is not None:
        for claim, value, unit in (
            ("loss.total_loss_ha", _loss_claim_value(input), "ha"),
            ("loss.by_year", [item.model_dump(mode="json") for item in loss.by_year], None),
        ):
            ledger.record(
                claim=claim,
                value=value,
                source=EvidenceSource.GFW,
                artifact={
                    "dataset": loss.dataset,
                    "version": loss.version,
                    "geometry_hash": loss.geometry_hash,
                    "date_window": loss.date_window,
                    "cached": loss.cached,
                },
                unit=unit,
                retrieved_at=loss.fetched_at,
            )

    hotspots = input.hotspots
    if hotspots is not None:
        for claim, value, unit in (
            ("hotspots.detection_count", _hotspot_claim_value(input), "count"),
            ("hotspots.total_frp", hotspots.total_frp, "MW"),
            (
                "hotspots.detections",
                [item.model_dump(mode="json") for item in hotspots.detections],
                None,
            ),
        ):
            ledger.record(
                claim=claim,
                value=value,
                source=EvidenceSource.FIRMS,
                artifact={
                    "source": hotspots.source,
                    "geometry_hash": hotspots.geometry_hash,
                    "date_window": hotspots.date_window,
                    "cached": hotspots.cached,
                },
                unit=unit,
                retrieved_at=hotspots.fetched_at,
            )

    supplier = input.supplier
    for claim, value, unit, artifact in (
        ("supplier.identifiers", [supplier.nib, supplier.npwp], None, {}),
        ("supplier.name", supplier.legal_name, None, {}),
        ("supplier.permit_status", supplier.permit_status, None, {}),
        ("supplier.concession_area_ha", supplier.concession_area_ha, "ha", {}),
        (
            "supplier.hgu_pbp",
            {"hgu_number": supplier.hgu_number, "pbp_number": supplier.pbp_number},
            None,
            {},
        ),
        ("supplier.sanctions", supplier.sanctions, None, {}),
        ("supplier.certifications", supplier.certifications, None, {}),
        ("supplier.beneficial_owners", supplier.beneficial_owners, None, {}),
    ):
        ledger.record(
            claim=claim,
            value=value,
            source=EvidenceSource.LEGALITY,
            artifact={"supplier_id": supplier.supplier_id, "synthetic": supplier.synthetic, **artifact},
            unit=unit,
            retrieved_at=retrieved_at,
            synthetic=supplier.synthetic,
            disclosure=supplier.disclosure,
        )

    consignment = input.consignment
    if consignment is not None:
        for claim, value, unit in (
            ("consignment.description", consignment.description, None),
            ("consignment.hs_heading", consignment.hs_heading, None),
            ("consignment.net_weight_kg", consignment.net_weight_kg, "kg"),
            (
                "consignment.measure",
                {
                    "net_weight_kg": consignment.net_weight_kg,
                    "supplementary_unit": consignment.supplementary_unit,
                    "supplementary_unit_qualifier": consignment.supplementary_unit_qualifier,
                },
                None,
            ),
            (
                "consignment.species",
                {
                    "scientific_name": consignment.species_scientific,
                    "common_name": consignment.species_common,
                },
                None,
            ),
            ("consignment.production_place", consignment.production_place, None),
            ("consignment.harvest_year", consignment.harvest_year, None),
        ):
            ledger.record(
                claim=claim,
                value=value,
                source=EvidenceSource.CONSIGNMENT,
                artifact={"supplier_id": consignment.supplier_id},
                unit=unit,
                retrieved_at=retrieved_at,
                synthetic=True,
            )

    operator = input.operator
    if operator is not None:
        for claim, value in (
            ("operator.name", operator.legal_name),
            ("operator.identifier", f"{operator.identifier_type}:{operator.identifier_value}"),
            (
                "operator.address",
                f"{operator.address_line}, {operator.postal_code} {operator.city}, {operator.country}",
            ),
            (
                "operator.activity",
                {
                    "activity_type": operator.activity_type,
                    "country_of_activity": operator.country_of_activity,
                    "border_cross_country": operator.border_cross_country,
                },
            ),
            ("operator.contact", {"email": operator.email, "phone": operator.phone}),
        ):
            ledger.record(
                claim=claim,
                value=value,
                source=EvidenceSource.OPERATOR,
                artifact={"operator_id": operator.operator_id},
                retrieved_at=retrieved_at,
                synthetic=operator.synthetic,
                disclosure=operator.disclosure,
            )
    return ledger
