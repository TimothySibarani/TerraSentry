"""Independent verification: deterministic re-derivation, then an LLM review.

The deterministic checks are the hard gate. They re-derive every metric from the
raw GFW/FIRMS/synthetic data and re-validate every DDS citation, so a tampered or
diverged candidate is rejected even without model access. The LLM review then
challenges the narrative. Both run before the writer node may release the DDS.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from terrasentry_core.agents.investigation import (
    BASELINE_TOOLS,
    DeepDive,
    required_deep_dives,
    triggering_codes,
)
from terrasentry_core.assessment.pipeline import RecordAssessment, assess_record
from terrasentry_core.dds import validate_citations
from terrasentry_core.domain.enums import FindingCode, FindingLevel
from terrasentry_core.domain.models import Finding
from terrasentry_core.errors import LedgerLookupError, UncitedClaimError
from terrasentry_core.evidence import EvidenceLedger
from terrasentry_core.reference.pipeline import PolygonReport
from terrasentry_core.scoring import RubricConfig
from terrasentry_core.seed.schemas import BatchRecord, ExpectedSignal, OperatorRecord
from terrasentry_core.tools.sources import PolygonSources
from terrasentry_core.tools.trace import TraceStep

ChallengeKind = Literal[
    "missing_source",
    "metric_mismatch",
    "citation_failure",
    "design_mismatch",
    "coverage",
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
        layers=sources.layers,
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
        post_cutoff = sum(item.loss_ha for item in sources.loss.by_year if item.year >= config.cutoff_year)
        ratio = post_cutoff / parcel.area_ha if parcel.area_ha > 0 else 0.0
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
    if record.expected_archetype is None:
        # Submitted plots carry no design labels; there is nothing to cross-check.
        return challenges, checked
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
    operator: OperatorRecord,
    assessment_date: date | None = None,
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

    expected = assess_record(
        _polygon_report(record, sources),
        record,
        operator,
        assessment_date=assessment_date,
        retrieved_at=retrieved_at,
        config=resolved,
    )
    comparisons = {
        "assessment_date": (candidate.assessment_date, expected.assessment_date),
        "assessment": (candidate.assessment, expected.assessment),
        "dds": (candidate.dds, expected.dds),
        "fingerprint": (candidate.fingerprint, expected.fingerprint),
        "run_state": (candidate.run_state, expected.run_state),
        "supplier_id": (candidate.supplier_id, expected.supplier_id),
        "polygon_id": (candidate.polygon_id, expected.polygon_id),
        "source_polygon": (sources.polygon_id, record.polygon.id),
        "evidence": (
            [entry.model_dump(exclude={"retrieved_at", "cached"}) for entry in candidate.evidence],
            [entry.model_dump(exclude={"retrieved_at", "cached"}) for entry in expected.evidence],
        ),
    }
    for claim, (observed, correct) in comparisons.items():
        checked.append(f"outcome.{claim}")
        if observed != correct:
            challenges.append(
                VerificationChallenge(
                    kind="metric_mismatch",
                    severity="error",
                    detail=f"candidate {claim} differs from deterministic re-derivation",
                )
            )

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


def coverage_checks(
    candidate: RecordAssessment, record: BatchRecord, steps: list[TraceStep]
) -> VerificationReport:
    """Reject a candidate whose server-recorded tool steps skipped a required investigation.

    Only ``tool`` steps recorded by server code count, matched on name and ids. Model
    summaries and ``retask`` steps never do. An attempted deep dive whose step reports an
    error counts as covered and leaves an info data-gap note.
    """
    expected_ids = {"polygon_id": record.polygon.id, "supplier_id": record.legality.supplier_id}
    codes = triggering_codes(candidate.assessment.findings)
    deep_dives = required_deep_dives(candidate.assessment.findings)
    # ``tool_start`` steps are written before a call returns, so they prove nothing.
    tool_steps = [step for step in steps if step.kind == "tool" and step.payload.get("event") != "tool_start"]
    challenges: list[VerificationChallenge] = []
    checked: list[str] = []

    def matching(requirement: DeepDive) -> list[TraceStep]:
        wanted = {field: expected_ids[field] for field in requirement.id_fields}
        return [
            step
            for step in tool_steps
            if step.name == requirement.tool and all(step.payload.get(k) == v for k, v in wanted.items())
        ]

    for requirement in [*BASELINE_TOOLS, *sorted(deep_dives, key=lambda item: item.tool)]:
        checked.append(f"coverage.{requirement.tool}")
        expected = ", ".join(f"{field}={expected_ids[field]}" for field in requirement.id_fields)
        found = matching(requirement)
        is_deep_dive = requirement in deep_dives
        if not found:
            reason = (
                f" (required by findings: {', '.join(codes)})" if is_deep_dive else " (baseline screening)"
            )
            challenges.append(
                VerificationChallenge(
                    kind="coverage",
                    severity="error",
                    detail=f"required tool {requirement.tool} was not called{reason}",
                    source="trace",
                    expected=expected,
                    observed="no matching tool step recorded",
                )
            )
        elif is_deep_dive and all(step.payload.get("status") == "error" for step in found):
            challenges.append(
                VerificationChallenge(
                    kind="coverage",
                    severity="info",
                    detail=f"{requirement.tool} was attempted but its sources were unavailable; data gap",
                    source="trace",
                    expected=expected,
                    observed="attempted; status=error",
                )
            )
    accepted = not any(challenge.severity == "error" for challenge in challenges)
    return VerificationReport(
        accepted=accepted,
        checked_claims=checked,
        challenges=challenges,
        notes=[f"coverage accepted={accepted}"],
    )


def merge_coverage(deterministic: VerificationReport, coverage: VerificationReport) -> VerificationReport:
    """Fold the coverage gate into the deterministic report; errors keep their veto."""
    return deterministic.model_copy(
        update={
            "accepted": deterministic.accepted and coverage.accepted,
            "checked_claims": [*deterministic.checked_claims, *coverage.checked_claims],
            "challenges": [*deterministic.challenges, *coverage.challenges],
            "notes": [*deterministic.notes, *coverage.notes],
        }
    )


_EVIDENCE_ID = re.compile(r"EV-[A-Za-z0-9_]+-[0-9a-f]{6,}")
# Kinds the deterministic gate owns; an LLM opinion on them is advisory.
_DETERMINISTIC_KINDS: frozenset[ChallengeKind] = frozenset({"design_mismatch", "coverage"})


def _review_challenge(challenge: VerificationChallenge, ledger_ids: set[str]) -> VerificationChallenge:
    """Stamp an LLM challenge as such; it may only veto when it cites evidence in the ledger."""
    challenge = challenge.model_copy(update={"source": "llm"})
    if challenge.severity != "error":
        return challenge
    cited = {*challenge.evidence_ids, *_EVIDENCE_ID.findall(challenge.detail)}
    if challenge.kind not in _DETERMINISTIC_KINDS and cited and cited <= ledger_ids:
        return challenge.model_copy(update={"evidence_ids": sorted(cited)})
    reason = (
        "the deterministic gate owns this check"
        if challenge.kind in _DETERMINISTIC_KINDS
        else "it cites no evidence id in the ledger"
        if not cited
        else f"it cites unknown evidence {', '.join(sorted(cited - ledger_ids))}"
    )
    return challenge.model_copy(
        update={"severity": "warning", "detail": f"{challenge.detail} [downgraded from error: {reason}]"}
    )


def merge_reports(
    deterministic: VerificationReport,
    review: VerificationReport,
    *,
    ledger_ids: set[str],
    model_id: str | None = None,
) -> VerificationReport:
    """Combine the deterministic gate with the LLM review.

    Only error-severity challenges veto. An LLM error counts only when it cites evidence ids
    that exist in the ledger and is not about a check the deterministic gate already owns;
    otherwise it is kept as a warning. The model's own ``accepted`` flag is not trusted on
    its own, so a rejection always names the challenge that caused it.
    """
    reviewed = [_review_challenge(challenge, ledger_ids) for challenge in review.challenges]
    challenges = [*deterministic.challenges, *reviewed]
    accepted = deterministic.accepted and not any(challenge.severity == "error" for challenge in challenges)
    downgraded = sum(
        1
        for before, after in zip(review.challenges, reviewed, strict=True)
        if before.severity != after.severity
    )
    notes = [*deterministic.notes, *review.notes]
    if downgraded:
        notes.append(f"llm review: {downgraded} uncited or out-of-scope error(s) kept as warnings")
    if not review.accepted and accepted:
        notes.append("llm review set accepted=false without a qualifying error; no veto applied")
    return VerificationReport(
        accepted=accepted,
        checked_claims=sorted({*deterministic.checked_claims, *review.checked_claims}),
        challenges=challenges,
        notes=notes,
        llm_reviewed=True,
        model_id=model_id,
    )


__all__ = [
    "VerificationChallenge",
    "VerificationReport",
    "code_checks",
    "merge_reports",
]
