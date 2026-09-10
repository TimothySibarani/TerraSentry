"""Deterministic risk rubric.

**No language model touches this file.** The score is a pure function of the findings
produced by the tools. The model's job is to *narrate* the result, never to compute it.

Two reasons this matters more than it might look:

  1. Reproducibility. The same supplier and the same evidence always produce the same
     number, which is the minimum bar for anything that feeds a legal statement.
  2. It is the honest answer to the question every judge asks -- *"what if the AI
     hallucinates?"* The number is not from the AI.

Scoring direction: **higher is better.** A run starts at 100 and loses points as risk
signals accumulate. Certain findings are hard gates that cap the maximum achievable
score regardless of everything else, because EUDR does not average away deforestation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from .tools.entity import EntityFinding
from .tools.forest_change import ForestChangeResult
from .tools.geometry import GeometryReport


class Recommendation(str, Enum):
    GO = "GO"
    CONDITIONAL = "CONDITIONAL"
    ESCALATE = "ESCALATE"
    NO_GO = "NO_GO"
    BLOCKED = "BLOCKED"  # cannot assess -- input is unusable


# Band thresholds, inclusive lower bound.
BANDS: list[tuple[int, Recommendation]] = [
    (80, Recommendation.GO),
    (60, Recommendation.CONDITIONAL),
    (30, Recommendation.ESCALATE),
    (0, Recommendation.NO_GO),
]

# Maximum points each dimension can remove.
WEIGHTS = {
    "deforestation": 40,
    "fire": 25,
    "legality": 20,
    "entity": 15,
}

SEVERITY_POINTS = {"info": 0, "low": 3, "medium": 7, "high": 12}


@dataclass
class Component:
    """One dimension's contribution, with the reasoning kept in structured form."""

    dimension: str
    penalty: float
    max_penalty: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "penalty": round(self.penalty, 2),
            "max_penalty": self.max_penalty,
            "reasons": self.reasons,
        }


@dataclass
class RiskAssessment:
    score: float
    recommendation: Recommendation
    components: list[Component]
    hard_gates: list[str] = field(default_factory=list)
    blocking_problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "recommendation": self.recommendation.value,
            "components": [c.to_dict() for c in self.components],
            "hard_gates": self.hard_gates,
            "blocking_problems": self.blocking_problems,
        }

    def explain(self) -> str:
        """Compact, model-readable summary.

        Feed this to the Compliance Writer as the *only* source of numbers. The model
        turns it into prose; it must not recompute anything.
        """
        lines = [f"SCORE {self.score:.1f}/100 -> {self.recommendation.value}"]
        for c in self.components:
            lines.append(f"  {c.dimension}: -{c.penalty:.1f} of max {c.max_penalty}")
            lines.extend(f"    - {r}" for r in c.reasons)
        if self.hard_gates:
            lines.append("  HARD GATES APPLIED:")
            lines.extend(f"    - {g}" for g in self.hard_gates)
        if self.blocking_problems:
            lines.append("  BLOCKING:")
            lines.extend(f"    - {p}" for p in self.blocking_problems)
        return "\n".join(lines)


