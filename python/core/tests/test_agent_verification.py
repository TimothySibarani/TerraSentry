"""The verifier's deterministic re-derivation is the hard gate."""

from __future__ import annotations

from typing import Any

import agent_helpers
import pytest
from terrasentry_core.agents.verification import code_checks, coverage_checks, merge_coverage
from terrasentry_core.assessment.pipeline import RecordAssessment, assess_record
from terrasentry_core.domain.enums import FindingCode
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.tools.sources import PolygonSources
from terrasentry_core.tools.trace import TraceCollector, TraceStep


def _candidate(factories: dict[str, Any]) -> tuple[Any, PolygonSources, RecordAssessment]:
    data = agent_helpers.datasets()
    record = data.get_record("REC-001")
    sources = PolygonSources(
        polygon_id=record.polygon.id,
        loss=factories["loss"](total_ha=6.0),
        hotspots=factories["hotspots"](count=0),
    )
    polygon = record.polygon
    report = PolygonReport(
        polygon_id=polygon.id,
        label=polygon.label,
        region=polygon.region,
        archetype=polygon.archetype,
        area_ha=polygon.area_ha,
        loss=sources.loss,
        hotspots=sources.hotspots,
    )
    candidate = assess_record(report, record, data.operator, retrieved_at=agent_helpers.FIXED_TIME)
    return record, sources, candidate


def test_clean_candidate_passes_and_reports_checks(factories: dict[str, Any]) -> None:
    record, sources, candidate = _candidate(factories)
    report = code_checks(
        candidate,
        record,
        sources,
        operator=agent_helpers.datasets().operator,
        retrieved_at=agent_helpers.FIXED_TIME,
    )
    assert report.accepted
    assert "dds.citations" in report.checked_claims
    assert f"metric.{FindingCode.DEFORESTATION_LOSS.value}" in report.checked_claims
    assert not report.errors


def test_tampered_metric_is_rejected(factories: dict[str, Any]) -> None:
    record, sources, candidate = _candidate(factories)
    finding = next(
        item for item in candidate.assessment.findings if item.code is FindingCode.DEFORESTATION_LOSS
    )
    finding.metrics["post_cutoff_loss_ha"] = 999.0
    report = code_checks(
        candidate,
        record,
        sources,
        operator=agent_helpers.datasets().operator,
        retrieved_at=agent_helpers.FIXED_TIME,
    )
    assert not report.accepted
    assert any(
        challenge.kind == "metric_mismatch" and challenge.severity == "error"
        for challenge in report.challenges
    )


def test_missing_evidence_is_a_citation_failure(factories: dict[str, Any]) -> None:
    record, sources, candidate = _candidate(factories)
    candidate.evidence = []
    report = code_checks(
        candidate,
        record,
        sources,
        operator=agent_helpers.datasets().operator,
        retrieved_at=agent_helpers.FIXED_TIME,
    )
    assert not report.accepted
    assert any(challenge.kind == "citation_failure" for challenge in report.challenges)


def test_source_gap_is_a_warning_not_a_rejection(factories: dict[str, Any]) -> None:
    record, _sources, candidate = _candidate(factories)
    empty = PolygonSources(polygon_id=record.polygon.id, errors=["gfw: timeout", "firms: timeout"])
    candidate = assess_record(
        PolygonReport(
            polygon_id=record.polygon.id,
            label=record.polygon.label,
            region=record.polygon.region,
            area_ha=record.polygon.area_ha,
            errors=empty.errors,
        ),
        record,
        agent_helpers.datasets().operator,
        retrieved_at=agent_helpers.FIXED_TIME,
    )
    report = code_checks(
        candidate,
        record,
        empty,
        operator=agent_helpers.datasets().operator,
        retrieved_at=agent_helpers.FIXED_TIME,
    )
    assert report.accepted
    assert any(
        challenge.kind == "missing_source" and challenge.severity == "warning"
        for challenge in report.challenges
    )


def test_candidate_record_mismatch_is_a_programming_error(factories: dict[str, Any]) -> None:
    record, sources, candidate = _candidate(factories)
    candidate.record_id = "REC-OTHER"
    with pytest.raises(ValueError, match="REC-OTHER"):
        code_checks(candidate, record, sources, operator=agent_helpers.datasets().operator)


def test_design_mismatch_is_reported_as_a_challenge(factories: dict[str, Any]) -> None:
    record = factories["batch_record"](
        index=70,
        expected_archetype="high_risk",
        expected_signal="deforestation",
    )
    sources = PolygonSources(
        polygon_id=record.polygon.id,
        loss=factories["loss"](total_ha=0.0),
        hotspots=factories["hotspots"](count=0),
    )
    polygon = record.polygon
    polygon_report = PolygonReport(
        polygon_id=polygon.id,
        label=polygon.label,
        region=polygon.region,
        archetype=polygon.archetype,
        area_ha=polygon.area_ha,
        loss=sources.loss,
        hotspots=sources.hotspots,
    )
    operator = agent_helpers.datasets().operator
    candidate = assess_record(polygon_report, record, operator, retrieved_at=agent_helpers.FIXED_TIME)
    report = code_checks(
        candidate,
        record,
        sources,
        operator=agent_helpers.datasets().operator,
        retrieved_at=agent_helpers.FIXED_TIME,
    )
    assert report.accepted
    assert any(challenge.kind == "design_mismatch" for challenge in report.challenges)


@pytest.mark.parametrize("target", ["score", "verdict", "fingerprint", "points", "dds", "evidence"])
def test_tampered_outcomes_are_rejected(factories: dict[str, Any], target: str) -> None:
    from terrasentry_core.domain.enums import Verdict

    record, sources, candidate = _candidate(factories)
    if target == "score":
        candidate.assessment.score = -1
    elif target == "verdict":
        candidate.assessment.verdict = Verdict.COMPLIANT
    elif target == "fingerprint":
        candidate.fingerprint = "fake"
    elif target == "points":
        candidate.assessment.findings[0].points += 1
    elif target == "dds":
        candidate.dds.statement.commodities[0].producers[0].country = "BR"
    else:
        candidate.evidence[0].value = "altered"
    assert not code_checks(candidate, record, sources, operator=agent_helpers.datasets().operator).accepted


# -- coverage gate -----------------------------------------------------------------------------


def _coverage_candidate(factories: dict[str, Any], *, loss_ha: float) -> tuple[Any, RecordAssessment]:
    record, _, _ = _candidate(factories)
    polygon = record.polygon
    report = PolygonReport(
        polygon_id=polygon.id,
        label=polygon.label,
        region=polygon.region,
        archetype=polygon.archetype,
        area_ha=polygon.area_ha,
        loss=factories["loss"](total_ha=loss_ha),
        hotspots=factories["hotspots"](count=0),
    )
    candidate = assess_record(
        report, record, agent_helpers.datasets().operator, retrieved_at=agent_helpers.FIXED_TIME
    )
    return record, candidate


def _steps(*calls: tuple[str, dict[str, Any]], kind: str = "tool") -> list[TraceStep]:
    trace = TraceCollector(clock=lambda: agent_helpers.FIXED_TIME)
    for name, payload in calls:
        trace.add(kind, name, "recorded", payload=payload)  # type: ignore[arg-type]
    return trace.steps


def _baseline(record: Any) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("get_tree_cover_loss", {"polygon_id": record.polygon.id, "status": "ok"}),
        ("get_fire_hotspots", {"polygon_id": record.polygon.id, "status": "ok"}),
        ("get_legality_record", {"supplier_id": record.supplier_id, "status": "ok"}),
    ]


def _deep_dives(record: Any, status: str = "ok") -> list[tuple[str, dict[str, Any]]]:
    return [
        ("get_context_layers", {"polygon_id": record.polygon.id, "status": status}),
        (
            "check_concession_overlap",
            {"polygon_id": record.polygon.id, "supplier_id": record.supplier_id, "status": status},
        ),
    ]


def test_clean_candidate_needs_only_the_baseline_tools(factories: dict[str, Any]) -> None:
    record, candidate = _coverage_candidate(factories, loss_ha=0.0)
    report = coverage_checks(candidate, record, _steps(*_baseline(record)))
    assert report.accepted and not report.challenges
    assert {"coverage.get_tree_cover_loss", "coverage.get_legality_record"} <= set(report.checked_claims)
    assert "coverage.get_context_layers" not in report.checked_claims


