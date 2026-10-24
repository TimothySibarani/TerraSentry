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
import re
import unicodedata
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

RUBRIC_VERSION = "1.2.0"

#: EUDR reference date: products must come from land not deforested after 2020-12-31.
EUDR_CUTOFF_YEAR = 2021


class RubricConfig(BaseModel):
    """Every knob the deterministic rubric reads; versioned for audit."""

    version: str = RUBRIC_VERSION
    cutoff_year: int = EUDR_CUTOFF_YEAR

    loss_flag_ha: float = 4.0
    loss_flag_ratio: float = 0.01
    loss_borderline_ha: float = 0.5
    #: Share of the plot a supplier's own wood-fibre concession must cover before flagged loss is
    #: treated as a possible plantation harvest (sent to a person) instead of a deforestation flag.
    harvest_overlap_ratio: float = 0.9

    hotspot_flag_count: int = 5
    hotspot_borderline_count: int = 1
    hotspot_recent_days: int = 7

    area_mismatch_tolerance: float = 0.05

    protected_flag_points: int = 60
    moratorium_flag_ha: float = 0.1
    moratorium_flag_points: int = 60
    moratorium_borderline_points: int = 20
    peat_borderline_points: int = 10
    concession_flag_points: int = 60
    concession_borderline_points: int = 20

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
        synthetic=False,
        provenance="derived",
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


def _harvest_context(input: AssessmentInput, config: RubricConfig) -> str | None:
    """Why flagged loss may be harvest of the supplier's own fibre plantation, else ``None``.

    Hansen loss is aggregate, not located within the plot, so this is an approximation: the plot
    must be a wood consignment lying (almost) wholly inside a wood-fibre concession whose holder
    matches the declared holder. It never clears the loss; it routes it to a person.
    """
    layers, consignment, area = input.layers, input.consignment, input.parcel.area_ha
    if layers is None or consignment is None or consignment.commodity != "wood" or area <= 0:
        return None
    layer = next(
        (
            item
            for item in layers.layers
            if item.name == "wood_fiber_concessions" and item.status == "success"
        ),
        None,
    )
    if layer is None:
        return None
    declared = input.supplier.declared_holder or input.supplier.legal_name
    held_ha = min(
        layer.overlap_ha,
        sum(
            feature.overlap_ha
            for feature in layer.features
            if holder_matches(feature.properties.get("company"), declared)
        ),
    )
    if held_ha / area < config.harvest_overlap_ratio:
        return None
    return (
        f"{held_ha:.2f} ha ({held_ha / area:.0%}) of the plot lies in a wood-fibre concession held by "
        f"{declared}"
    )


