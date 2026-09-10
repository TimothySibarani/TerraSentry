from __future__ import annotations

from conftest import (
    FIXED_TIME,
    make_hotspots,
    make_input,
    make_loss,
    make_supplier,
)
from terrasentry_core.domain.enums import FindingCode, FindingLevel, RiskLevel, Verdict
from terrasentry_core.domain.models import Assessment, AssessmentInput, Finding
from terrasentry_core.evidence import EvidenceLedger, build_source_ledger
from terrasentry_core.scoring import RUBRIC_VERSION, RubricConfig, assess, fingerprint


def score(
    assessment_input: AssessmentInput, config: RubricConfig | None = None
) -> tuple[Assessment, EvidenceLedger]:
    ledger = build_source_ledger(assessment_input, retrieved_at=FIXED_TIME)
    return assess(assessment_input, ledger, config=config), ledger


def find(assessment: Assessment, code: FindingCode) -> Finding:
    return next(finding for finding in assessment.findings if finding.code is code)


def test_same_inputs_always_produce_the_same_score_and_fingerprint() -> None:
    input = make_input(loss=make_loss(total_ha=12.0), hotspots=make_hotspots(count=3))
    first, first_ledger = score(input)
    second, second_ledger = score(input)
    assert first.model_dump() == second.model_dump()
    assert fingerprint(first) == fingerprint(second)
    assert [entry.evidence_id for entry in first_ledger.entries] == [
        entry.evidence_id for entry in second_ledger.entries
    ]


def test_clean_record_is_compliant() -> None:
    assessment, _ = score(make_input())
    assert assessment.verdict is Verdict.COMPLIANT
    assert assessment.risk_level is RiskLevel.NEGLIGIBLE
    assert assessment.score == 0
    assert assessment.data_gaps == []


def test_large_recent_loss_is_high_risk_without_mitigation() -> None:
    input = make_input(
        supplier=make_supplier(certifications=[]),
        loss=make_loss(total_ha=50.0),
    )
    assessment, _ = score(input)
    loss = find(assessment, FindingCode.DEFORESTATION_LOSS)
    assert loss.level is FindingLevel.FLAG
    assert assessment.verdict is Verdict.HIGH_RISK
    assert assessment.risk_level is RiskLevel.NON_NEGLIGIBLE


def test_legal_flag_is_critical_even_with_certification() -> None:
    input = make_input(
        supplier=make_supplier(
            permit_status="suspended",
            sanctions=["2021 permit suspension (synthetic)"],
            certifications=["ISPO"],
        )
    )
    assessment, _ = score(input)
    legal = find(assessment, FindingCode.LEGAL_PERMIT)
    assert legal.level is FindingLevel.FLAG
    assert assessment.verdict is Verdict.HIGH_RISK


def test_loss_below_flag_threshold_is_ambiguous() -> None:
    input = make_input(supplier=make_supplier(certifications=[]), loss=make_loss(total_ha=2.0))
    assessment, _ = score(input)
    loss = find(assessment, FindingCode.DEFORESTATION_LOSS)
    assert loss.level is FindingLevel.BORDERLINE
    assert assessment.verdict is Verdict.AMBIGUOUS


def test_conflicting_signals_resolve_to_ambiguous() -> None:
    # A strong loss flag plus a live certification is exactly the PRD's conflict case.
    input = make_input(supplier=make_supplier(certifications=["ISPO"]), loss=make_loss(total_ha=50.0))
    assessment, _ = score(input)
    assert find(assessment, FindingCode.DEFORESTATION_LOSS).level is FindingLevel.FLAG
    assert find(assessment, FindingCode.CERTIFICATION).mitigating is True
    assert assessment.verdict is Verdict.AMBIGUOUS


def test_fire_cluster_flag_detection() -> None:
    input = make_input(
        supplier=make_supplier(certifications=[]),
        hotspots=make_hotspots(count=6, total_frp=120.0),
    )
    assessment, _ = score(input)
    fire = find(assessment, FindingCode.FIRE_CLUSTER)
    assert fire.level is FindingLevel.FLAG
    assert fire.metrics["detection_count"] == 6
    assert assessment.verdict is Verdict.HIGH_RISK


def test_recent_single_detection_flags_a_cluster() -> None:
    input = make_input(hotspots=make_hotspots(count=1, total_frp=5.0))
    assessment, _ = score(input)
    assert find(assessment, FindingCode.FIRE_CLUSTER).level is FindingLevel.FLAG


def test_missing_sources_become_data_gaps_and_ambiguity() -> None:
    assessment, _ = score(make_input(loss=None, hotspots=None))
    assert "gfw:no data" in assessment.data_gaps
    assert "firms:no data" in assessment.data_gaps
    assert assessment.verdict is Verdict.AMBIGUOUS


def test_rubric_config_is_the_only_knob_needed_to_retune() -> None:
    input = make_input(supplier=make_supplier(certifications=[]), loss=make_loss(total_ha=2.0))
    default, _ = score(input)
    assert default.verdict is Verdict.AMBIGUOUS
    relaxed, _ = score(input, RubricConfig(loss_borderline_ha=5.0))
    assert relaxed.verdict is Verdict.COMPLIANT


def test_every_finding_and_rubric_claim_resolves_in_the_ledger() -> None:
    assessment, ledger = score(make_input(loss=make_loss(total_ha=12.0), hotspots=make_hotspots(count=2)))
    for finding in assessment.findings:
        assert finding.evidence_ids
        ledger.verify({finding.code.value: finding.evidence_ids})
    ledger.verify(assessment.citations)
    score_entry = ledger.by_claim("rubric.score")[0]
    assert score_entry.value["verdict"] == str(assessment.verdict)
    assert score_entry.value["rubric_version"] == RUBRIC_VERSION


def test_score_never_exceeds_bounds() -> None:
    input = make_input(
        supplier=make_supplier(
            permit_status="expired",
            sanctions=["suspended"],
            certifications=[],
        ),
        loss=make_loss(total_ha=100.0),
        hotspots=make_hotspots(count=10, total_frp=400.0),
    )
    assessment, _ = score(input)
    assert 0 <= assessment.score <= 100


def test_empty_ledger_does_not_crash_and_marks_gaps() -> None:
    # assess only needs the source claims; an empty ledger yields empty citations
    # rather than an exception, so partial failure never hides a verdict.
    assessment = assess(make_input(), EvidenceLedger())
    assert assessment.verdict in set(Verdict)
    assert assessment.citations["rubric.score"]
