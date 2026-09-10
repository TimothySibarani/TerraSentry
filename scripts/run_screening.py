"""End-to-end screening over the deterministic pipeline -- no AWS required.

This runs the whole dossier assembly without touching Bedrock, so the team can work on
tools, the rubric and the DDS output from day one, before hackathon accounts exist.

    python -m scripts.run_screening --supplier SUP-001
    python -m scripts.run_screening --supplier SUP-002 --json

What this is NOT: the agent. Here the sequence is hardcoded, including the adjacent-parcel
branch. The agent's contribution is *deciding* to take that branch. Keeping the two apart
matters -- when the Bedrock loop is wired up in ``agent/orchestrator.py``, it calls exactly
these same functions, and this script stays as the reference for what a correct run
produces. If the agent's output diverges from this, the agent is wrong.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rimba.dds import build as build_dds  # noqa: E402
from rimba.evidence import EvidenceLedger  # noqa: E402
from rimba.scoring import score as compute_score  # noqa: E402
from rimba.tools import geometry as geo  # noqa: E402
from rimba.tools.entity import EntityRegistry  # noqa: E402
from rimba.tools.forest_change import ForestChangeResult  # noqa: E402

DATA = Path("data")

# Loss touching a shared boundary cannot be attributed from geometry alone. Above this
# many hectares on a boundary, ownership of the neighbouring parcel becomes material --
# this is the trigger the agent learns to pull on its own.
BOUNDARY_LOSS_TRIGGER_HA = 5.0


def load_registry_payload() -> dict:
    return json.loads((DATA / "entities" / "suppliers.json").read_text(encoding="utf-8"))


def find_supplier(payload: dict, supplier_id: str) -> dict:
    for s in payload["suppliers"]:
        if s["supplier_id"] == supplier_id or s["legal_name"].lower() == supplier_id.lower():
            return s
    raise SystemExit(f"Unknown supplier: {supplier_id}")


def load_cached_forest_change(supplier_id: str) -> ForestChangeResult:
    raw = json.loads((DATA / "cache" / f"forest_change_{supplier_id}.json").read_text(encoding="utf-8"))
    return ForestChangeResult(
        polygon_area_ha=raw["polygon_area_ha"],
        tree_cover_2020_ha=raw["tree_cover_2020_ha"],
        loss_since_cutoff_ha=raw["loss_since_cutoff_ha"],
        loss_by_year=raw.get("loss_by_year", {}),
        canopy_threshold=raw.get("canopy_threshold_pct", 30),
        dataset=raw.get("dataset", "Hansen Global Forest Change"),
        backend="cache",
        notes=raw.get("notes", []),
    )


def load_cached_hotspots(supplier_id: str) -> dict:
    return json.loads((DATA / "cache" / f"hotspots_{supplier_id}.json").read_text(encoding="utf-8"))


def boundary_loss_ha(forest: ForestChangeResult) -> float:
    """Extract boundary-adjacent loss from the analysis notes.

    TODO(geospatial owner): once the raster pipeline is real, compute this properly --
    intersect the loss mask with a buffer inside the polygon edge and return the area.
    Parsing it out of a note is demo scaffolding, not a design.
    """
    for note in forest.notes:
        if "boundary" in note.lower():
            for token in note.replace("(", " ").replace(")", " ").split():
                try:
                    return float(token)
                except ValueError:
                    continue
    return 0.0


def run(supplier_id: str) -> dict:
    payload = load_registry_payload()
    supplier = find_supplier(payload, supplier_id)
    sid = supplier["supplier_id"]

    ledger = EvidenceLedger(supplier=supplier["legal_name"])
    registry = EntityRegistry(DATA / "entities" / "suppliers.json")

    # -- 1. geometry ------------------------------------------------------
    geom = geo.load_geojson(supplier["polygon"])
    report = geo.validate(geom)
    ledger.add(
        claim=(
            f"Plot area is {report.area_ha:,.1f} ha; EUDR Article 9 requires a "
            f"{report.geolocation_requirement}."
        ),
        source="RIMBA geometry tool (geodesic, WGS84)",
        artifact=report.to_dict(),
    )
    if report.blocking:
        print("BLOCKED -- geometry unusable:", *report.problems, sep="\n  ")
        return {"blocked": True, "problems": report.problems}

    # -- 2. forest change -------------------------------------------------
    forest = load_cached_forest_change(sid)
    ledger.add(
        claim=(
            f"{forest.loss_since_cutoff_ha:.1f} ha of tree cover lost since the "
            f"31 Dec 2020 cutoff ({forest.loss_share_of_plot * 100:.2f}% of the plot)."
        ),
        source=forest.dataset,
        artifact=forest.to_dict(),
        url="https://glad.earthengine.app/view/global-forest-change",
    )

    # -- 3. fire ----------------------------------------------------------
    hotspots = load_cached_hotspots(sid)
    inside = hotspots["inside"]
    ledger.add(
        claim=f"{inside['total']} fire hotspot(s) detected inside the plot, {inside['high_confidence']} high-confidence.",
        source="NASA FIRMS VIIRS_SNPP_SP",
        artifact=inside,
        url="https://firms.modaps.eosdis.nasa.gov/",
    )

    # -- 4. entity --------------------------------------------------------
    entity = registry.find_by_name(supplier["legal_name"])
    findings = registry.analyse(entity) if entity else []

    # -- 5. THE BRANCH ----------------------------------------------------
    # Not part of the standard plan. Triggered only because loss sits on a shared
    # boundary and cannot be attributed from geometry alone.
    edge_ha = boundary_loss_ha(forest)
    branch_taken = False
    if edge_ha >= BOUNDARY_LOSS_TRIGGER_HA and supplier.get("adjacent_parcels") and entity:
        branch_taken = True
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

    # -- 6. permit --------------------------------------------------------
    permit_number = supplier.get("permit_number", "")
    permit_record = payload.get("permits", {}).get(permit_number)
    permit_valid = bool(permit_record and permit_record.get("status") == "active")
    if permit_record:
        ledger.add(
            claim=f"Permit {permit_number} is recorded as {permit_record['status']}, valid to {permit_record['valid_to']}.",
            source=f"{registry.source_label} [permit record]",
            artifact={"permit_number": permit_number, **permit_record},
        )

    # -- 7. score (deterministic -- no model involved) --------------------
    assessment = compute_score(
        geometry=report,
        forest=forest,
        hotspot_summary=inside,
        entity_findings=findings,
        permit_valid=permit_valid,
    )

    # -- 8. DDS or gap list -----------------------------------------------
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

    return {
        "supplier": supplier["legal_name"],
        "supplier_id": sid,
        "geometry": report.to_dict(),
        "forest_change": forest.to_dict(),
        "hotspots": inside,
        "adjacent_parcel_branch_taken": branch_taken,
        "assessment": assessment.to_dict(),
        "assessment_explained": assessment.explain(),
        "dds": draft.to_dict(),
        "evidence_count": len(ledger),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a RIMBA screening over the demo dataset.")
    parser.add_argument("--supplier", required=True, help="Supplier id (e.g. SUP-001) or legal name.")
    parser.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    args = parser.parse_args()

    result = run(args.supplier)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if result.get("blocked"):
        return

    print(f"\n=== {result['supplier']} ({result['supplier_id']}) ===\n")
    print(result["assessment_explained"])
    print(f"\nEvidence items recorded: {result['evidence_count']}")
    print(f"Adjacent-parcel branch taken: {result['adjacent_parcel_branch_taken']}")

    dds = result["dds"]
    print(f"\nDDS issuable: {dds['issued']}")
    if dds["gaps"]:
        print("\nGaps the supplier must close:")
        for gap in dds["gaps"]:
            print(f"  [{gap['code']}] {gap['requirement']}")
            print(f"      why: {gap['why']}")
    print()


if __name__ == "__main__":
    main()
