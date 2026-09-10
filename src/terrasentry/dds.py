"""Due Diligence Statement (DDS) builder.

EUDR requires operators to file a DDS through the EU **TRACES** Information System
before placing regulated commodities on the market. This module assembles a
TRACES-*aligned* draft plus the evidence annex behind it.

⚠️  **Field names here are structural, not authoritative.** The official TRACES DDS
schema is published by the European Commission and has changed across implementing
acts -- most recently with the May 2026 simplification package, which also moved the
filing obligation onto the *first operator* placing goods on the EU market. Before
anything is submitted for real, map these fields against the current official schema.
Treat this module as "the right shape, pending verification of the exact keys".

The deliberate design choice: when the assessment does not support a
"negligible risk" conclusion, this module does **not** emit a statement anyway with a
worse rating. It emits a **gap list** -- what the supplier must provide to close the
finding. That is the output procurement can actually act on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .evidence import EvidenceLedger
from .scoring import Recommendation, RiskAssessment

# EUDR Annex I commodity scope, with the HS headings usually cited for each.
# Confirm the precise subheading for the actual product before filing.
COMMODITY_HS_HINTS = {
    "palm_oil": "1511",
    "timber": "4401-4421",
    "rubber": "4001",
    "coffee": "0901",
    "cocoa": "1801",
    "soy": "1201",
    "cattle": "0102",
}


@dataclass
class Gap:
    """One thing the supplier must supply before the dossier can be closed."""

    code: str
    requirement: str
    why: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "requirement": self.requirement, "why": self.why}


@dataclass
class DdsDraft:
    issued: bool
    payload: dict[str, Any]
    gaps: list[Gap] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issued": self.issued,
            "gaps": [g.to_dict() for g in self.gaps],
            "statement": self.payload,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def build(
    *,
    supplier_name: str,
    operator: dict[str, Any],
    commodity: str,
    geometry_feature: dict[str, Any],
    geometry_requirement: str,
    area_ha: float,
    country_of_production: str,
    assessment: RiskAssessment,
    ledger: EvidenceLedger,
    quantity: dict[str, Any] | None = None,
    narrative: str | None = None,
) -> DdsDraft:
    """Assemble a DDS draft, or a gap list when the assessment does not support one.

    Args:
        operator: The entity that would file the statement -- name, address, EORI.
        commodity: Key from :data:`COMMODITY_HS_HINTS`.
        geometry_feature: GeoJSON Feature from ``tools.geometry.to_geojson_feature``.
        geometry_requirement: "polygon" or "point", per EUDR Art. 9.
        assessment: Output of ``scoring.score``. Numbers come from here, never from a model.
        narrative: Optional model-written prose explaining the assessment. It may
            *describe* the numbers; it may not introduce new ones.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    statement: dict[str, Any] = {
        "schema_note": (
            "TRACES-aligned draft. Field names must be mapped to the official EU "
            "Information System schema before submission."
        ),
        "generated_at": now,
        "operator": operator,
        "supplier": {"name": supplier_name, "country_of_production": country_of_production},
        "commodity": {
            "key": commodity,
            "hs_heading_hint": COMMODITY_HS_HINTS.get(commodity, "UNKNOWN -- confirm HS code"),
        },
        "quantity": quantity or {"value": None, "unit": None, "note": "to be completed per shipment"},
        "geolocation": {
            "requirement": geometry_requirement,
            "area_ha": round(area_ha, 3),
            "features": {"type": "FeatureCollection", "features": [geometry_feature]},
            "crs": "EPSG:4326",
        },
        "risk_assessment": {
            "score": round(assessment.score, 1),
            "recommendation": assessment.recommendation.value,
            "conclusion": _conclusion_for(assessment),
            "components": [c.to_dict() for c in assessment.components],
            "hard_gates": assessment.hard_gates,
            "narrative": narrative,
        },
        "evidence_annex": ledger.to_dict(),
        "declaration": {
            "text": (
                "By submitting this statement the operator confirms that due diligence "
                "was carried out in accordance with Regulation (EU) 2023/1115 and that "
                "the risk of non-compliance is negligible."
            ),
            "signed_by": None,
            "signed_at": None,
            "note": "Unsigned draft. A human authorised representative must review and sign.",
        },
    }

    gaps = _gaps_for(assessment, ledger)
    issued = assessment.recommendation == Recommendation.GO and not gaps

    if not issued:
        statement["declaration"]["note"] = (
            "NOT ISSUABLE as a negligible-risk statement in its current state. "
            "See the gap list."
        )

    return DdsDraft(issued=issued, payload=statement, gaps=gaps)


def _conclusion_for(assessment: RiskAssessment) -> str:
    if assessment.recommendation == Recommendation.GO:
        return "negligible_risk"
    if assessment.recommendation == Recommendation.CONDITIONAL:
        return "negligible_risk_pending_conditions"
    if assessment.recommendation == Recommendation.BLOCKED:
        return "not_assessable"
    return "non_negligible_risk"


def _gaps_for(assessment: RiskAssessment, ledger: EvidenceLedger) -> list[Gap]:
    """Turn an unfavourable assessment into an actionable request list."""
    gaps: list[Gap] = []

    for problem in assessment.blocking_problems:
        gaps.append(
            Gap(
                code="GEOMETRY_UNUSABLE",
                requirement="Provide a valid WGS84 GeoJSON polygon for the production plot.",
                why=problem,
            )
        )

    for component in assessment.components:
        if component.dimension == "deforestation" and component.penalty > 0:
            gaps.append(
                Gap(
                    code="DEFORESTATION_EXPLANATION",
                    requirement=(
                        "Provide documentation explaining tree-cover loss recorded after "
                        "31 December 2020 within the plot (permits, land-use change approvals, "
                        "or evidence of natural disturbance)."
                    ),
                    why="; ".join(component.reasons) or "Post-cutoff loss detected.",
                )
            )
        if component.dimension == "fire" and component.penalty > 0:
            gaps.append(
                Gap(
                    code="FIRE_EXPLANATION",
                    requirement=(
                        "Provide fire-management records and incident reports covering the "
                        "detected hotspot periods."
                    ),
                    why="; ".join(component.reasons),
                )
            )
        if component.dimension == "legality" and component.penalty > 0:
            gaps.append(
                Gap(
                    code="PERMIT_EVIDENCE",
                    requirement="Provide the current concession permit and its validity dates.",
                    why="; ".join(component.reasons),
                )
            )
        if component.dimension == "entity" and component.penalty > 0:
            gaps.append(
                Gap(
                    code="OWNERSHIP_CLARIFICATION",
                    requirement=(
                        "Provide a beneficial-ownership declaration and clarify the relationship "
                        "with the entities identified in the assessment."
                    ),
                    why="; ".join(component.reasons),
                )
            )

    unverified = ledger.verify()
    for problem in unverified:
        gaps.append(
            Gap(
                code="UNSUPPORTED_CLAIM",
                requirement="Remove or substantiate the claim before the dossier is issued.",
                why=problem,
            )
        )

    return gaps