def score(
    geometry: GeometryReport,
    forest: ForestChangeResult | None,
    hotspot_summary: dict[str, Any] | None,
    entity_findings: Sequence[EntityFinding] = (),
    permit_valid: bool | None = None,
    permit_notes: Sequence[str] = (),
) -> RiskAssessment:
    """Compute the risk assessment from tool outputs.

    Args:
        geometry: Output of ``tools.geometry.validate``.
        forest: Output of a forest-change backend, or None if not yet available.
        hotspot_summary: Output of ``tools.firms.summarise`` for hotspots *inside* the plot.
        entity_findings: Findings from ``tools.entity``.
        permit_valid: Tri-state. None means "not verified", which is itself a penalty.
        permit_notes: Free-text notes from permit verification.
    """
    # -- gate 0: can we assess at all? ------------------------------------
    if geometry.blocking:
        return RiskAssessment(
            score=0.0,
            recommendation=Recommendation.BLOCKED,
            components=[],
            blocking_problems=list(geometry.problems),
        )

    components: list[Component] = []
    hard_gates: list[str] = []

    # -- deforestation ----------------------------------------------------
    defo = Component("deforestation", 0.0, WEIGHTS["deforestation"])
    if forest is None:
        defo.penalty = WEIGHTS["deforestation"] * 0.5
        defo.reasons.append("Tree-cover change not yet analysed; assessed as unverified.")
    elif forest.loss_since_cutoff_ha <= 0:
        defo.reasons.append(
            f"No tree-cover loss detected since the 31 Dec 2020 cutoff "
            f"(canopy threshold {forest.canopy_threshold}%)."
        )
    else:
        share = forest.loss_share_of_plot
        # Scale to the full weight at 5% of the plot lost; beyond that it is already maximal.
        defo.penalty = min(WEIGHTS["deforestation"], WEIGHTS["deforestation"] * (share / 0.05))
        defo.reasons.append(
            f"{forest.loss_since_cutoff_ha:.1f} ha lost since cutoff "
            f"({share * 100:.2f}% of the {forest.polygon_area_ha:.0f} ha plot)."
        )
        hard_gates.append(
            "Post-2020 deforestation detected inside the plot: a 'negligible risk' "
            "conclusion cannot be issued without a documented lawful explanation."
        )
    components.append(defo)

    # -- fire -------------------------------------------------------------
    fire = Component("fire", 0.0, WEIGHTS["fire"])
    if hotspot_summary is None:
        fire.penalty = WEIGHTS["fire"] * 0.4
        fire.reasons.append("Hotspot history not retrieved; assessed as unverified.")
    else:
        total = int(hotspot_summary.get("total", 0))
        high = int(hotspot_summary.get("high_confidence", 0))
        if total == 0:
            fire.reasons.append("No hotspots detected inside the plot in the review period.")
        else:
            # Full weight at 50 detections; high-confidence ones count double.
            weighted = total + high
            fire.penalty = min(WEIGHTS["fire"], WEIGHTS["fire"] * (weighted / 50.0))
            fire.reasons.append(f"{total} hotspot(s) inside the plot, {high} high-confidence.")
            peak = hotspot_summary.get("peak_month")
            if peak and peak.get("count", 0) >= 10:
                fire.reasons.append(
                    f"Clustered activity in {peak['month']} ({peak['count']} detections) "
                    f"-- inconsistent with diffuse seasonal burning."
                )
    components.append(fire)

    # -- legality ---------------------------------------------------------
    legality = Component("legality", 0.0, WEIGHTS["legality"])
    if permit_valid is None:
        legality.penalty = WEIGHTS["legality"] * 0.5
        legality.reasons.append("Permit status not verified.")
    elif permit_valid:
        legality.reasons.append("Permit verified as valid and current.")
    else:
        legality.penalty = WEIGHTS["legality"]
        legality.reasons.append("Permit could not be verified as valid.")
        hard_gates.append("Permit invalid or unverifiable: legality of production is not established.")
    legality.reasons.extend(permit_notes)
    components.append(legality)

    # -- entity structure -------------------------------------------------
    entity = Component("entity", 0.0, WEIGHTS["entity"])
    if not entity_findings:
        entity.reasons.append("No ownership-structure anomalies detected.")
    else:
        raw = sum(SEVERITY_POINTS.get(f.severity, 0) for f in entity_findings)
        entity.penalty = min(WEIGHTS["entity"], float(raw))
        for f in entity_findings:
            if f.severity != "info":
                entity.reasons.append(f"[{f.severity}] {f.statement}")
        if any(f.severity == "high" for f in entity_findings):
            hard_gates.append(
                "High-severity ownership anomaly: supply-chain mapping should be confirmed "
                "by a human before contracting."
            )
    components.append(entity)

    # -- combine ----------------------------------------------------------
    total_penalty = sum(c.penalty for c in components)
    raw_score = max(0.0, 100.0 - total_penalty)

    # Hard gates cap the ceiling. Deforestation inside the plot must never be able to
    # average out to GO because the other dimensions are clean.
    ceiling = 100.0
    if hard_gates:
        ceiling = 59.0  # cannot exceed the top of the ESCALATE band
    final = min(raw_score, ceiling)

    return RiskAssessment(
        score=final,
        recommendation=_band(final),
        components=components,
        hard_gates=hard_gates,
    )


def _band(value: float) -> Recommendation:
    for threshold, rec in BANDS:
        if value >= threshold:
            return rec
    return Recommendation.NO_GO
