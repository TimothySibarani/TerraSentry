"""Deterministic rubric: the model never computes the score.

The rubric is a pure, config-driven rule table over structured tool outputs.
``assess`` writes rubric-derived claims (metrics, per-finding points, score,
verdict) into the supplied :class:`EvidenceLedger` so the full decision chain is
auditable, then returns an :class:`Assessment` whose findings cite those entries.

Determinism: no clock, no network, no randomness. The same
:class:`AssessmentInput` and config always produce the same findings, score,
verdict, and content-hashed evidence ids. Tune ``RubricConfig`` (M6 calibration)
instead of editing rule code.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from terrasentry_core.domain.enums import (
    EvidenceSource,
    FindingCode,
    FindingLevel,
    RiskLevel,
    Verdict,
)
from terrasentry_core.domain.models import Assessment, AssessmentInput, Finding
from terrasentry_core.evidence import EvidenceLedger

RUBRIC_VERSION = "1.0.0"

#: EUDR reference date: products must come from land not deforested after 2020-12-31.
EUDR_CUTOFF_YEAR = 2021


class RubricConfig(BaseModel):
    """Every knob the deterministic rubric reads; versioned for audit."""

    version: str = RUBRIC_VERSION
    cutoff_year: int = EUDR_CUTOFF_YEAR

    loss_flag_ha: float = 4.0
    loss_flag_ratio: float = 0.01
    loss_borderline_ha: float = 0.5

    hotspot_flag_count: int = 5
    hotspot_borderline_count: int = 1
    hotspot_recent_days: int = 7

    area_mismatch_tolerance: float = 0.05

    legal_flag_points: int = 60
    legal_borderline_points: int = 20
    loss_flag_points: int = 50
    loss_borderline_points: int = 15
    fire_flag_points: int = 30
    fire_borderline_points: int = 10
    area_mismatch_points: int = 15
    certification_credit: int = 10

    high_risk_threshold: int = 30
    legal_flag_is_critical: bool = True

    @classmethod
    def default(cls) -> RubricConfig:
        return cls()


def _round(value: float) -> float:
    return round(value, 4)


def _metric_finding(
    ledger: EvidenceLedger,
    *,
    code: FindingCode,
    level: FindingLevel,
    points: int,
    detail: str,
    metrics: dict[str, float | int | str],
    source_ids: list[str],
    input: AssessmentInput,
    config: RubricConfig,
    mitigating: bool = False,
) -> Finding:
    entry = ledger.record(
        claim=f"rubric.finding.{code.value}",
        value={
            "level": level.value,
            "points": points,
            "detail": detail,
            "metrics": metrics,
            "rubric_version": config.version,
        },
        source=EvidenceSource.RUBRIC,
        artifact={"supplier_id": input.supplier.supplier_id, "polygon_id": input.parcel.polygon_id},
        synthetic=True,
        retrieved_at=_source_timestamp(input),
    )
    return Finding(
        code=code,
        level=level,
        points=points,
        detail=detail,
        metrics=metrics,
        evidence_ids=[*source_ids, entry.evidence_id],
        mitigating=mitigating,
    )


def _source_timestamp(input: AssessmentInput):
    timestamps = [
        result.fetched_at
        for result in (input.loss, input.hotspots)
        if result is not None and result.fetched_at is not None
    ]
    return max(timestamps) if timestamps else None


def _evaluate_loss(
    input: AssessmentInput, ledger: EvidenceLedger, config: RubricConfig
) -> tuple[Finding | None, list[str]]:
    loss = input.loss
    if loss is None:
        return None, ["gfw:no data"]
    post_cutoff = sum(item.loss_ha for item in loss.by_year if item.year >= config.cutoff_year)
    post_cutoff = _round(post_cutoff)
    ratio = _round(post_cutoff / input.parcel.area_ha) if input.parcel.area_ha > 0 else 0.0
    flagged_by_area = post_cutoff >= config.loss_flag_ha
    flagged_by_ratio = post_cutoff >= config.loss_borderline_ha and ratio >= config.loss_flag_ratio
    if flagged_by_area or flagged_by_ratio:
        level, points = FindingLevel.FLAG, config.loss_flag_points
    elif post_cutoff >= config.loss_borderline_ha:
        level, points = FindingLevel.BORDERLINE, config.loss_borderline_points
    else:
        level, points = FindingLevel.CLEAR, 0
    detail = (
        f"post-{config.cutoff_year} tree cover loss {post_cutoff:.2f} ha "
        f"({ratio:.2%} of plot) in {loss.date_window}"
    )
    return (
        _metric_finding(
            ledger,
            code=FindingCode.DEFORESTATION_LOSS,
            level=level,
            points=points,
            detail=detail,
            metrics={"post_cutoff_loss_ha": post_cutoff, "loss_ratio": ratio},
            source_ids=[*ledger.ids_for("loss.total_loss_ha"), *ledger.ids_for("loss.by_year")],
            input=input,
            config=config,
        ),
        [],
    )


def _evaluate_fire(
    input: AssessmentInput, ledger: EvidenceLedger, config: RubricConfig
) -> tuple[Finding | None, list[str]]:
    hotspots = input.hotspots
    if hotspots is None:
        return None, ["firms:no data"]
    count = hotspots.detection_count
    days_since_last: int | None = None
    if hotspots.detections:
        last = max(item.acq_date for item in hotspots.detections)
        days_since_last = max((hotspots.window_end - last).days, 0)
    recent = days_since_last is not None and days_since_last <= config.hotspot_recent_days
    if count >= config.hotspot_flag_count or (count > 0 and recent):
        level, points = FindingLevel.FLAG, config.fire_flag_points
    elif count >= config.hotspot_borderline_count:
        level, points = FindingLevel.BORDERLINE, config.fire_borderline_points
    else:
        level, points = FindingLevel.CLEAR, 0
    detail = f"{count} fire detection(s), {hotspots.total_frp:.1f} MW FRP, window {hotspots.date_window}" + (
        f"; last detection {days_since_last}d before window end" if days_since_last is not None else ""
    )
    metrics: dict[str, float | int | str] = {"detection_count": count, "total_frp": hotspots.total_frp}
    if days_since_last is not None:
        metrics["days_since_last_detection"] = days_since_last
    return (
        _metric_finding(
            ledger,
            code=FindingCode.FIRE_CLUSTER,
            level=level,
            points=points,
            detail=detail,
            metrics=metrics,
            source_ids=[
                *ledger.ids_for("hotspots.detection_count"),
                *ledger.ids_for("hotspots.total_frp"),
                *ledger.ids_for("hotspots.detections"),
            ],
            input=input,
            config=config,
        ),
        [],
    )


def _evaluate_legal(input: AssessmentInput, ledger: EvidenceLedger, config: RubricConfig) -> Finding:
    supplier = input.supplier
    missing_permit = supplier.hgu_number is None and supplier.pbp_number is None
    permit_bad = supplier.permit_status != "active" or bool(supplier.sanctions)
    if permit_bad:
        level, points = FindingLevel.FLAG, config.legal_flag_points
        detail = (
            f"permit status {supplier.permit_status!r} with {len(supplier.sanctions)} sanction(s) "
            f"on the synthetic legality record"
        )
    elif missing_permit:
        level, points = FindingLevel.BORDERLINE, config.legal_borderline_points
        detail = "synthetic legality record lists neither an HGU nor a PBPH permit"
    else:
        level, points = FindingLevel.CLEAR, 0
        detail = f"permit status {supplier.permit_status!r}, HGU/PBPH present, no sanctions"
    return _metric_finding(
        ledger,
        code=FindingCode.LEGAL_PERMIT,
        level=level,
        points=points,
        detail=detail,
        metrics={
            "permit_status": supplier.permit_status,
            "sanction_count": len(supplier.sanctions),
            "has_hgu": supplier.hgu_number is not None,
            "has_pbp": supplier.pbp_number is not None,
        },
        source_ids=[
            *ledger.ids_for("supplier.permit_status"),
            *ledger.ids_for("supplier.sanctions"),
            *ledger.ids_for("supplier.hgu_pbp"),
        ],
        input=input,
        config=config,
    )


def _evaluate_area_mismatch(input: AssessmentInput, ledger: EvidenceLedger, config: RubricConfig) -> Finding:
    supplier = input.supplier
    parcel = input.parcel
    floor = parcel.area_ha * (1.0 - config.area_mismatch_tolerance)
    mismatch = supplier.concession_area_ha < floor
    level = FindingLevel.BORDERLINE if mismatch else FindingLevel.CLEAR
    points = config.area_mismatch_points if mismatch else 0
    detail = (
        f"concession {supplier.concession_area_ha:.1f} ha is smaller than plot {parcel.area_ha:.2f} ha"
        if mismatch
        else f"concession {supplier.concession_area_ha:.1f} ha covers plot {parcel.area_ha:.2f} ha"
    )
    return _metric_finding(
        ledger,
        code=FindingCode.AREA_MISMATCH,
        level=level,
        points=points,
        detail=detail,
        metrics={
            "concession_area_ha": supplier.concession_area_ha,
            "plot_area_ha": parcel.area_ha,
        },
        source_ids=[
            *ledger.ids_for("supplier.concession_area_ha"),
            *ledger.ids_for("parcel.area_ha"),
        ],
        input=input,
        config=config,
    )


def _evaluate_certification(input: AssessmentInput, ledger: EvidenceLedger, config: RubricConfig) -> Finding:
    certifications = input.supplier.certifications
    if certifications:
        level, points = FindingLevel.CLEAR, -config.certification_credit
        detail = f"certifications on file: {', '.join(certifications)}"
    else:
        level, points = FindingLevel.CLEAR, 0
        detail = "no sustainability certification on the synthetic legality record"
    return _metric_finding(
        ledger,
        code=FindingCode.CERTIFICATION,
        level=level,
        points=points,
        detail=detail,
        metrics={"certifications": ",".join(certifications)},
        source_ids=ledger.ids_for("supplier.certifications"),
        input=input,
        config=config,
        mitigating=bool(certifications),
    )


def _decide(
    findings: list[Finding],
    score: int,
    config: RubricConfig,
    data_gaps: list[str],
) -> Verdict:
    legal_flag = any(
        finding.code is FindingCode.LEGAL_PERMIT and finding.level is FindingLevel.FLAG
        for finding in findings
    )
    if legal_flag and config.legal_flag_is_critical:
        return Verdict.HIGH_RISK
    flagged = [finding for finding in findings if finding.level is FindingLevel.FLAG]
    borderline = [finding for finding in findings if finding.level is FindingLevel.BORDERLINE]
    mitigating = [finding for finding in findings if finding.mitigating]
    if flagged and mitigating:
        # A confirmed flag plus a positive assurance is exactly the PRD conflict case.
        return Verdict.AMBIGUOUS
    if flagged:
        return Verdict.HIGH_RISK
    if score >= config.high_risk_threshold:
        return Verdict.HIGH_RISK
    if borderline:
        return Verdict.AMBIGUOUS
    if data_gaps:
        return Verdict.AMBIGUOUS
    return Verdict.COMPLIANT


def assess(
    input: AssessmentInput,
    ledger: EvidenceLedger,
    *,
    config: RubricConfig | None = None,
) -> Assessment:
    """Score one supplier/parcel deterministically and record the decision chain.

    The caller must have recorded source claims first (``build_source_ledger``);
    missing source data is reported as a data gap rather than raising, so batch
    runs keep moving on partial failures.
    """
    config = config or RubricConfig.default()
    findings: list[Finding] = []
    data_gaps: list[str] = list(dict.fromkeys(input.source_errors))

    legal = _evaluate_legal(input, ledger, config)
    findings.append(legal)
    loss_finding, loss_gaps = _evaluate_loss(input, ledger, config)
    if loss_finding is not None:
        findings.append(loss_finding)
    data_gaps.extend(loss_gaps)
    fire_finding, fire_gaps = _evaluate_fire(input, ledger, config)
    if fire_finding is not None:
        findings.append(fire_finding)
    data_gaps.extend(fire_gaps)
    findings.append(_evaluate_area_mismatch(input, ledger, config))
    findings.append(_evaluate_certification(input, ledger, config))

    score = max(0, min(100, sum(finding.points for finding in findings)))
    verdict = _decide(findings, score, config, data_gaps)
    risk_level = RiskLevel.NEGLIGIBLE if verdict is Verdict.COMPLIANT else RiskLevel.NON_NEGLIGIBLE

    score_entry = ledger.record(
        claim="rubric.score",
        value={
            "score": score,
            "verdict": verdict.value,
            "rubric_version": config.version,
            "config": config.model_dump(mode="json"),
        },
        source=EvidenceSource.RUBRIC,
        artifact={"supplier_id": input.supplier.supplier_id, "polygon_id": input.parcel.polygon_id},
        synthetic=True,
        retrieved_at=_source_timestamp(input),
    )
    verdict_entry = ledger.record(
        claim="rubric.verdict",
        value=verdict.value,
        source=EvidenceSource.RUBRIC,
        artifact={
            "supplier_id": input.supplier.supplier_id,
            "polygon_id": input.parcel.polygon_id,
            "rubric_version": config.version,
        },
        synthetic=True,
        retrieved_at=_source_timestamp(input),
    )

    citations: dict[str, list[str]] = {
        "rubric.score": [score_entry.evidence_id],
        "rubric.verdict": [verdict_entry.evidence_id],
    }
    for finding in findings:
        citations[f"rubric.finding.{finding.code.value}"] = list(finding.evidence_ids)

    disclosures = [input.supplier.disclosure] if input.supplier.disclosure else []
    return Assessment(
        record_id=input.record_id,
        supplier_id=input.supplier.supplier_id,
        polygon_id=input.parcel.polygon_id,
        rubric_version=config.version,
        score=score,
        verdict=verdict,
        risk_level=risk_level,
        findings=findings,
        citations=citations,
        disclosures=disclosures,
        data_gaps=data_gaps,
    )


def fingerprint(assessment: Assessment) -> str:
    """Content hash of an assessment; equal fingerprints mean equal outcomes."""
    payload: dict[str, Any] = assessment.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
