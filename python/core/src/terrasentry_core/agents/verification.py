"""Independent verification: deterministic re-derivation, then an LLM review.

The deterministic checks are the hard gate. They re-derive every metric from the
raw GFW/FIRMS/synthetic data and re-validate every DDS citation, so a tampered or
diverged candidate is rejected even without model access. The LLM review then
challenges the narrative. Both run before the writer node may release the DDS.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from terrasentry_core.assessment.pipeline import RecordAssessment
from terrasentry_core.dds import validate_citations
from terrasentry_core.domain.enums import FindingCode, FindingLevel
from terrasentry_core.domain.models import Finding
from terrasentry_core.errors import LedgerLookupError, UncitedClaimError
from terrasentry_core.evidence import EvidenceLedger
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.scoring import RubricConfig
from terrasentry_core.seed.schemas import BatchRecord, ExpectedSignal
from terrasentry_core.tools.sources import PolygonSources

ChallengeKind = Literal[
    "missing_source",
    "metric_mismatch",
    "citation_failure",
    "design_mismatch",
    "llm_review",
]
ChallengeSeverity = Literal["info", "warning", "error"]

_SIGNAL_FINDINGS: dict[ExpectedSignal, FindingCode] = {
    "deforestation": FindingCode.DEFORESTATION_LOSS,
    "fire": FindingCode.FIRE_CLUSTER,
    "legal": FindingCode.LEGAL_PERMIT,
}


class VerificationChallenge(BaseModel):
    """One issue the verifier raised, with what it expected and observed."""

    kind: ChallengeKind
    severity: ChallengeSeverity
    detail: str
    source: str = "deterministic"
    evidence_ids: list[str] = Field(default_factory=list)
    expected: str | None = None
    observed: str | None = None


class VerificationReport(BaseModel):
    """Outcome of the independent verification step; only accepted runs write."""

    accepted: bool
    checked_claims: list[str] = Field(default_factory=list)
    challenges: list[VerificationChallenge] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    llm_reviewed: bool = False
    model_id: str | None = None

    @property
    def errors(self) -> list[VerificationChallenge]:
        return [challenge for challenge in self.challenges if challenge.severity == "error"]


def _polygon_report(record: BatchRecord, sources: PolygonSources) -> PolygonReport:
    polygon = record.polygon
    return PolygonReport(
        polygon_id=polygon.id,
        label=polygon.label,
        region=polygon.region,
        archetype=polygon.archetype,
        area_ha=polygon.area_ha,
        loss=sources.loss,
        hotspots=sources.hotspots,
        errors=list(sources.errors),
    )


def _derived_metrics(
    record: BatchRecord,
    sources: PolygonSources,
    config: RubricConfig,
) -> dict[FindingCode, dict[str, float | int | str]]:
    """Recompute the metric values the rubric claims, from the raw sources."""
    parcel = record.polygon
    supplier = record.legality
    derived: dict[FindingCode, dict[str, float | int | str]] = {}
    if sources.loss is not None:
        post_cutoff = round(
            sum(item.loss_ha for item in sources.loss.by_year if item.year >= config.cutoff_year),
            4,
        )
        ratio = round(post_cutoff / parcel.area_ha, 4) if parcel.area_ha > 0 else 0.0
        derived[FindingCode.DEFORESTATION_LOSS] = {
            "post_cutoff_loss_ha": post_cutoff,
            "loss_ratio": ratio,
        }
    if sources.hotspots is not None:
        derived[FindingCode.FIRE_CLUSTER] = {
            "detection_count": sources.hotspots.detection_count,
            "total_frp": sources.hotspots.total_frp,
        }
    derived[FindingCode.LEGAL_PERMIT] = {
        "permit_status": supplier.permit_status,
        "sanction_count": len(supplier.sanctions),
        "has_hgu": supplier.hgu_number is not None,
        "has_pbp": supplier.pbp_number is not None,
    }
    derived[FindingCode.AREA_MISMATCH] = {
        "concession_area_ha": supplier.concession_area_ha,
        "plot_area_ha": parcel.area_ha,
    }
    derived[FindingCode.CERTIFICATION] = {
        "certifications": ",".join(supplier.certifications),
    }
    return derived


def _metric_challenges(
    candidate: RecordAssessment,
    record: BatchRecord,
    sources: PolygonSources,
    config: RubricConfig,
) -> tuple[list[VerificationChallenge], list[str]]:
    challenges: list[VerificationChallenge] = []
    checked: list[str] = []
    findings = {finding.code: finding for finding in candidate.assessment.findings}
    for code, expected_metrics in _derived_metrics(record, sources, config).items():
        label = code.value
        finding = findings.get(code)
        if finding is None:
            challenges.append(
                VerificationChallenge(
                    kind="metric_mismatch",
                    severity="error",
                    detail=f"candidate has no {label} finding although its source data is present",
                )
            )
            continue
        for key, expected in expected_metrics.items():
            observed = finding.metrics.get(key)
            if observed != expected:
                challenges.append(
                    VerificationChallenge(
                        kind="metric_mismatch",
                        severity="error",
                        detail=f"{label}.{key} disagrees with the raw source data",
                        evidence_ids=list(finding.evidence_ids),
                        expected=str(expected),
                        observed=str(observed),
                    )
                )
        checked.append(f"metric.{label}")
    return challenges, checked


def _source_challenges(sources: PolygonSources) -> list[VerificationChallenge]:
    challenges: list[VerificationChallenge] = []
    if sources.loss is None:
        challenges.append(
            VerificationChallenge(
                kind="missing_source",
                severity="warning",
                detail=f"GFW tree cover loss is unavailable for {sources.polygon_id}",
            )
        )
    if sources.hotspots is None:
        challenges.append(
            VerificationChallenge(
                kind="missing_source",
                severity="warning",
                detail=f"NASA FIRMS hotspots are unavailable for {sources.polygon_id}",
            )
        )
    for error in sources.errors:
        challenges.append(
            VerificationChallenge(
                kind="missing_source",
                severity="warning",
                detail=f"source error: {error}",
            )
        )
    return challenges


def _design_challenges(
    candidate: RecordAssessment, record: BatchRecord, findings: dict[FindingCode, Finding]
) -> tuple[list[VerificationChallenge], list[str]]:
    """Cross-check the seeded design labels against what the sources showed."""
    challenges: list[VerificationChallenge] = []
    checked: list[str] = []
    verdict = candidate.assessment.verdict.value
    if record.expected_archetype != verdict:
        challenges.append(
            VerificationChallenge(
                kind="design_mismatch",
                severity="warning",
                detail="seeded archetype and observed verdict differ; calibrate the rubric or the seed",
                expected=record.expected_archetype,
                observed=verdict,
            )
        )
    checked.append("design.archetype")
    if record.expected_signal is not None:
        code = _SIGNAL_FINDINGS[record.expected_signal]
        finding = findings.get(code)
        level = finding.level if finding is not None else None
        if level is not FindingLevel.FLAG:
            challenges.append(
                VerificationChallenge(
                    kind="design_mismatch",
                    severity="warning",
                    detail=f"seeded {record.expected_signal} signal is not a flag in the source data",
                    expected="flag",
                    observed=str(level),
                )
            )
        checked.append("design.signal")
    if record.expected_ambiguity is not None and verdict != "ambiguous":
        challenges.append(
            VerificationChallenge(
                kind="design_mismatch",
                severity="warning",
                detail=f"seeded ambiguity {record.expected_ambiguity!r} did not produce an ambiguous verdict",
                expected="ambiguous",
                observed=verdict,
            )
        )
        checked.append("design.ambiguity")
    return challenges, checked


def code_checks(
    candidate: RecordAssessment,
    record: BatchRecord,
    sources: PolygonSources,
    *,
    retrieved_at: datetime | None = None,
    config: RubricConfig | None = None,
) -> VerificationReport:
    """Re-derive the candidate from raw sources and return the hard-gate report."""
    resolved = config or RubricConfig.default()
    if candidate.record_id != record.record_id:
        raise ValueError(f"candidate {candidate.record_id!r} does not match record {record.record_id!r}")
    challenges = _source_challenges(sources)
    checked = ["sources.completeness"]

    try:
        validate_citations(candidate.dds, EvidenceLedger.from_entries(candidate.evidence))
        checked.append("dds.citations")
    except (UncitedClaimError, LedgerLookupError) as exc:
        challenges.append(
            VerificationChallenge(
                kind="citation_failure",
                severity="error",
                detail=f"DDS citation validation failed: {exc}",
            )
        )

    metric_challenges, metric_checked = _metric_challenges(candidate, record, sources, resolved)
    challenges.extend(metric_challenges)
    checked.extend(metric_checked)

    findings = {finding.code: finding for finding in candidate.assessment.findings}
    design_challenges, design_checked = _design_challenges(candidate, record, findings)
    challenges.extend(design_challenges)
    checked.extend(design_checked)

    accepted = not any(challenge.severity == "error" for challenge in challenges)
    return VerificationReport(
        accepted=accepted,
        checked_claims=checked,
        challenges=challenges,
        notes=[
            f"deterministic re-derivation accepted={accepted}",
            f"retrieved_at={retrieved_at.isoformat() if retrieved_at else 'unset'}",
        ],
    )


def merge_reports(
    deterministic: VerificationReport,
    review: VerificationReport,
    *,
    model_id: str | None = None,
) -> VerificationReport:
    """Combine the deterministic gate with the LLM review; errors keep their veto."""
    challenges = [*deterministic.challenges, *review.challenges]
    accepted = (
        deterministic.accepted
        and review.accepted
        and not any(challenge.severity == "error" for challenge in challenges)
    )
    return VerificationReport(
        accepted=accepted,
        checked_claims=sorted({*deterministic.checked_claims, *review.checked_claims}),
        challenges=challenges,
        notes=[*deterministic.notes, *review.notes],
        llm_reviewed=True,
        model_id=model_id,
    )


__all__ = [
    "VerificationChallenge",
    "VerificationReport",
    "code_checks",
    "merge_reports",
]
