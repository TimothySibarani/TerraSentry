"""Controlled vocabulary for the deterministic core.

These names are shared by scoring, the evidence ledger, the DDS builder, and the
future API/agent layers. They are deliberately ``StrEnum`` so they serialize to
stable strings in JSON, XML, and Postgres.
"""

from __future__ import annotations

from enum import StrEnum


class Verdict(StrEnum):
    """Outcome of the deterministic rubric for one supplier/parcel."""

    COMPLIANT = "compliant"
    HIGH_RISK = "high_risk"
    AMBIGUOUS = "ambiguous"


class RiskLevel(StrEnum):
    """EUDR risk language derived from the verdict."""

    NEGLIGIBLE = "negligible"
    NON_NEGLIGIBLE = "non_negligible"


class RunState(StrEnum):
    """Lifecycle of an assessment run (architecture run-state machine)."""

    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_MORE_DATA = "needs_more_data"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETE = "complete"
    FAILED = "failed"


class RunEvent(StrEnum):
    """Events that drive the run-state machine."""

    START = "start"
    REQUIRE_MORE_DATA = "require_more_data"
    FLAG_FOR_REVIEW = "flag_for_review"
    APPROVE = "approve"
    OVERRIDE = "override"
    COMPLETE = "complete"
    FAIL = "fail"
    RETRY = "retry"


class FindingCode(StrEnum):
    """Deterministic signals the rubric evaluates."""

    DEFORESTATION_LOSS = "deforestation_loss"
    FIRE_CLUSTER = "fire_cluster"
    LEGAL_PERMIT = "legal_permit"
    AREA_MISMATCH = "area_mismatch"
    CERTIFICATION = "certification"


class FindingLevel(StrEnum):
    """Strength of a signal: a flag is above threshold, borderline is near it."""

    CLEAR = "clear"
    BORDERLINE = "borderline"
    FLAG = "flag"


class EvidenceSource(StrEnum):
    """Where a ledger entry came from."""

    GFW = "global_forest_watch"
    FIRMS = "nasa_firms"
    LEGALITY = "legality_dataset"
    CONCESSION = "concession_dataset"
    CONSIGNMENT = "consignment_dataset"
    OPERATOR = "operator_dataset"
    RUBRIC = "deterministic_rubric"


class Decision(StrEnum):
    """Human decision recorded on the HITL branch."""

    APPROVE = "approve"
    OVERRIDE = "override"
