"""Assess an M1 reference run deterministically and emit DDS artifacts.

This is the executable parity target for M3: the agent path must produce the
same :class:`Assessment` (and therefore the same fingerprint) for the same
inputs. Nothing here calls a model, the network, or the wall clock beyond the
reference run's own timestamps.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from terrasentry_core.dds import DdsDocument, build_dds, validate_citations
from terrasentry_core.domain.enums import FindingCode, FindingLevel, RunState
from terrasentry_core.domain.models import (
    Assessment,
    AssessmentInput,
    Consignment,
    OperatorProfile,
    Parcel,
    SupplierProfile,
)
from terrasentry_core.domain.run_state import state_for_verdict
from terrasentry_core.errors import CoreError
from terrasentry_core.evidence import EvidenceEntry, build_source_ledger
from terrasentry_core.reference.pipeline import PolygonReport, ReferenceRun
from terrasentry_core.scoring import RUBRIC_VERSION, assess, fingerprint
from terrasentry_core.seed.schemas import (
    AmbiguityReason,
    Archetype,
    BatchDataset,
    BatchRecord,
    ExpectedSignal,
    LegalityRecord,
    OperatorDataset,
    OperatorRecord,
    SeedPolygon,
)


class RecordAssessment(BaseModel):
    """Everything produced for one batch record: verdict, DDS, and the ledger."""

    record_id: str
    supplier_id: str
    polygon_id: str
    expected_archetype: Archetype
    expected_signal: ExpectedSignal | None = None
    expected_ambiguity: AmbiguityReason | None = None
    run_state: RunState
    assessment: Assessment
    dds: DdsDocument
    fingerprint: str
    evidence: list[EvidenceEntry] = Field(default_factory=list)


class AssessmentBatch(BaseModel):
    """Aggregate result used by M5's batch view and M6's calibration harness."""

    reference_run_id: str
    rubric_version: str = RUBRIC_VERSION
    record_count: int
    verdict_breakdown: dict[str, int]
    expected_breakdown: dict[str, int]
    confusion: dict[str, dict[str, int]]
    signal_coverage: dict[str, int]
    records: list[RecordAssessment]
    disclosures: list[str] = Field(default_factory=list)

    def summary_payload(self) -> dict:
        """Aggregates plus one light row per record; full payloads live in files."""
        return {
            "reference_run_id": self.reference_run_id,
            "rubric_version": self.rubric_version,
            "record_count": self.record_count,
            "verdict_breakdown": self.verdict_breakdown,
            "expected_breakdown": self.expected_breakdown,
            "confusion": self.confusion,
            "signal_coverage": self.signal_coverage,
            "disclosures": self.disclosures,
            "records": [
                {
                    "record_id": item.record_id,
                    "supplier_id": item.supplier_id,
                    "polygon_id": item.polygon_id,
                    "expected_archetype": item.expected_archetype,
                    "expected_signal": item.expected_signal,
                    "expected_ambiguity": item.expected_ambiguity,
                    "verdict": str(item.assessment.verdict),
                    "score": item.assessment.score,
                    "run_state": str(item.run_state),
                    "fingerprint": item.fingerprint,
                    "flags": [
                        finding.code.value
                        for finding in item.assessment.findings
                        if finding.level is FindingLevel.FLAG
                    ],
                    "data_gaps": item.assessment.data_gaps,
                }
                for item in self.records
            ],
        }


def load_reference_run(path: Path) -> ReferenceRun:
    return ReferenceRun.model_validate_json(path.read_text(encoding="utf-8"))


def load_batch(path: Path) -> BatchDataset:
    return BatchDataset.model_validate_json(path.read_text(encoding="utf-8"))


def load_operator(path: Path) -> OperatorRecord:
    return OperatorDataset.model_validate_json(path.read_text(encoding="utf-8")).operator


def _parcel(polygon: SeedPolygon) -> Parcel:
    return Parcel(
        polygon_id=polygon.id,
        label=polygon.label,
        region=polygon.region,
        province=polygon.province,
        area_ha=polygon.area_ha,
        centroid_lat=polygon.centroid_lat,
        centroid_lon=polygon.centroid_lon,
        geometry=polygon.geometry,
    )


def _supplier(legality: LegalityRecord) -> SupplierProfile:
    return SupplierProfile(**legality.model_dump())


def _consignment(record: BatchRecord) -> Consignment:
    return Consignment(**record.consignment.model_dump())


def _operator(operator: OperatorRecord) -> OperatorProfile:
    return OperatorProfile(**operator.model_dump())


def to_input(report: PolygonReport, record: BatchRecord, operator: OperatorRecord) -> AssessmentInput:
    """Map an M1 report + seed record onto the domain input the rubric consumes."""
    return AssessmentInput(
        record_id=record.record_id,
        parcel=_parcel(record.polygon),
        supplier=_supplier(record.legality),
        loss=report.loss,
        hotspots=report.hotspots,
        consignment=_consignment(record),
        operator=_operator(operator),
        source_errors=list(report.errors),
    )


def assess_record(
    report: PolygonReport,
    record: BatchRecord,
    operator: OperatorRecord,
    *,
    retrieved_at: datetime | None = None,
) -> RecordAssessment:
    """Score one record and build its DDS, validating every citation."""
    input = to_input(report, record, operator)
    ledger = build_source_ledger(input, retrieved_at=retrieved_at)
    assessment = assess(input, ledger)
    document = build_dds(input, assessment, ledger)
    validate_citations(document, ledger)
    return RecordAssessment(
        record_id=record.record_id,
        supplier_id=record.supplier_id,
        polygon_id=record.polygon.id,
        expected_archetype=record.expected_archetype,
        expected_signal=record.expected_signal,
        expected_ambiguity=record.expected_ambiguity,
        run_state=state_for_verdict(assessment.verdict),
        assessment=assessment,
        dds=document,
        fingerprint=fingerprint(assessment),
        evidence=ledger.entries,
    )


def assess_reference_run(
    run: ReferenceRun,
    batch: BatchDataset,
    operator: OperatorRecord,
) -> AssessmentBatch:
    """Assess every report in an M1 run against the matching seed record."""
    by_polygon = {record.polygon.id: record for record in batch.records}
    records: list[RecordAssessment] = []
    missing: list[str] = []
    for report in run.reports:
        record = by_polygon.get(report.polygon_id)
        if record is None:
            missing.append(report.polygon_id)
            continue
        records.append(assess_record(report, record, operator, retrieved_at=run.started_at))
    if missing:
        raise CoreError(
            "no seed record for polygon(s) "
            + ", ".join(sorted(missing))
            + "; pass --batch with the dataset that contains them"
        )

    verdicts = Counter(str(item.assessment.verdict) for item in records)
    expected = Counter(str(item.expected_archetype) for item in records)
    confusion: dict[str, dict[str, int]] = {
        archetype: {verdict: 0 for verdict in ("compliant", "high_risk", "ambiguous")}
        for archetype in ("compliant", "high_risk", "ambiguous")
    }
    for item in records:
        confusion[str(item.expected_archetype)][str(item.assessment.verdict)] += 1
    signal_coverage = {code.value: 0 for code in FindingCode}
    for item in records:
        for finding in item.assessment.findings:
            if finding.level is FindingLevel.FLAG:
                signal_coverage[finding.code.value] += 1

    return AssessmentBatch(
        reference_run_id=run.run_id,
        record_count=len(records),
        verdict_breakdown={
            verdict: verdicts.get(verdict, 0) for verdict in ("compliant", "high_risk", "ambiguous")
        },
        expected_breakdown={
            archetype: expected.get(archetype, 0) for archetype in ("compliant", "high_risk", "ambiguous")
        },
        confusion=confusion,
        signal_coverage=signal_coverage,
        records=records,
        disclosures=sorted({disclosure for item in records for disclosure in item.dds.disclosures}),
    )


def write_assessment_batch(batch: AssessmentBatch, out_dir: Path) -> list[Path]:
    """Write per-record DDS JSON/XML/evidence plus the aggregate summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in batch.records:
        prefix = out_dir / item.record_id
        dds_json = prefix.with_suffix(".dds.json")
        dds_xml = prefix.with_suffix(".dds.xml")
        evidence_json = prefix.with_suffix(".evidence.json")
        dds_json.write_text(item.dds.to_json(), encoding="utf-8")
        dds_xml.write_text(item.dds.to_xml(), encoding="utf-8")
        evidence_json.write_text(
            json.dumps(
                [entry.model_dump(mode="json") for entry in item.evidence],
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        written.extend([dds_json, dds_xml, evidence_json])
    summary = out_dir / "summary.json"
    summary.write_text(
        json.dumps(batch.summary_payload(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    written.append(summary)
    return written


__all__ = [
    "AssessmentBatch",
    "RecordAssessment",
    "assess_record",
    "assess_reference_run",
    "load_batch",
    "load_operator",
    "load_reference_run",
    "to_input",
    "write_assessment_batch",
]
