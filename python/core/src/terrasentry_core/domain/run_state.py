"""The run-state machine, enforced in code.

Mirrors the diagram in ``docs/architecture.md`` section 6:

    queued -> running -> complete
                 |  \\
                 |   -> needs_more_data (retryable)
                 v
            awaiting_review -> (approve | override) -> complete
                 |
                 v
              failed -> retry / manual

``advance`` is the only way to move a run between states; anything undeclared
raises :class:`~terrasentry_core.errors.InvalidTransitionError`.
"""

from __future__ import annotations

from terrasentry_core.domain.enums import Decision, RunEvent, RunState, Verdict
from terrasentry_core.errors import InvalidTransitionError

_TRANSITIONS: dict[RunState, dict[RunEvent, RunState]] = {
    RunState.QUEUED: {RunEvent.START: RunState.RUNNING},
    RunState.RUNNING: {
        RunEvent.COMPLETE: RunState.COMPLETE,
        RunEvent.REQUIRE_MORE_DATA: RunState.NEEDS_MORE_DATA,
        RunEvent.FLAG_FOR_REVIEW: RunState.AWAITING_REVIEW,
        RunEvent.FAIL: RunState.FAILED,
    },
    RunState.NEEDS_MORE_DATA: {
        RunEvent.START: RunState.RUNNING,
        RunEvent.FAIL: RunState.FAILED,
    },
    RunState.AWAITING_REVIEW: {
        RunEvent.APPROVE: RunState.COMPLETE,
        RunEvent.OVERRIDE: RunState.COMPLETE,
        RunEvent.FAIL: RunState.FAILED,
    },
    RunState.FAILED: {RunEvent.RETRY: RunState.QUEUED},
    RunState.COMPLETE: {},
}


def advance(state: RunState, event: RunEvent) -> RunState:
    """Return the next state for ``state``/``event`` or raise."""
    allowed = _TRANSITIONS[state]
    if event not in allowed:
        raise InvalidTransitionError(str(state), str(event))
    return allowed[event]


def decision_event(decision: Decision) -> RunEvent:
    """Map a human HITL decision onto the state-machine event that records it."""
    if decision is Decision.APPROVE:
        return RunEvent.APPROVE
    return RunEvent.OVERRIDE


def state_for_verdict(verdict: Verdict) -> RunState:
    """State a run reaches after scoring: only a compliant verdict releases without a person.

    Ambiguous and high-risk results both wait for a human decision, so no adverse action
    (a vendor block in the ERP) is ever taken by the rubric alone.
    """
    if verdict is Verdict.COMPLIANT:
        return RunState.COMPLETE
    return RunState.AWAITING_REVIEW
