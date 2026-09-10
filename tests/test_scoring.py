"""The rubric must be deterministic and must not let deforestation average away."""

from terrasentry.scoring import Recommendation, score
from terrasentry.tools.entity import EntityFinding
from terrasentry.tools.forest_change import ForestChangeResult
from terrasentry.tools.geometry import GeometryReport


def _clean_geometry() -> GeometryReport:
    return GeometryReport(
        valid=True,
        area_ha=4197.4,
        perimeter_km=26.0,
        geolocation_requirement="polygon",
        bbox=(110.55, -0.2088, 110.608, -0.15),
        problems=[],
        centroid=(110.579, -0.179),
    )


def _forest(loss_ha: float) -> ForestChangeResult:
    return ForestChangeResult(
        polygon_area_ha=4197.4,
        tree_cover_2020_ha=3854.1,
        loss_since_cutoff_ha=loss_ha,
    )


def test_clean_supplier_scores_go():
    result = score(
        geometry=_clean_geometry(),
        forest=_forest(0.0),
        hotspot_summary={"total": 0, "high_confidence": 0},
        entity_findings=[],
        permit_valid=True,
    )
    assert result.recommendation == Recommendation.GO
    assert result.score == 100.0
    assert not result.hard_gates


def test_any_post_cutoff_loss_caps_the_score():
    """Even with everything else spotless, deforestation must not reach GO."""
    result = score(
        geometry=_clean_geometry(),
        forest=_forest(38.2),
        hotspot_summary={"total": 0, "high_confidence": 0},
        entity_findings=[],
        permit_valid=True,
    )
    assert result.hard_gates
    assert result.score <= 59.0
    assert result.recommendation in (Recommendation.ESCALATE, Recommendation.NO_GO)


def test_invalid_geometry_blocks_assessment():
    bad = GeometryReport(
        valid=False,
        area_ha=0.0,
        perimeter_km=0.0,
        geolocation_requirement="point",
        bbox=(0, 0, 0, 0),
        problems=["polygon has zero area"],
        centroid=(0, 0),
    )
    result = score(geometry=bad, forest=None, hotspot_summary=None)
    assert result.recommendation == Recommendation.BLOCKED
    assert result.blocking_problems


def test_scoring_is_deterministic():
    args = dict(
        geometry=_clean_geometry(),
        forest=_forest(12.0),
        hotspot_summary={"total": 7, "high_confidence": 3},
        entity_findings=[EntityFinding("SHARED_DIRECTORS", "medium", "shared", {})],
        permit_valid=True,
    )
    assert score(**args).to_dict() == score(**args).to_dict()


def test_unverified_inputs_cost_points():
    """'Not checked' must never score the same as 'checked and clean'."""
    checked = score(
        geometry=_clean_geometry(),
        forest=_forest(0.0),
        hotspot_summary={"total": 0, "high_confidence": 0},
        permit_valid=True,
    )
    unchecked = score(geometry=_clean_geometry(), forest=None, hotspot_summary=None, permit_valid=None)
    assert unchecked.score < checked.score
