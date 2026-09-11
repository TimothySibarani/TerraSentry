"""Store-level checks: auto-seed is idempotent and run results are reconstructible."""

from __future__ import annotations

import asyncio
from pathlib import Path

import api_helpers
from terrasentry_api.seed_loader import seed_if_empty
from terrasentry_api.store import RunStore
from terrasentry_core.agents.schemas import AgentRunResult, ReviewDecision
from terrasentry_core.domain.enums import Decision, RunState
from terrasentry_core.errors import InvalidReviewDecisionError
from terrasentry_core.tools.datasets import SeedDatasets


async def test_seed_is_idempotent(tmp_path: Path, datasets: SeedDatasets) -> None:
    factory = api_helpers.test_services_factory(tmp_path, datasets)
    async with factory() as services, services.session_factory() as session:
        assert await seed_if_empty(RunStore(session), services.datasets) == 0
        assert await RunStore(session).count_suppliers() == 4


async def test_load_result_reconstructs_an_awaiting_run(
    tmp_path: Path, datasets: SeedDatasets, source_router: object
) -> None:
    """The HITL resume path rebuilds the M3 result from persisted rows."""
    factory = api_helpers.test_services_factory(tmp_path, datasets)
    async with factory() as services:
        run_id = await services.run_manager.start_run(record_id="REC-003", scenario=None, model="scripted")
        result = None
        for _ in range(500):
            async with services.session_factory() as session:
                result = await RunStore(session).load_result(run_id)
            if result is not None and result.state is RunState.AWAITING_REVIEW:
                break
            await asyncio.sleep(0.01)
        assert result is not None
        assert result.state is RunState.AWAITING_REVIEW
        assert result.pending_assessment is not None
        assert result.assessment is None
        assert result.pending_assessment.assessment.verdict.value == "ambiguous"
        assert result.pending_assessment.dds.statement is not None
        assert [step.step_id for step in result.trace] == [
            f"STEP-{index:03d}" for index in range(1, len(result.trace) + 1)
        ]


async def test_concurrent_decisions_only_one_wins(
    tmp_path: Path, datasets: SeedDatasets, source_router: object
) -> None:
    """Two approvals racing on the same run: the per-run lock serialises them."""
    factory = api_helpers.test_services_factory(tmp_path, datasets)
    async with factory() as services:
        manager = services.run_manager
        run_id = await manager.start_run(record_id="REC-003", scenario=None, model="scripted")
        for _ in range(500):
            async with services.session_factory() as session:
                run = await RunStore(session).get_run(run_id)
            if run is not None and run.state is RunState.AWAITING_REVIEW:
                break
            await asyncio.sleep(0.01)

        results = await asyncio.gather(
            manager.decide(run_id, ReviewDecision(decision=Decision.APPROVE, reviewer="alice")),
            manager.decide(run_id, ReviewDecision(decision=Decision.OVERRIDE, reviewer="bob")),
            return_exceptions=True,
        )

    winners = [result for result in results if isinstance(result, AgentRunResult)]
    rejects = [result for result in results if isinstance(result, InvalidReviewDecisionError)]
    assert len(winners) == 1
    assert len(rejects) == 1
    assert winners[0].state is RunState.COMPLETE
