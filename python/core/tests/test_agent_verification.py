"""The verifier's deterministic re-derivation is the hard gate."""

from __future__ import annotations

from typing import Any

import agent_helpers
import pytest
from terrasentry_core.agents.verification import code_checks
from terrasentry_core.assessment.pipeline import RecordAssessment, assess_record
from terrasentry_core.domain.enums import FindingCode
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.tools.sources import PolygonSources


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
    report = code_checks(candidate, record, sources, retrieved_at=agent_helpers.FIXED_TIME)
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
    report = code_checks(candidate, record, sources, retrieved_at=agent_helpers.FIXED_TIME)
    assert not report.accepted
    assert any(
        challenge.kind == "metric_mismatch" and challenge.severity == "error"
        for challenge in report.challenges
    )


def test_missing_evidence_is_a_citation_failure(factories: dict[str, Any]) -> None:
    record, sources, candidate = _candidate(factories)
    candidate.evidence = []
    report = code_checks(candidate, record, sources, retrieved_at=agent_helpers.FIXED_TIME)
    assert not report.accepted
    assert any(challenge.kind == "citation_failure" for challenge in report.challenges)


def test_source_gap_is_a_warning_not_a_rejection(factories: dict[str, Any]) -> None:
    record, _sources, candidate = _candidate(factories)
    empty = PolygonSources(polygon_id=record.polygon.id, errors=["gfw: timeout", "firms: timeout"])
    report = code_checks(candidate, record, empty, retrieved_at=agent_helpers.FIXED_TIME)
    assert report.accepted
    assert any(
        challenge.kind == "missing_source" and challenge.severity == "warning"
        for challenge in report.challenges
    )


def test_candidate_record_mismatch_is_a_programming_error(factories: dict[str, Any]) -> None:
    record, sources, candidate = _candidate(factories)
    candidate.record_id = "REC-OTHER"
    with pytest.raises(ValueError, match="REC-OTHER"):
        code_checks(candidate, record, sources)


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
    report = code_checks(candidate, record, sources, retrieved_at=agent_helpers.FIXED_TIME)
    assert report.accepted
    assert any(challenge.kind == "design_mismatch" for challenge in report.challenges)
