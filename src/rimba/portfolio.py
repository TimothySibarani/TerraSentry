"""Portfolio screening: the whole supply base in one pass.

Nobody reviews suppliers one at a time. A mill with hundreds of smallholders needs the
opposite of a detail page -- it needs *management by exception*: screen everything, show
the aggregate, and put a human only on what is actually stuck.

So this module screens every supplier with the deterministic pipeline and returns three
things: totals, a band distribution, and an exception queue. The single-supplier panel
becomes the drill-down, reached by clicking a row -- not the home screen.

**Cost note, and the reason this design matters beyond the UI.** The deterministic
pipeline is free and takes milliseconds, so running it across the entire base nightly
costs nothing. The LLM agent is neither. Screen everything here; escalate only the
ambiguous cases to the agent. On this cohort that is 23 rubric runs and roughly 4 agent
runs -- and the same ratio is what makes 500 suppliers affordable rather than ruinous.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import pipeline

# Bands that put a supplier in the work queue. CONDITIONAL is deliberately not here:
# it needs a document chased, not a decision made, and mixing the two buries the
# handful of cases that genuinely need judgement.
EXCEPTION_BANDS = {"ESCALATE", "NO_GO", "BLOCKED"}

# Only GO volume counts as covered. "Conditional" means the statement is not issuable yet.
COVERED_BANDS = {"GO"}

BAND_ORDER = ["GO", "CONDITIONAL", "ESCALATE", "NO_GO", "BLOCKED"]
_SEVERITY = {b: i for i, b in enumerate(BAND_ORDER)}


def _top_reason(result: dict[str, Any]) -> str:
    """One line saying why this supplier is not clean, for the queue."""
    if result.get("blocked"):
        return "; ".join(result.get("problems", [])) or "Geometry unusable"

    assessment = result["assessment"]
    if assessment["hard_gates"]:
        return assessment["hard_gates"][0]

    worst = max(assessment["components"], key=lambda c: c["penalty"], default=None)
    if worst and worst["penalty"] > 0 and worst["reasons"]:
        return worst["reasons"][0]
    return "No findings"


def _action(result: dict[str, Any]) -> str:
    """What a human would actually do next."""
    if result.get("blocked"):
        return "Request a valid WGS84 polygon from the supplier"
    gaps = (result.get("dds") or {}).get("gaps", [])
    if gaps:
        return gaps[0]["requirement"]
    return "None"


def screen_all() -> dict[str, Any]:
    """Screen every supplier and assemble the portfolio view."""
    payload = pipeline.load_registry_payload()
    aggregators = {a["id"]: a for a in payload.get("aggregators", [])}
    by_id = {s["supplier_id"]: s for s in payload["suppliers"]}

    rows: list[dict[str, Any]] = []
    bands: dict[str, int] = {b: 0 for b in BAND_ORDER}

    for supplier_id, supplier in by_id.items():
        try:
            result = pipeline.run(supplier_id)
        except Exception as exc:
            # One bad record must not take down the whole portfolio -- surface it as a row.
            rows.append({
                "supplier_id": supplier_id,
                "legal_name": supplier.get("legal_name", supplier_id),
                "band": "BLOCKED", "score": None, "error": f"{type(exc).__name__}: {exc}",
                "reason": "Screening failed", "action": "Investigate the supplier record",
                "tier": supplier.get("tier"), "aggregator": supplier.get("aggregator"),
                "area_ha": None, "volume_m3_month": supplier.get("volume_m3_month", 0),
                "geolocation_requirement": None,
            })
            bands["BLOCKED"] += 1
            continue

        band = "BLOCKED" if result.get("blocked") else result["assessment"]["recommendation"]
        bands[band] = bands.get(band, 0) + 1
        geometry = result.get("geometry") or {}

        rows.append({
            "supplier_id": supplier_id,
            "legal_name": supplier["legal_name"],
            "band": band,
            "score": None if result.get("blocked") else result["assessment"]["score"],
            "reason": _top_reason(result),
            "action": _action(result),
            "tier": supplier.get("tier", "concession"),
            "aggregator": supplier.get("aggregator"),
            "area_ha": geometry.get("area_ha"),
            "geolocation_requirement": geometry.get("geolocation_requirement"),
            "volume_m3_month": supplier.get("volume_m3_month", 0),
            "gap_codes": [g["code"] for g in (result.get("dds") or {}).get("gaps", [])],
        })

    rows.sort(key=lambda r: (-_SEVERITY.get(r["band"], 0), r["score"] if r["score"] is not None else -1))

    total_volume = sum(r["volume_m3_month"] for r in rows) or 1
    covered_volume = sum(r["volume_m3_month"] for r in rows if r["band"] in COVERED_BANDS)
    exceptions = [r for r in rows if r["band"] in EXCEPTION_BANDS]

    # Group by aggregator so a cooperative's whole cohort can be judged together --
    # smallholders do not contract with a mill directly, and a problem is often shared
    # across everyone a single collector supplies.
    groups: list[dict[str, Any]] = []
    for gid, agg in aggregators.items():
        members = [r for r in rows if r["aggregator"] == gid]
        if not members:
            continue
        groups.append({
            **agg,
            "supplier_count": len(members),
            "volume_m3_month": sum(m["volume_m3_month"] for m in members),
            "worst_band": max((m["band"] for m in members), key=lambda b: _SEVERITY.get(b, 0)),
            "exceptions": sum(1 for m in members if m["band"] in EXCEPTION_BANDS),
            "suppliers": members,
        })
    direct = [r for r in rows if not r["aggregator"]]
    if direct:
        groups.insert(0, {
            "id": "DIRECT", "name": "Direct concession suppliers", "type": "direct",
            "region": "-", "supplier_count": len(direct),
            "volume_m3_month": sum(m["volume_m3_month"] for m in direct),
            "worst_band": max((m["band"] for m in direct), key=lambda b: _SEVERITY.get(b, 0)),
            "exceptions": sum(1 for m in direct if m["band"] in EXCEPTION_BANDS),
            "suppliers": direct,
        })

    # Plots below 4 ha take the GPS-point route under Article 9, not a polygon. In an
    # Indonesian supply base that is most of the tail, and it is worth showing on the
    # dashboard rather than discovering during an audit.
    point_rule = sum(1 for r in rows if r["geolocation_requirement"] == "point")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mill": payload.get("mill", {}),
        "totals": {
            "suppliers": len(rows),
            "screened": len(rows),
            "coverage_pct": 100.0,
            "exceptions": len(exceptions),
            "needs_documents": bands.get("CONDITIONAL", 0),
            "volume_m3_month": sum(r["volume_m3_month"] for r in rows),
            "volume_covered_pct": round(covered_volume / total_volume * 100, 1),
            "smallholders": sum(1 for r in rows if r["tier"] == "smallholder"),
            "point_rule_plots": point_rule,
        },
        "bands": bands,
        "exceptions": exceptions,
        "groups": groups,
        "rows": rows,
    }
