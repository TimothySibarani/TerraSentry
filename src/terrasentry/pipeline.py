"""The screening pipeline, emitting steps as it goes.

Extracted out of ``scripts/run_screening.py`` so both the CLI and the web panel run
*exactly the same code*. If the panel ever shows something the CLI does not, that is a
bug, not a feature.

Every stage reports through an optional ``on_step`` callback, which is what makes the
live reasoning panel possible. The callback is fire-and-forget: the pipeline never waits
on it and never lets a slow consumer change the result.

Note on honesty: in this module the sequence is fixed, *including* the adjacent-parcel
branch, which fires on a rule (boundary loss above a threshold). When the Bedrock loop in
``agent/orchestrator.py`` is wired up, the model decides to take that branch instead of a
constant deciding for it. Until then, do not describe this as the agent reasoning -- it is
the reference pipeline the agent will be measured against.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from .dds import build as build_dds
from .evidence import EvidenceLedger
from .scoring import score as compute_score
from .tools import geometry as geo
from .tools.entity import EntityRegistry
from .tools.forest_change import ForestChangeResult

DATA = Path("data")

# Loss touching a shared boundary cannot be attributed from geometry alone. Above this
# many hectares, ownership of the neighbouring parcel becomes material.
BOUNDARY_LOSS_TRIGGER_HA = 5.0

StepFn = Callable[["Step"], None]


@dataclass
class Step:
    """One observable stage of a screening run."""

    index: int
    phase: str          # geometry | forest | fire | entity | branch | permit | score | dds
    title: str
    detail: str = ""
    status: str = "done"  # done | flag | blocked | info
    data: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _Emitter:
    """Emits steps and measures how long the *work* took.

    Time spent inside ``on_step`` is excluded from ``elapsed_ms``. The web panel paces
    its display by sleeping in that callback, and without this subtraction every step
    would report the pacing delay as if it were computation -- a number that is not just
    useless but actively misleading to anyone reading the panel.
    """

    def __init__(self, on_step: StepFn | None) -> None:
        self.on_step = on_step
        self.index = 0
        self.started = time.perf_counter()
        self.consumer_time = 0.0
        self.steps: list[Step] = []

    def emit(self, phase: str, title: str, detail: str = "", status: str = "done", **data: Any) -> Step:
        elapsed = time.perf_counter() - self.started - self.consumer_time
        step = Step(
            index=self.index,
            phase=phase,
            title=title,
            detail=detail,
            status=status,
            data=data,
            elapsed_ms=int(elapsed * 1000),
        )
        self.index += 1
        self.steps.append(step)
        if self.on_step is not None:
            consumer_start = time.perf_counter()
            try:
                self.on_step(step)
            except Exception:
                # A broken consumer must never break a screening.
                pass
            self.consumer_time += time.perf_counter() - consumer_start
        return step


# -- data access ----------------------------------------------------------


def load_registry_payload() -> dict:
    return json.loads((DATA / "entities" / "suppliers.json").read_text(encoding="utf-8"))


def list_suppliers() -> list[dict[str, Any]]:
    payload = load_registry_payload()
    return [
        {
            "supplier_id": s["supplier_id"],
            "legal_name": s["legal_name"],
            "commodity": s.get("commodity", ""),
            "country": s.get("country_of_production", ""),
        }
        for s in payload["suppliers"]
    ]


def find_supplier(payload: dict, supplier_id: str) -> dict:
    for s in payload["suppliers"]:
        if s["supplier_id"] == supplier_id or s["legal_name"].lower() == supplier_id.lower():
            return s
    raise KeyError(f"Unknown supplier: {supplier_id}")


def load_cached_forest_change(supplier_id: str) -> ForestChangeResult:
    raw = json.loads((DATA / "cache" / f"forest_change_{supplier_id}.json").read_text(encoding="utf-8"))
    return ForestChangeResult(
        polygon_area_ha=raw["polygon_area_ha"],
        tree_cover_2020_ha=raw["tree_cover_2020_ha"],
        loss_since_cutoff_ha=raw["loss_since_cutoff_ha"],
        loss_by_year=raw.get("loss_by_year", {}),
        boundary_loss_ha=raw.get("boundary_loss_ha", 0.0),
        interior_loss_ha=raw.get("interior_loss_ha", 0.0),
        boundary_adjoins_parcel=raw.get("boundary_adjoins_parcel"),
        canopy_threshold=raw.get("canopy_threshold_pct", 30),
        dataset=raw.get("dataset", "Hansen Global Forest Change"),
        backend="cache",
        notes=raw.get("notes", []),
    )


def load_cached_hotspots(supplier_id: str) -> dict:
    return json.loads((DATA / "cache" / f"hotspots_{supplier_id}.json").read_text(encoding="utf-8"))


def boundary_loss_ha(forest: ForestChangeResult) -> float:
    """Loss adjoining a shared boundary, in hectares.

    Reads a real field. This used to parse a float out of an English sentence in the
    analysis notes, which meant the entire adjacent-parcel branch -- the centrepiece of
    the pitch -- silently stopped firing if anyone reworded a note. Never make a
    load-bearing decision depend on prose.

    TODO(geospatial owner): populate this in the raster pipeline by intersecting the
    loss mask with an inward buffer of the polygon edge.
    """
    return forest.boundary_loss_ha


def _permit_state(permit_number: str, record: dict[str, Any] | None) -> bool | None:
    """Tri-state permit status.

    None means "could not verify", which is NOT the same as "verified invalid" and the
    rubric scores them differently -- an unverifiable permit is a gap to chase, a revoked
    one is a hard gate. Collapsing both to False (the old behaviour) made every supplier
    without a permit record look like a violation, and made "not checked yet" impossible
    to represent at all.
    """
    if not permit_number or record is None:
        return None
    return record.get("status") == "active"


def build_map_layers(supplier: dict[str, Any], geom, hotspots: dict[str, Any]) -> dict[str, Any]:
    """Assemble everything the map panel needs to draw the evidence.

    Returns plain GeoJSON and point lists -- no tiles, no projection, no styling. The
    renderer in ``web/map.js`` owns all of that, so this stays testable and the panel can
    be swapped without touching Python.

    Imagery is referenced by path, never fetched here. If a pre-rendered composite exists
    in ``data/cache/imagery/`` it is listed; if not, the map simply draws without it.
    Demo Day must never wait on a satellite scene download.
    """
    sid = supplier["supplier_id"]
    layers: dict[str, Any] = {
        "plot": geo.to_geojson_feature(geom, {"supplier_id": sid, "role": "plot"}),
        "adjacent": [],
        "hotspots_inside": hotspots.get("inside", {}).get("points", []),
        "hotspots_buffer": hotspots.get("buffer_only", {}).get("points", []),
        "imagery": [],
    }

    for parcel_id in supplier.get("adjacent_parcels") or []:
        path = DATA / "polygons" / f"{parcel_id}.geojson"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw.setdefault("properties", {})["role"] = "adjacent"
            layers["adjacent"].append(raw)

    manifest = DATA / "cache" / "imagery" / f"{sid}.json"
    if manifest.exists():
        layers["imagery"] = json.loads(manifest.read_text(encoding="utf-8")).get("scenes", [])

    return layers


# -- the pipeline ---------------------------------------------------------


def run(supplier_id: str, on_step: StepFn | None = None) -> dict[str, Any]:
    """Run a full screening. Returns the dossier; streams progress through ``on_step``."""
    emitter = _Emitter(on_step)

    payload = load_registry_payload()
    supplier = find_supplier(payload, supplier_id)
    sid = supplier["supplier_id"]

    ledger = EvidenceLedger(supplier=supplier["legal_name"])
    registry = EntityRegistry(DATA / "entities" / "suppliers.json")

    emitter.emit(
        "plan",
        "Screening plan prepared",
        f"Supplier {supplier['legal_name']} ({sid}), commodity {supplier.get('commodity')}. "
        f"Starting with geometry validation, which gates every later step.",
        supplier=supplier["legal_name"],
        supplier_id=sid,
    )

    # -- 1. geometry ------------------------------------------------------
    geom = geo.load_geojson(supplier["polygon"])
    report = geo.validate(geom)
    ledger.add(
        claim=(
            f"Plot area is {report.area_ha:,.1f} ha; EUDR Article 9 requires a "
            f"{report.geolocation_requirement}."
        ),
        source="TerraSentry geometry tool (geodesic, WGS84)",
        artifact=report.to_dict(),
    )
    if report.blocking:
        emitter.emit(
            "geometry",
            "Geometry unusable -- assessment blocked",
            "; ".join(report.problems),
            status="blocked",
            **report.to_dict(),
        )
        # Return the SAME keys as a completed run, with explicit nulls. A caller that
        # has to guess which keys exist will guess wrong -- the panel did exactly that
        # and left its placeholders up, so a blocked supplier looked like a hung request.
        return {
            "blocked": True,
            "supplier": supplier["legal_name"],
            "supplier_id": sid,
            "problems": report.problems,
            "geometry": report.to_dict(),
            "geojson": None,
            "map": None,
            "forest_change": None,
            "hotspots": None,
            "adjacent_parcel_branch_taken": False,
            "assessment": None,
            "assessment_explained": "BLOCKED -- geometry unusable, no score computed.",
            "dds": None,
            "required_action": (
                "Request a valid WGS84 GeoJSON polygon from the supplier before any "
                "further assessment. Coordinates are commonly transposed (GeoJSON is "
                "lon,lat, not lat,lon)."
            ),
            "evidence": ledger.to_dict(),
            "evidence_count": len(ledger),
            "steps": [s.to_dict() for s in emitter.steps],
        }

    emitter.emit(
        "geometry",
        f"Geometry valid -- {report.area_ha:,.0f} ha",
        f"Above the 4 ha threshold, so EUDR Article 9 requires a {report.geolocation_requirement}, "
        f"not a GPS point.",
        **report.to_dict(),
    )

    # -- 2. forest change -------------------------------------------------
    forest = load_cached_forest_change(sid)
    ledger.add(
        claim=(
            f"{forest.loss_since_cutoff_ha:.1f} ha of tree cover lost since the "
            f"31 Dec 2020 cutoff ({forest.loss_share_of_plot * 100:.2f}% of the plot)."
        ),
        source=forest.dataset,
        artifact=forest.to_dict(),
        url="https://www.globalforestwatch.org/",
    )
    emitter.emit(
        "forest",
        (
            "No post-cutoff tree-cover loss detected"
            if forest.is_deforestation_free
            else f"{forest.loss_since_cutoff_ha:.1f} ha lost since 31 Dec 2020"
        ),
        " ".join(forest.notes) or f"Canopy threshold {forest.canopy_threshold}%.",
        status="done" if forest.is_deforestation_free else "flag",
        **forest.to_dict(),
    )

    # -- 3. fire ----------------------------------------------------------
    hotspots = load_cached_hotspots(sid)
    inside = hotspots["inside"]
    buffer_only = hotspots.get("buffer_only", {})
    ledger.add(
        claim=f"{inside['total']} fire hotspot(s) detected inside the plot, {inside['high_confidence']} high-confidence.",
        source="NASA FIRMS VIIRS_SNPP_SP",
        artifact=inside,
        url="https://firms.modaps.eosdis.nasa.gov/",
    )
    peak = inside.get("peak_month")
    emitter.emit(
        "fire",
        f"{inside['total']} hotspot(s) inside the plot",
        (
            f"{inside['high_confidence']} high-confidence. Peak {peak['month']} with {peak['count']} "
            f"detections, plus {buffer_only.get('total', 0)} in the surrounding buffer."
            if peak
            else "No clustering detected in the review period."
        ),
        status="flag" if inside["total"] > 0 else "done",
        inside=inside,
        buffer_only=buffer_only,
    )

    # -- 4. entity --------------------------------------------------------
    entity = registry.find_by_name(supplier["legal_name"])
    findings = registry.analyse(entity) if entity else []
    emitter.emit(
        "entity",
        (
            f"{len(findings)} ownership-structure signal(s)"
            if findings
            else "No ownership-structure anomalies"
        ),
        "; ".join(f.statement for f in findings) or "Registered address and directorships are unremarkable.",
        status="flag" if findings else "done",
        findings=[f.to_dict() for f in findings],
        registry_note=registry.source_label,
    )

    # -- 5. THE BRANCH ----------------------------------------------------
    edge_ha = boundary_loss_ha(forest)
    branch_taken = False
    if edge_ha >= BOUNDARY_LOSS_TRIGGER_HA and supplier.get("adjacent_parcels") and entity:
        branch_taken = True
        emitter.emit(
            "branch",
            f"Unplanned step: {edge_ha:.1f} ha of loss sits on a shared boundary",
            "Geometry alone cannot attribute this loss. Ownership of the adjoining parcel "
            "becomes material, so the investigation widens beyond the original plan.",
            status="flag",
            boundary_loss_ha=edge_ha,
            trigger_threshold_ha=BOUNDARY_LOSS_TRIGGER_HA,
        )
        for parcel_id in supplier["adjacent_parcels"]:
            extra = registry.investigate_adjacent_parcel(parcel_id, entity)
            findings.extend(extra)
            for f in extra:
                if f.severity != "info":
                    ledger.add(
                        claim=f.statement,
                        source=f"{registry.source_label} [heuristic {f.code}]",
                        artifact=f.artifact,
                    )
            high = [f for f in extra if f.severity == "high"]
            emitter.emit(
                "branch",
                f"Adjacent parcel {parcel_id} investigated",
                (high[0].statement if high else "; ".join(f.statement for f in extra)),
                status="flag" if high else "info",
                parcel_id=parcel_id,
                findings=[f.to_dict() for f in extra],
            )

    # -- 6. permit --------------------------------------------------------
    permit_number = supplier.get("permit_number", "")
    permit_record = payload.get("permits", {}).get(permit_number)
    permit_valid = _permit_state(permit_number, permit_record)
    if permit_record:
        ledger.add(
            claim=f"Permit {permit_number} is recorded as {permit_record['status']}, valid to {permit_record['valid_to']}.",
            source=f"{registry.source_label} [permit record]",
            artifact={"permit_number": permit_number, **permit_record},
        )
    emitter.emit(
        "permit",
        f"Permit {permit_number or 'not supplied'}: "
        f"{'valid' if permit_valid else ('invalid' if permit_valid is False else 'not verified')}",
        (
            f"Holder {permit_record['holder']}, valid to {permit_record['valid_to']}."
            if permit_record
            else "No matching permit record found. 'Unverified' is not the same as 'clean'."
        ),
        status="done" if permit_valid else "flag",
        permit_number=permit_number,
        record=permit_record,
    )

    # -- 7. score ---------------------------------------------------------
    assessment = compute_score(
        geometry=report,
        forest=forest,
        hotspot_summary=inside,
        entity_findings=findings,
        permit_valid=permit_valid,
    )
    emitter.emit(
        "score",
        f"Score {assessment.score:.1f}/100 -- {assessment.recommendation.value}",
        "Computed by the deterministic rubric. No model involved in this number.",
        status="flag" if assessment.recommendation.value != "GO" else "done",
        **assessment.to_dict(),
    )

    # -- 8. DDS -----------------------------------------------------------
    draft = build_dds(
        supplier_name=supplier["legal_name"],
        operator={"name": "<EU operator placing goods on the market>", "eori": None},
        commodity=supplier.get("commodity", "timber"),
        geometry_feature=geo.to_geojson_feature(geom, {"supplier_id": sid}),
        geometry_requirement=report.geolocation_requirement,
        area_ha=report.area_ha,
        country_of_production=supplier.get("country_of_production", "ID"),
        assessment=assessment,
        ledger=ledger,
    )
    emitter.emit(
        "dds",
        "DDS draft issued" if draft.issued else f"DDS not issuable -- {len(draft.gaps)} gap(s) to close",
        (
            "Negligible-risk conclusion supported by the evidence gathered."
            if draft.issued
            else "The output is a request list procurement can act on, not a rejection letter."
        ),
        status="done" if draft.issued else "flag",
        issued=draft.issued,
        gaps=[g.to_dict() for g in draft.gaps],
    )

    return {
        "blocked": False,
        "supplier": supplier["legal_name"],
        "supplier_id": sid,
        "geometry": report.to_dict(),
        "geojson": geo.to_geojson_feature(geom, {"supplier_id": sid}),
        "map": build_map_layers(supplier, geom, hotspots),
        "forest_change": forest.to_dict(),
        "hotspots": inside,
        "adjacent_parcel_branch_taken": branch_taken,
        "assessment": assessment.to_dict(),
        "assessment_explained": assessment.explain(),
        "dds": draft.to_dict(),
        "evidence": ledger.to_dict(),
        "evidence_count": len(ledger),
        "steps": [s.to_dict() for s in emitter.steps],
    }
