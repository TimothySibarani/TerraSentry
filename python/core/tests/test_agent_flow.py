"""Graph flow: the verify-before-write edge gates the writer, and the trace shows it."""

from __future__ import annotations

from typing import Any

import agent_helpers
from terrasentry_core.agents.orchestrator import RunOrchestrator
from terrasentry_core.agents.verification import VerificationChallenge, VerificationReport
from terrasentry_core.domain.enums import RunState


def _rejected_review() -> VerificationReport:
    return VerificationReport(
        accepted=False,
        checked_claims=["llm.scripted"],
        challenges=[
            VerificationChallenge(
                kind="llm_review",
                severity="error",
                detail="summary claims 'no fire activity' but detections exist",
                source="llm",
            )
        ],
    )


def _orchestrator(source_clients: Any, data: Any, record: Any, *, review=None) -> RunOrchestrator:
    return RunOrchestrator(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=data,
        models=agent_helpers.scripted_models(record, review=review),
        clock=lambda: agent_helpers.FIXED_TIME,
    )


async def test_accepted_verification_releases_the_dds(source_router, source_clients) -> None:
    data = agent_helpers.datasets()
    record = data.get_record("REC-001")
    orchestrator = _orchestrator(source_clients, data, record)
    result = await orchestrator.run(record.record_id)

    assert result.state is RunState.COMPLETE
    assert result.assessment is not None
    assert result.verification is not None and result.verification.accepted
    assert result.verification.llm_reviewed
    assert "dds_writer" in [step.name for step in result.trace]
    assert result.trace[-1].kind == "state"


async def test_rejected_verification_blocks_the_writer(source_router, source_clients) -> None:
    data = agent_helpers.datasets()
    record = data.get_record("REC-001")
    orchestrator = _orchestrator(source_clients, data, record, review=_rejected_review())
    result = await orchestrator.run(record.record_id)

    assert result.state is RunState.FAILED
    assert result.assessment is None
    assert result.pending_assessment is None
    assert result.verification is not None and not result.verification.accepted
    assert result.verification.errors
    assert "dds_writer" not in [step.name for step in result.trace]