def _evaluate_loss(
    input: AssessmentInput, ledger: EvidenceLedger, config: RubricConfig
) -> tuple[Finding | None, list[str]]:
    loss = input.loss
    if loss is None:
        return None, ["gfw:no data"]
    post_cutoff = sum(item.loss_ha for item in loss.by_year if item.year >= config.cutoff_year)
    ratio = post_cutoff / input.parcel.area_ha if input.parcel.area_ha > 0 else 0.0
    flagged_by_area = post_cutoff >= config.loss_flag_ha
    flagged_by_ratio = post_cutoff >= config.loss_borderline_ha and ratio >= config.loss_flag_ratio
    harvest = _harvest_context(input, config) if flagged_by_area or flagged_by_ratio else None
    if harvest is not None:
        level, points = FindingLevel.BORDERLINE, config.loss_borderline_points
    elif flagged_by_area or flagged_by_ratio:
        level, points = FindingLevel.FLAG, config.loss_flag_points
    elif post_cutoff >= config.loss_borderline_ha:
        level, points = FindingLevel.BORDERLINE, config.loss_borderline_points
    else:
        level, points = FindingLevel.CLEAR, 0
    detail = (
        f"post-{config.cutoff_year} tree cover loss {post_cutoff:.2f} ha "
        f"({ratio:.2%} of plot) in {loss.date_window}"
    )
    metrics: dict[str, float | int | str] = {"post_cutoff_loss_ha": post_cutoff, "loss_ratio": ratio}
    if harvest is not None:
        detail += (
            f"; possible plantation harvest, needs review: {harvest}. Loss is not located within the plot, "
            "so a person must confirm harvest rather than conversion of forest"
        )
        metrics["harvest_candidate"] = 1
    return (
        _metric_finding(
            ledger,
            code=FindingCode.DEFORESTATION_LOSS,
            level=level,
            points=points,
            detail=detail,
            metrics=metrics,
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
    expired = (
        supplier.permit_expiry is not None
        and input.assessment_date is not None
        and supplier.permit_expiry < input.assessment_date
    )
    permit_bad = expired or supplier.permit_status in {"expired", "suspended"} or bool(supplier.sanctions)
    if permit_bad:
        level, points = FindingLevel.FLAG, config.legal_flag_points
        detail = (
            f"permit status {supplier.permit_status!r} with {len(supplier.sanctions)} sanction(s) "
            f"on the {supplier.provenance} legality record; expiry {supplier.permit_expiry}"
        )
    elif input.parcel.country != "ID" and missing_permit:
        level, points = FindingLevel.CLEAR, 0
        detail = (
            "Indonesian HGU/PBPH checks do not apply to this production country; local legality is unverified"
        )
    elif missing_permit:
        level, points = FindingLevel.BORDERLINE, config.legal_borderline_points
        detail = "declared legality record lists neither an HGU nor a PBPH permit"
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
            *ledger.ids_for("supplier.permit_expiry"),
            *ledger.ids_for("assessment.date"),
            *ledger.ids_for("parcel.country"),
            *ledger.ids_for("supplier.sanctions"),
            *ledger.ids_for("supplier.hgu_pbp"),
        ],
        input=input,
        config=config,
    )


