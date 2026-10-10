"""Deterministic investigation rules shared by the tools, scripted agents and verifier.

Two rules live here so neither the prompts nor the model own them:

- ``screening_signals`` lists the screening facts that warrant a deep dive.
- ``required_deep_dives`` lists the deep dives a candidate assessment requires.

Every non-CLEAR level in ``scoring.py`` needs a positive fact that
``screening_signals`` reports, so a model that follows the signals always satisfies
coverage. The coverage gate stays a minimum the model cannot negotiate.
"""

from __future__ import annotations

from dataclasses import dataclass

from terrasentry_core.domain.enums import FindingCode, FindingLevel
from terrasentry_core.domain.models import Finding
from terrasentry_core.scoring import RubricConfig
from terrasentry_core.tools.sources import PolygonSources

SIGNALS_PREFIX = "SCREENING_SIGNALS:"

#: Findings whose presence (BORDERLINE or FLAG) requires both deep dives.
INVESTIGATED_CODES: frozenset[FindingCode] = frozenset(
    {
        FindingCode.DEFORESTATION_LOSS,
        FindingCode.FIRE_CLUSTER,
        FindingCode.PROTECTED_AREA,
        FindingCode.MORATORIUM,
        FindingCode.PEATLAND,
        FindingCode.CONCESSION_CONFLICT,
    }
)

#: Context layer name -> signal code for a positive overlap.
_OVERLAP_SIGNALS = {
    "protected_areas": "protected_overlap",
    "moratorium": "moratorium_overlap",
    "peatlands": "peat_overlap",
}


@dataclass(frozen=True, slots=True)
class DeepDive:
    """A required tool call and the id fields its trace step must carry."""

    tool: str
    id_fields: tuple[str, ...]


GET_CONTEXT_LAYERS = DeepDive("get_context_layers", ("polygon_id",))
CHECK_CONCESSION_OVERLAP = DeepDive("check_concession_overlap", ("polygon_id", "supplier_id"))

BASELINE_TOOLS: tuple[DeepDive, ...] = (
    DeepDive("get_tree_cover_loss", ("polygon_id",)),
    DeepDive("get_fire_hotspots", ("polygon_id",)),
    DeepDive("get_legality_record", ("supplier_id",)),
)


def screening_signals(sources: PolygonSources, config: RubricConfig | None = None) -> list[str]:
    """Stable, sorted codes for the screening facts that call for a deep dive."""
    config = config or RubricConfig()
    signals: set[str] = set()
    if sources.loss is not None:
        post_cutoff = sum(item.loss_ha for item in sources.loss.by_year if item.year >= config.cutoff_year)
        if post_cutoff > 0:
            signals.add("loss_post_cutoff")
    if sources.hotspots is not None and sources.hotspots.detection_count > 0:
        signals.add("hotspots")
    if sources.layers is not None:
        for layer in sources.layers.layers:
            if layer.status == "unavailable":
                signals.add(f"context_unavailable:{layer.name}")
            elif layer.status == "success" and layer.overlap_ha > 0:
                if layer.name.endswith("_concessions"):
                    signals.add("concession_overlap")
                elif layer.name in _OVERLAP_SIGNALS:
                    signals.add(_OVERLAP_SIGNALS[layer.name])
    return sorted(signals)


def required_deep_dives(findings: list[Finding]) -> frozenset[DeepDive]:
    """Deep dives a candidate requires: any non-CLEAR finding in the investigated codes."""
    triggered = any(
        finding.code in INVESTIGATED_CODES and finding.level is not FindingLevel.CLEAR for finding in findings
    )
    return frozenset({GET_CONTEXT_LAYERS, CHECK_CONCESSION_OVERLAP}) if triggered else frozenset()


def triggering_codes(findings: list[Finding]) -> list[str]:
    """Finding codes that make deep dives mandatory, for challenge messages."""
    return sorted(
        finding.code.value
        for finding in findings
        if finding.code in INVESTIGATED_CODES and finding.level is not FindingLevel.CLEAR
    )


def format_signals_line(signals: list[str]) -> str:
    return f"{SIGNALS_PREFIX} {','.join(signals) if signals else 'none'}"


def parse_signals(text: str) -> list[str]:
    """Robustly pull the signals line out of surrounding specialist text."""
    found: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip().strip("*`")
        if stripped.startswith(SIGNALS_PREFIX):
            for item in stripped.removeprefix(SIGNALS_PREFIX).split(","):
                item = item.strip().strip("*`")
                if item and item != "none":
                    found.add(item)
    return sorted(found)


__all__ = [
    "BASELINE_TOOLS",
    "CHECK_CONCESSION_OVERLAP",
    "GET_CONTEXT_LAYERS",
    "INVESTIGATED_CODES",
    "SIGNALS_PREFIX",
    "DeepDive",
    "format_signals_line",
    "parse_signals",
    "required_deep_dives",
    "screening_signals",
    "triggering_codes",
]
