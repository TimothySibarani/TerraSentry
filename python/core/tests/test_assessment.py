from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from terrasentry_core.assessment import (
    assess_reference_run,
    load_batch,
    load_operator,
    load_reference_run,
    write_assessment_batch,
)
from terrasentry_core.assessment.cli import main
from terrasentry_core.domain.enums import FindingCode
from terrasentry_core.errors import CoreError
from terrasentry_core.reference.pipeline import PolygonReport, ReferenceRun
from terrasentry_core.seed import generate_batch, operator_dataset
from terrasentry_core.seed.schemas import BatchRecord
from terrasentry_integrations.sources.firms import FireDetection, FirmsHotspotResult
from terrasentry_integrations.sources.gfw import TreeCoverLossResult, TreeCoverLossYear

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_STARTED_AT = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def make_report(
    record: BatchRecord,
    *,
    loss_ha: float = 0.0,
    hotspot_count: int = 0,
    hotspot_date: date = date(2026, 8, 30),
) -> PolygonReport:
    polygon = record.polygon
    detections = [
        FireDetection(
            latitude=polygon.centroid_lat,
            longitude=polygon.centroid_lon,
            acq_date=hotspot_date,
            frp=10.0,
        )
        for _ in range(hotspot_count)
    ]
    return PolygonReport(
        polygon_id=polygon.id,
        label=polygon.label,
        region=polygon.region,
        archetype=polygon.archetype,
        area_ha=polygon.area_ha,
        loss=TreeCoverLossResult(
            dataset="umd_tree_cover_loss",
            version="v1.13",
            geometry_hash="b" * 64,
            date_window="2021-2025",
            start_year=2021,
            end_year=2025,
            total_loss_ha=loss_ha,
            by_year=[TreeCoverLossYear(year=2022, loss_ha=loss_ha)] if loss_ha else [],
            fetched_at=RUN_STARTED_AT,
        ),
        hotspots=FirmsHotspotResult(
            source="VIIRS_SNPP_NRT",
            geometry_hash="b" * 64,
            date_window="2026-08-02..2026-09-01",
            window_start=date(2026, 8, 2),
            window_end=date(2026, 9, 1),
            detection_count=hotspot_count,
            total_frp=10.0 * hotspot_count,
            detections=detections,
            fetched_at=RUN_STARTED_AT,
        ),
    )


def make_run(records: list[BatchRecord]) -> ReferenceRun:
    reports = [
        make_report(
            record,
            # Push the first two records onto different finding paths.
            loss_ha=25.0 if record.expected_archetype == "high_risk" else 0.0,
            hotspot_count=1 if record.expected_archetype == "compliant" else 0,
        )
        for record in records
    ]
    return ReferenceRun(
        run_id="ref-unit-test",
        started_at=RUN_STARTED_AT,
        finished_at=RUN_STARTED_AT,
        window_days=30,
        years=5,
        offline=True,
        cache_stats={"hits": 0, "misses": 0, "writes": 0, "offline_misses": 0},
        reports=reports,
    )


def design_report(record: BatchRecord) -> PolygonReport:
    """Inject the source signal each seeded archetype is designed to exercise.

    This is the M6 calibration harness in miniature: the seeded labels are design
    targets, and the deterministic rubric must map the injected signals back onto
    the intended 30/12/8 breakdown.
    """
    loss_ha = 0.0
    hotspot_count = 0
    hotspot_date = date(2026, 9, 1)
    if record.expected_archetype == "high_risk":
        if record.expected_signal == "deforestation":
            loss_ha = 8.0
        elif record.expected_signal == "fire":
            hotspot_count = 8
    elif record.expected_archetype == "ambiguous":
        if record.expected_ambiguity == "borderline_area":
            loss_ha = 2.0
        elif record.expected_ambiguity == "old_fire_scar":
            hotspot_count = 3
            hotspot_date = date(2026, 8, 7)  # old enough not to be a recent cluster
    return make_report(record, loss_ha=loss_ha, hotspot_count=hotspot_count, hotspot_date=hotspot_date)


def test_assess_reference_run_is_reproducible() -> None:
    batch = generate_batch()
    run = make_run(batch.records[:3])
    operator = operator_dataset(batch).operator
    first = assess_reference_run(run, batch, operator)
    second = assess_reference_run(run, batch, operator)
    assert [item.fingerprint for item in first.records] == [item.fingerprint for item in second.records]
    assert first.summary_payload() == second.summary_payload()
    assert first.record_count == 3
    assert sum(first.verdict_breakdown.values()) == 3


