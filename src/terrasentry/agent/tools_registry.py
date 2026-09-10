"""Binds the tool schemas in ``toolspec.py`` to real functions.

This is the piece that was missing: ``toolspec.py`` describes eight tools to the model,
and ``Orchestrator`` expects ``{name: callable}`` -- but nothing built that mapping, so
the whole ``agent/`` package was unreachable code.

A :class:`ScreeningSession` holds the state one screening accumulates (supplier context,
evidence ledger, findings so far) and exposes bound methods as tools. State lives here
rather than in the orchestrator because the model must be free to call tools in any
order, skip some, and repeat others -- the session tolerates all of that and simply
reports what has and has not been established.

Every tool returns a plain JSON-serialisable dict. Anything a tool learns that belongs in
the dossier is written to the ledger *by the tool*, not by the model, so a claim exists
only if a tool actually observed it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..dds import build as build_dds
from ..evidence import EvidenceLedger
from ..pipeline import (
    _permit_state,
    DATA,
    find_supplier,
    load_cached_forest_change,
    load_cached_hotspots,
    load_registry_payload,
)
from ..scoring import score as compute_score
from ..tools import geometry as geo
from ..tools.entity import EntityFinding, EntityRegistry


class ScreeningSession:
    """One supplier, one screening, one ledger."""

    def __init__(self, supplier_id: str) -> None:
        self.payload = load_registry_payload()
        self.supplier = find_supplier(self.payload, supplier_id)
        self.supplier_id = self.supplier["supplier_id"]
        self.registry = EntityRegistry(DATA / "entities" / "suppliers.json")
        self.ledger = EvidenceLedger(supplier=self.supplier["legal_name"])

        # Established as tools run. None means "not yet checked", which the rubric
        # deliberately scores worse than "checked and clean".
        self.geometry: geo.GeometryReport | None = None
        self.geom = None
        self.forest = None
        self.hotspots: dict[str, Any] | None = None
        self.findings: list[EntityFinding] = []
        self.permit_valid: bool | None = None
        self.assessment = None

    # -- tools ------------------------------------------------------------

    def validate_geometry(self, supplier_id: str | None = None) -> dict[str, Any]:
        self.geom = geo.load_geojson(self.supplier["polygon"])
        self.geometry = geo.validate(self.geom)
        self.ledger.add(
            claim=(
                f"Plot area is {self.geometry.area_ha:,.1f} ha; EUDR Article 9 requires a "
                f"{self.geometry.geolocation_requirement}."
            ),
            source="TerraSentry geometry tool (geodesic, WGS84)",
            artifact=self.geometry.to_dict(),
        )
        return self.geometry.to_dict()

    def analyse_forest_change(
        self, supplier_id: str | None = None, canopy_threshold: int = 30
    ) -> dict[str, Any]:
        self.forest = load_cached_forest_change(self.supplier_id)
        self.ledger.add(
            claim=(
                f"{self.forest.loss_since_cutoff_ha:.1f} ha of tree cover lost since the "
                f"31 Dec 2020 cutoff ({self.forest.loss_share_of_plot * 100:.2f}% of the plot)."
            ),
            source=self.forest.dataset,
            artifact=self.forest.to_dict(),
            url="https://www.globalforestwatch.org/",
        )
        out = self.forest.to_dict()
        # Surface the attribution problem explicitly. The model should not have to infer
        # from prose that boundary loss is ambiguous -- say it in the tool result.
        if self.forest.boundary_loss_ha > 0:
            out["attribution_note"] = (
                f"{self.forest.boundary_loss_ha:.1f} ha of the loss adjoins a shared boundary "
                f"with parcel {self.forest.boundary_adjoins_parcel}. Geometry alone cannot "
                f"attribute it to this supplier."
            )
        return out

    def fetch_hotspots(
        self, supplier_id: str | None = None, years: int = 5, buffer_km: float = 2.0
    ) -> dict[str, Any]:
        payload = load_cached_hotspots(self.supplier_id)
        self.hotspots = payload["inside"]
        self.ledger.add(
            claim=(
                f"{self.hotspots['total']} fire hotspot(s) detected inside the plot, "
                f"{self.hotspots['high_confidence']} high-confidence."
            ),
            source="NASA FIRMS VIIRS_SNPP_SP",
            artifact=self.hotspots,
            url="https://firms.modaps.eosdis.nasa.gov/",
        )
        return payload

    def lookup_entity(self, entity_name: str) -> dict[str, Any]:
        entity = self.registry.find_by_name(entity_name)
        if entity is None:
            return {"found": False, "entity_name": entity_name}
        found = self.registry.analyse(entity)
        self._record(found)
        return {
            "found": True,
            "entity": entity.to_dict(),
            "findings": [f.to_dict() for f in found],
            "registry_note": self.registry.source_label,
        }

    def investigate_adjacent_parcel(self, parcel_id: str, supplier_entity_name: str) -> dict[str, Any]:
        entity = self.registry.find_by_name(supplier_entity_name)
        if entity is None:
            return {"error": f"Supplier entity not found: {supplier_entity_name}"}
        found = self.registry.investigate_adjacent_parcel(parcel_id, entity)
        self._record(found)
        return {
            "parcel_id": parcel_id,
            "findings": [f.to_dict() for f in found],
            "registry_note": self.registry.source_label,
        }

    def verify_permit(self, permit_number: str, entity_name: str | None = None) -> dict[str, Any]:
        record = self.payload.get("permits", {}).get(permit_number)
        self.permit_valid = _permit_state(permit_number, record)
        if record:
            self.ledger.add(
                claim=(
                    f"Permit {permit_number} is recorded as {record['status']}, "
                    f"valid to {record['valid_to']}."
                ),
                source=f"{self.registry.source_label} [permit record]",
                artifact={"permit_number": permit_number, **record},
            )
        return {
            "permit_number": permit_number,
            "status": ("valid" if self.permit_valid else
                       "invalid" if self.permit_valid is False else "unverified"),
            "record": record,
        }

    def compute_risk_score(self, supplier_id: str | None = None) -> dict[str, Any]:
        if self.geometry is None:
            return {"error": "Geometry has not been validated yet. Call validate_geometry first."}
        self.assessment = compute_score(
            geometry=self.geometry,
            forest=self.forest,
            hotspot_summary=self.hotspots,
            entity_findings=self.findings,
            permit_valid=self.permit_valid,
        )
        return self.assessment.to_dict()

    def generate_dds(
        self, supplier_id: str | None = None, commodity: str = "timber", language: str = "en"
    ) -> dict[str, Any]:
        if self.assessment is None:
            return {"error": "No risk score yet. Call compute_risk_score first."}
        draft = build_dds(
            supplier_name=self.supplier["legal_name"],
            operator={"name": "<EU operator placing goods on the market>", "eori": None},
            commodity=commodity,
            geometry_feature=geo.to_geojson_feature(self.geom, {"supplier_id": self.supplier_id}),
            geometry_requirement=self.geometry.geolocation_requirement,
            area_ha=self.geometry.area_ha,
            country_of_production=self.supplier.get("country_of_production", "ID"),
            assessment=self.assessment,
            ledger=self.ledger,
        )
        return {
            "issued": draft.issued,
            "gaps": [g.to_dict() for g in draft.gaps],
            "statement_preview": {
                k: draft.payload[k] for k in ("supplier", "commodity", "geolocation", "risk_assessment")
            },
        }

    # -- helpers ----------------------------------------------------------

    def _record(self, found: list[EntityFinding]) -> None:
        """Accumulate findings and write the non-trivial ones to the ledger."""
        for f in found:
            if any(
                existing.code == f.code and existing.statement == f.statement
                for existing in self.findings
            ):
                continue  # the model may call a tool twice; do not double-count
            self.findings.append(f)
            if f.severity != "info":
                self.ledger.add(
                    claim=f.statement,
                    source=f"{self.registry.source_label} [heuristic {f.code}]",
                    artifact=f.artifact,
                )

    def build(self) -> dict[str, Callable[..., dict[str, Any]]]:
        """The mapping ``Orchestrator`` needs. Names must match ``toolspec.py`` exactly."""
        return {
            "validate_geometry": self.validate_geometry,
            "analyse_forest_change": self.analyse_forest_change,
            "fetch_hotspots": self.fetch_hotspots,
            "lookup_entity": self.lookup_entity,
            "investigate_adjacent_parcel": self.investigate_adjacent_parcel,
            "verify_permit": self.verify_permit,
            "compute_risk_score": self.compute_risk_score,
            "generate_dds": self.generate_dds,
        }

    def task_prompt(self) -> str:
        """The opening instruction handed to the model."""
        s = self.supplier
        return (
            f"Assess this candidate supplier for EUDR compliance before contracting.\n\n"
            f"  supplier_id : {s['supplier_id']}\n"
            f"  legal name  : {s['legal_name']}\n"
            f"  commodity   : {s.get('commodity')}\n"
            f"  permit      : {s.get('permit_number')}\n"
            f"  country     : {s.get('country_of_production')}\n"
            f"  adjacent parcels on record: {', '.join(s.get('adjacent_parcels') or []) or 'none'}\n\n"
            f"Work through the tools, decide when the evidence is sufficient, and finish with an "
            f"assessment a procurement officer can act on."
        )