def test_flagged_candidate_without_the_deep_dive_is_rejected(factories: dict[str, Any]) -> None:
    record, candidate = _coverage_candidate(factories, loss_ha=6.0)
    report = coverage_checks(candidate, record, _steps(*_baseline(record)))
    assert not report.accepted
    errors = {c.detail.split()[2]: c for c in report.errors}
    assert set(errors) == {"get_context_layers", "check_concession_overlap"}
    assert errors["get_context_layers"].expected == f"polygon_id={record.polygon.id}"
    assert "deforestation_loss" in errors["get_context_layers"].detail
    assert all(c.kind == "coverage" and c.source == "trace" for c in report.errors)


def test_complete_investigation_is_accepted(factories: dict[str, Any]) -> None:
    record, candidate = _coverage_candidate(factories, loss_ha=6.0)
    report = coverage_checks(candidate, record, _steps(*_baseline(record), *_deep_dives(record)))
    assert report.accepted and not report.challenges


def test_deep_dive_for_another_polygon_or_supplier_does_not_count(factories: dict[str, Any]) -> None:
    record, candidate = _coverage_candidate(factories, loss_ha=6.0)
    wrong = [
        ("get_context_layers", {"polygon_id": "PLY-OTHER", "status": "ok"}),
        (
            "check_concession_overlap",
            {"polygon_id": record.polygon.id, "supplier_id": "SUP-OTHER", "status": "ok"},
        ),
    ]
    report = coverage_checks(candidate, record, _steps(*_baseline(record), *wrong))
    assert not report.accepted and len(report.errors) == 2


def test_attempted_but_failed_deep_dive_is_covered_with_a_data_gap(factories: dict[str, Any]) -> None:
    record, candidate = _coverage_candidate(factories, loss_ha=6.0)
    report = coverage_checks(candidate, record, _steps(*_baseline(record), *_deep_dives(record, "error")))
    assert report.accepted and not report.errors
    assert [c.severity for c in report.challenges] == ["info", "info"]
    assert all("data gap" in c.detail for c in report.challenges)


def test_missing_baseline_legality_read_is_rejected_on_a_clean_record(factories: dict[str, Any]) -> None:
    record, candidate = _coverage_candidate(factories, loss_ha=0.0)
    report = coverage_checks(candidate, record, _steps(*_baseline(record)[:2]))
    assert not report.accepted
    assert [c.detail.split()[2] for c in report.errors] == ["get_legality_record"]


def test_model_claims_and_retask_steps_never_count(factories: dict[str, Any]) -> None:
    record, candidate = _coverage_candidate(factories, loss_ha=6.0)
    claim = _steps(
        ("legality_analyst", {"reason": "context layers checked; concession overlap checked", "ordinal": 2}),
        kind="retask",
    )
    forged = _steps(*_deep_dives(record), kind="verifier")
    forged.extend(_steps(*_deep_dives(record), kind="thought"))
    report = coverage_checks(candidate, record, [*_steps(*_baseline(record)), *claim, *forged])
    assert not report.accepted and len(report.errors) == 2


def test_merge_coverage_keeps_the_error_veto_and_leaves_code_checks_alone(factories: dict[str, Any]) -> None:
    record, sources, candidate = _candidate(factories)
    operator = agent_helpers.datasets().operator
    deterministic = code_checks(
        candidate, record, sources, operator=operator, retrieved_at=agent_helpers.FIXED_TIME
    )
    again = code_checks(candidate, record, sources, operator=operator, retrieved_at=agent_helpers.FIXED_TIME)
    assert deterministic == again and deterministic.accepted
    assert not any(c.kind == "coverage" for c in deterministic.challenges)
    merged = merge_coverage(deterministic, coverage_checks(candidate, record, []))
    assert not merged.accepted
    assert {c.kind for c in merged.errors} == {"coverage"}
    assert set(deterministic.checked_claims) <= set(merged.checked_claims)
