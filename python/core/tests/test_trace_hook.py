"""The M4 API seam: steps are observable while a run is in flight.

``on_step`` is what lets the API persist and stream the trace instead of only
receiving it in the final ``AgentRunResult``; ``run_id`` injection lets the API
own the id before the background task starts.
"""

from __future__ import annotations

from typing import Any

import agent_helpers
import httpx
import respx
from terrasentry_core.agents.orchestrator import RunOrchestrator
from terrasentry_core.agents.schemas import ReviewDecision
from terrasentry_core.domain.enums import Decision, RunState
from terrasentry_core.seed.schemas import BatchDataset
from terrasentry_core.tools.datasets import SeedDatasets


def _ambiguous_datasets(factories: dict[str, Any]) -> tuple[SeedDatasets, Any]:
    supplier = factories["supplier"](
        supplier_id="SUP-HOOK",
        hgu_number=None,
        pbp_number=None,
        permit_status="active",
        sanctions=[],
    )
    record = factories["batch_record"](
        index=91,
        expected_archetype="ambiguous",
        expected_ambiguity="permit_gap",
        supplier=supplier,
    )
    batch = BatchDataset(
        rng_seed=1,
        distribution={"compliant": 0, "high_risk": 0, "ambiguous": 1},
        records=[record],
    )
    return SeedDatasets(batch, agent_helpers.datasets().operator), record


async def test_on_step_mirrors_the_final_trace_and_run_id_is_injectable(
    source_router, source_clients
) -> None:
    data = agent_helpers.datasets()
    record = data.get_record("REC-001")
    seen: list[Any] = []
    orchestrator = RunOrchestrator(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=data,
        models=agent_helpers.scripted_models(record),
        clock=lambda: agent_helpers.FIXED_TIME,
        on_step=seen.append,
    )

    result = await orchestrator.run(record.record_id, run_id="api-run-001")

    assert result.run_id == "api-run-001"
    assert [step.step_id for step in seen] == [step.step_id for step in result.trace]
    assert seen[0].name == "queued"
    assert seen[-1].kind == "state"
    assert len(seen) == len(result.trace)


async def test_resume_emits_the_review_step(factories, source_clients) -> None:
    data, record = _ambiguous_datasets(factories)
    seen: list[Any] = []
    with respx.mock(assert_all_called=False) as router:
        router.post(agent_helpers.GFW_URL).mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )
        router.get(url__regex=agent_helpers.FIRMS_REGEX).mock(return_value=httpx.Response(200, text=""))
        orchestrator = RunOrchestrator(
            gfw=source_clients.gfw,
            firms=source_clients.firms,
            datasets=data,
            models=agent_helpers.scripted_models(record),
            clock=lambda: agent_helpers.FIXED_TIME,
            on_step=seen.append,
        )
        result = await orchestrator.run(record.record_id, run_id="api-run-hitl")
    assert result.state is RunState.AWAITING_REVIEW
    before_resume = len(seen)

    resumed = await orchestrator.resume(
        result, ReviewDecision(decision=Decision.APPROVE, reviewer="alice", note="ok")
    )

    assert resumed.state is RunState.COMPLETE
    assert len(seen) == before_resume + 1
    assert seen[-1].kind == "review"
    assert seen[-1].step_id == f"STEP-{before_resume + 1:03d}"