def test_confusion_and_signal_coverage_are_reported() -> None:
    batch = generate_batch()
    run = make_run(batch.records[:3])
    result = assess_reference_run(run, batch, operator_dataset(batch).operator)
    assert set(result.confusion) == {"compliant", "high_risk", "ambiguous"}
    for row in result.confusion.values():
        assert set(row) == {"compliant", "high_risk", "ambiguous"}
    flagged_loss = sum(
        1
        for item in result.records
        for finding in item.assessment.findings
        if finding.code is FindingCode.DEFORESTATION_LOSS and finding.level.value == "flag"
    )
    assert result.signal_coverage[FindingCode.DEFORESTATION_LOSS.value] == flagged_loss


def test_write_assessment_batch_emits_dds_evidence_and_summary(tmp_path: Path) -> None:
    batch = generate_batch()
    run = make_run(batch.records[:2])
    result = assess_reference_run(run, batch, operator_dataset(batch).operator)
    written = write_assessment_batch(result, tmp_path)
    names = {path.name for path in written}
    assert {"REC-001.dds.json", "REC-001.dds.xml", "REC-001.evidence.json", "summary.json"} <= names
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["record_count"] == 2
    assert len(summary["records"]) == 2
    assert summary["rubric_version"] == result.rubric_version
    dds = json.loads((tmp_path / "REC-001.dds.json").read_text(encoding="utf-8"))
    assert dds["statement"]["commodities"][0]["producers"][0]["geometryGeojson"]


def test_missing_seed_record_is_a_typed_failure() -> None:
    batch = generate_batch()
    run = make_run(batch.records[:1])
    run.reports[0].polygon_id = "PLY-NOT-IN-BATCH"
    with pytest.raises(CoreError, match="PLY-NOT-IN-BATCH"):
        assess_reference_run(run, batch, operator_dataset(batch).operator)


def test_cli_scores_the_demo_polygons_and_writes_artifacts(tmp_path: Path) -> None:
    batch = generate_batch()
    run = make_run(batch.records[:2])
    run_path = tmp_path / "ref-unit-test.json"
    run_path.write_text(json.dumps(run.model_dump(mode="json"), indent=2), encoding="utf-8")

    exit_code = main(
        [
            "--run",
            str(run_path),
            "--batch",
            str(REPO_ROOT / "data/seed/batch_50.json"),
            "--operator",
            str(REPO_ROOT / "data/seed/operator.json"),
            "--out",
            str(tmp_path / "dds"),
            "--quiet",
        ]
    )
    assert exit_code == 0
    assert (tmp_path / "dds" / "summary.json").exists()


def test_synthetic_signal_batch_reproduces_the_design_breakdown() -> None:
    batch = generate_batch()
    run = ReferenceRun(
        run_id="ref-design-smoke",
        started_at=RUN_STARTED_AT,
        finished_at=RUN_STARTED_AT,
        window_days=30,
        years=5,
        offline=True,
        cache_stats={},
        reports=[design_report(record) for record in batch.records],
    )
    result = assess_reference_run(run, batch, operator_dataset(batch).operator)
    assert result.record_count == 50
    assert result.verdict_breakdown == {"compliant": 30, "high_risk": 12, "ambiguous": 8}
    for archetype, expected_verdict in (
        ("compliant", "compliant"),
        ("high_risk", "high_risk"),
        ("ambiguous", "ambiguous"),
    ):
        assert result.confusion[archetype][expected_verdict] == batch.distribution[archetype]
    # All three PRD detection paths fire at least once on the seeded batch.
    assert result.signal_coverage["deforestation_loss"] >= 4
    assert result.signal_coverage["fire_cluster"] >= 4
    assert result.signal_coverage["legal_permit"] >= 4


def test_loaders_round_trip_the_committed_seed_files(tmp_path: Path) -> None:
    batch = load_batch(REPO_ROOT / "data/seed/batch_50.json")
    operator = load_operator(REPO_ROOT / "data/seed/operator.json")
    run = make_run(batch.records[:1])
    run_path = tmp_path / "run.json"
    run_path.write_text(run.model_dump_json(), encoding="utf-8")
    assert load_reference_run(run_path).run_id == run.run_id
    assert operator.operator_id == "OP-SYNTH-001"
    assert batch.records[0].consignment.hs_heading
