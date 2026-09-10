"""Bedrock Converse tool specifications.

These schemas are what the model sees. They are documentation as much as validation:
a vague description here produces a confused agent, and no amount of prompt tuning
fixes it. Keep descriptions concrete about *when* to reach for each tool.
"""

from __future__ import annotations

from typing import Any


def _spec(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    return {
        "toolSpec": {
            "name": name,
            "description": description,
            "inputSchema": {
                "json": {"type": "object", "properties": properties, "required": required}
            },
        }
    }


VALIDATE_GEOMETRY = _spec(
    "validate_geometry",
    "Validate a supplier's production plot geometry and return its geodesic area, bounding box, "
    "and the EUDR Article 9 geolocation requirement (polygon for plots >= 4 ha, GPS point below). "
    "ALWAYS call this first. Every downstream analysis depends on the polygon being correct, and "
    "an invalid geometry is a blocking finding in its own right.",
    {
        "supplier_id": {"type": "string", "description": "Supplier identifier, e.g. 'SUP-001'."},
    },
    ["supplier_id"],
)

ANALYSE_FOREST_CHANGE = _spec(
    "analyse_forest_change",
    "Compute tree-cover loss inside the plot since the EUDR cutoff of 31 December 2020, using "
    "Hansen Global Forest Change data. Returns total loss in hectares, loss as a share of the plot, "
    "and a per-year breakdown. Call this after the geometry validates.",
    {
        "supplier_id": {"type": "string"},
        "canopy_threshold": {
            "type": "integer",
            "description": "Canopy density percent above which a pixel counts as forest. Default 30.",
        },
    },
    ["supplier_id"],
)

FETCH_HOTSPOTS = _spec(
    "fetch_hotspots",
    "Retrieve NASA FIRMS fire hotspot history for the plot and a surrounding buffer. Returns counts "
    "inside the plot, counts in the buffer only, and monthly clustering. Use the buffer result to "
    "distinguish fire that originated on the plot from fire that reached it from outside.",
    {
        "supplier_id": {"type": "string"},
        "years": {"type": "integer", "description": "Years of history to retrieve. Default 5."},
        "buffer_km": {"type": "number", "description": "Buffer around the plot in km. Default 2."},
    },
    ["supplier_id"],
)

LOOKUP_ENTITY = _spec(
    "lookup_entity",
    "Look up a supplier in the corporate registry and run ownership-structure heuristics: shared "
    "registered addresses, overlapping directors, and recent incorporation. Returns findings with "
    "severity levels. NOTE: this registry is synthetic demo data, not a live feed.",
    {
        "entity_name": {"type": "string", "description": "Legal name of the entity."},
    },
    ["entity_name"],
)

INVESTIGATE_ADJACENT_PARCEL = _spec(
    "investigate_adjacent_parcel",
    "Identify the registered owner of a parcel adjacent to the plot and run the same ownership "
    "heuristics against it. Call this when tree-cover loss sits on a shared boundary and you cannot "
    "attribute it from the geometry alone. This step is NOT part of the standard plan -- reach for "
    "it only when a boundary finding makes ownership of the neighbouring land material.",
    {
        "parcel_id": {"type": "string"},
        "supplier_entity_name": {"type": "string"},
    },
    ["parcel_id", "supplier_entity_name"],
)

VERIFY_PERMIT = _spec(
    "verify_permit",
    "Check a concession permit number against the permit records: existence, holder, and validity "
    "dates. Returns a tri-state result -- valid, invalid, or unverified. 'Unverified' is a real "
    "outcome and must not be reported as valid.",
    {
        "permit_number": {"type": "string"},
        "entity_name": {"type": "string"},
    },
    ["permit_number"],
)

COMPUTE_RISK_SCORE = _spec(
    "compute_risk_score",
    "Run the deterministic scoring rubric over everything gathered so far and return the score, "
    "the recommendation band, and the per-dimension breakdown. You MUST call this to obtain the "
    "score. Never state a score you did not receive from this tool.",
    {
        "supplier_id": {"type": "string"},
    },
    ["supplier_id"],
)

GENERATE_DDS = _spec(
    "generate_dds",
    "Assemble the TRACES-aligned Due Diligence Statement draft, or -- when the assessment does not "
    "support a negligible-risk conclusion -- the gap list describing what the supplier must provide. "
    "Call this last, after the score has been computed.",
    {
        "supplier_id": {"type": "string"},
        "commodity": {
            "type": "string",
            "enum": ["palm_oil", "timber", "rubber", "coffee", "cocoa", "soy", "cattle"],
        },
        "language": {"type": "string", "enum": ["id", "en"], "description": "Narrative language."},
    },
    ["supplier_id", "commodity"],
)


ALL_TOOLS: list[dict[str, Any]] = [
    VALIDATE_GEOMETRY,
    ANALYSE_FOREST_CHANGE,
    FETCH_HOTSPOTS,
    LOOKUP_ENTITY,
    INVESTIGATE_ADJACENT_PARCEL,
    VERIFY_PERMIT,
    COMPUTE_RISK_SCORE,
    GENERATE_DDS,
]