def _holder(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFKC", value).casefold()).split())


def concession_commodity(layer_name: str) -> str:
    """Commodity a concession dataset authorises; shared by the rubric and the agent deep dive."""
    return "oil_palm" if layer_name == "oil_palm_concessions" else "wood"


def holder_matches(company: object, declared_holder: str) -> bool | None:
    """Compare a concession company to the declared holder; None when the company is unknown."""
    if not isinstance(company, str) or not company.strip():
        return None
    return _holder(company) == _holder(declared_holder)


def _evaluate_context(
    input: AssessmentInput, ledger: EvidenceLedger, config: RubricConfig
) -> tuple[list[Finding], list[str]]:
    from terrasentry_integrations.sources.gfw_layers import LAYER_DEFINITIONS

    findings: list[Finding] = []
    gaps: list[str] = []
    by_name = {layer.name: layer for layer in input.layers.layers} if input.layers else {}
    for name in LAYER_DEFINITIONS:
        layer = by_name.get(name)
        if layer is None or layer.status == "unavailable":
            gaps.append(f"gfw:{name}:unavailable")
            continue
        if layer.status == "not_applicable":
            continue
        area = layer.overlap_ha
        level, points = FindingLevel.CLEAR, 0
        if name == "protected_areas":
            code = FindingCode.PROTECTED_AREA
            if area > 0:
                level, points = FindingLevel.FLAG, config.protected_flag_points
        elif name == "moratorium":
            code = FindingCode.MORATORIUM
            if area > config.moratorium_flag_ha:
                level, points = FindingLevel.FLAG, config.moratorium_flag_points
            elif area > 0:
                level, points = FindingLevel.BORDERLINE, config.moratorium_borderline_points
        elif name == "peatlands":
            code = FindingCode.PEATLAND
            if area > 0:
                level, points = FindingLevel.BORDERLINE, config.peat_borderline_points
        elif name == "forest_baseline":
            code = FindingCode.FOREST_BASELINE
        else:
            # One strongest concession finding across all three datasets; no double counting.
            continue
        feature_names = [
            str(
                feature.properties.get("name")
                or feature.properties.get("name_eng")
                or feature.properties.get("pippib_en")
                or feature.feature_id
            )
            for feature in layer.features[:3]
        ]
        feature_detail = f"features: {', '.join(feature_names)}; " if feature_names else ""
        findings.append(
            _metric_finding(
                ledger,
                code=code,
                level=level,
                points=points,
                detail=f"{name}: {area:.4f} ha overlap ({layer.dataset}/{layer.version}); "
                + feature_detail
                + (
                    "baseline context only; tree cover loss is assessed separately"
                    if name == "forest_baseline"
                    else "context signal; legality is not registry-verified"
                ),
                metrics={"overlap_ha": area, "dataset": layer.dataset, "version": layer.version},
                source_ids=ledger.ids_for(f"context.{name}"),
                input=input,
                config=config,
            )
        )
    relevant = [
        layer
        for name, layer in by_name.items()
        if name.endswith("_concessions") and layer.status == "success" and layer.overlap_ha > 0
    ]
    if relevant:
        level, points = FindingLevel.CLEAR, 0
        reasons: list[str] = []
        declared = input.supplier.declared_holder or input.supplier.legal_name
        for layer in relevant:
            compatible = input.consignment is not None and input.consignment.commodity == (
                concession_commodity(layer.name)
            )
            if not compatible:
                if level is not FindingLevel.FLAG:
                    level, points = FindingLevel.BORDERLINE, config.concession_borderline_points
                reasons.append(f"commodity conflicts with {layer.name}")
            for feature in layer.features:
                company = feature.properties.get("company")
                matches = holder_matches(company, declared)
                if matches is None:
                    gaps.append(f"gfw:{layer.name}:holder unknown for {feature.feature_id}")
                elif not matches:
                    level, points = FindingLevel.FLAG, config.concession_flag_points
                    reasons.append(
                        f"{layer.dataset}/{feature.feature_id}: holder {company!r} "
                        "differs from declared holder"
                    )
        findings.append(
            _metric_finding(
                ledger,
                code=FindingCode.CONCESSION_CONFLICT,
                level=level,
                points=points,
                detail="; ".join(reasons)
                or "concession holder and commodity match declarations; not registry-verified",
                metrics={f"{layer.name}_overlap_ha": layer.overlap_ha for layer in relevant},
                source_ids=[
                    *ledger.ids_for("supplier.declared_holder"),
                    *ledger.ids_for("consignment.description"),
                    *(
                        evidence_id
                        for layer in relevant
                        for evidence_id in ledger.ids_for(f"context.{layer.name}")
                    ),
                ],
                input=input,
                config=config,
            )
        )
    return findings, gaps


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
        detail = "no sustainability certification on the legality record"
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
    critical_flag = any(
        finding.level is FindingLevel.FLAG
        and (
            finding.code
            in {FindingCode.PROTECTED_AREA, FindingCode.MORATORIUM, FindingCode.CONCESSION_CONFLICT}
            or (finding.code is FindingCode.LEGAL_PERMIT and config.legal_flag_is_critical)
        )
        for finding in findings
    )
    if critical_flag:
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
    context_findings, context_gaps = _evaluate_context(input, ledger, config)
    findings.extend(context_findings)
    data_gaps.extend(context_gaps)
    if input.supplier.permit_expiry is not None and input.assessment_date is None:
        data_gaps.append("legality:assessment date missing for permit expiry")
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
        synthetic=False,
        provenance="derived",
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
        synthetic=False,
        provenance="derived",
        retrieved_at=_source_timestamp(input),
    )

    citations: dict[str, list[str]] = {
        "rubric.score": [score_entry.evidence_id],
        "rubric.verdict": [verdict_entry.evidence_id],
    }
    for finding in findings:
        citations[f"rubric.finding.{finding.code.value}"] = list(finding.evidence_ids)

    disclosures = [input.supplier.disclosure] if input.supplier.disclosure else []
    disclosures.append(
        "Declared permits and holders are not independently verified against a live permit registry."
    )
    if input.supplier.permit_expiry is None:
        disclosures.append("Permit expiry is unknown; an active status does not establish current validity.")
    if input.parcel.country != "ID":
        disclosures.append(
            "Indonesian permit and context layers are not applicable; local legality remains unverified."
        )
    return Assessment(
        record_id=input.record_id,
        assessment_date=input.assessment_date,
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
