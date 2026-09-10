"""Typed failures for the deterministic core.

Mirrors the ``terrasentry_integrations.errors`` style: every failure the core can
raise has a named type so callers (agents, API, CLI) can branch on it instead of
parsing messages.
"""

from __future__ import annotations


class CoreError(Exception):
    """Base class for terrasentry-core failures."""


class InvalidTransitionError(CoreError):
    """A run-state event is not legal from the current state."""

    def __init__(self, state: str, event: str) -> None:
        super().__init__(f"event {event!r} is not allowed from state {state!r}")
        self.state = state
        self.event = event


class LedgerLookupError(CoreError):
    """A citation references an evidence id that is not in the ledger."""

    def __init__(self, evidence_id: str) -> None:
        super().__init__(f"evidence id {evidence_id!r} is not present in the ledger")
        self.evidence_id = evidence_id


class UncitedClaimError(CoreError):
    """A claim that must be traceable has no ledger citation."""

    def __init__(self, claim: str) -> None:
        super().__init__(f"claim {claim!r} has no evidence citation")
        self.claim = claim


class InvalidGeometryError(CoreError):
    """A parcel geometry cannot be represented in the DDS geolocation payload."""

    def __init__(self, polygon_id: str, reason: str) -> None:
        super().__init__(f"parcel {polygon_id!r} geometry is invalid: {reason}")
        self.polygon_id = polygon_id
        self.reason = reason


class MissingAssessmentInputError(CoreError):
    """An assessment was requested without the source data it requires."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail
