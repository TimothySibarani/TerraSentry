from __future__ import annotations

import pytest
from terrasentry_core.domain.enums import Decision, RunEvent, RunState, Verdict
from terrasentry_core.domain.run_state import advance, decision_event, state_for_verdict
from terrasentry_core.errors import InvalidTransitionError

VALID_TRANSITIONS = [
    (RunState.QUEUED, RunEvent.START, RunState.RUNNING),
    (RunState.RUNNING, RunEvent.COMPLETE, RunState.COMPLETE),
    (RunState.RUNNING, RunEvent.REQUIRE_MORE_DATA, RunState.NEEDS_MORE_DATA),
    (RunState.RUNNING, RunEvent.FLAG_FOR_REVIEW, RunState.AWAITING_REVIEW),
    (RunState.RUNNING, RunEvent.FAIL, RunState.FAILED),
    (RunState.NEEDS_MORE_DATA, RunEvent.START, RunState.RUNNING),
    (RunState.NEEDS_MORE_DATA, RunEvent.FAIL, RunState.FAILED),
    (RunState.AWAITING_REVIEW, RunEvent.APPROVE, RunState.COMPLETE),
    (RunState.AWAITING_REVIEW, RunEvent.OVERRIDE, RunState.COMPLETE),
    (RunState.FAILED, RunEvent.RETRY, RunState.QUEUED),
]


@pytest.mark.parametrize(("state", "event", "expected"), VALID_TRANSITIONS)
def test_advance_follows_the_architecture_state_machine(
    state: RunState, event: RunEvent, expected: RunState
) -> None:
    assert advance(state, event) is expected


def test_advance_rejects_undeclared_transitions() -> None:
    with pytest.raises(InvalidTransitionError) as excinfo:
        advance(RunState.QUEUED, RunEvent.COMPLETE)
    assert excinfo.value.state == "queued"
    assert excinfo.value.event == "complete"


def test_terminal_states_have_no_events() -> None:
    with pytest.raises(InvalidTransitionError):
        advance(RunState.COMPLETE, RunEvent.START)


def test_decision_event_maps_hitl_choices() -> None:
    assert decision_event(Decision.APPROVE) is RunEvent.APPROVE
    assert decision_event(Decision.OVERRIDE) is RunEvent.OVERRIDE


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (Verdict.COMPLIANT, RunState.COMPLETE),
        (Verdict.HIGH_RISK, RunState.COMPLETE),
        (Verdict.AMBIGUOUS, RunState.AWAITING_REVIEW),
    ],
)
def test_state_for_verdict_sends_only_ambiguous_to_review(verdict: Verdict, expected: RunState) -> None:
    assert state_for_verdict(verdict) is expected
