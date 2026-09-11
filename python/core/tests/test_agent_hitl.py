"""HITL: an ambiguous run pauses before DDS release and resumes with a decision."""

from __future__ import annotations

import re
from typing import Any

import agent_helpers
import httpx
import pytest
import respx
from terrasentry_core.agents.orchestrator import RunOrchestrator
from terrasentry_core.agents.schemas import ReviewDecision
from terrasentry_core.domain.enums import Decision, RunState
from terrasentry_core.errors import InvalidReviewDecisionError
from terrasentry_core.seed.schemas import BatchDataset
from terrasentry_core.tools.datasets import SeedDatasets


def _ambiguous_datasets(factories: dict[str, Any]) -> tuple[SeedDatasets, Any]:
    supplier = factories["supplier"](
        supplier_id="SUP-HITL",
        hgu_number=None,
        pbp_number=None,
        permit_status="active",
        sanctions=[],
    )
    record = factories["batch_record"](
        index=90,
        expected_archetype="ambiguous",
        expected_ambiguity="permit_gap",
        supplier=supplier,
    )
    batch = BatchDataset(
        rng_seed=1,
        distribution={"compliant": 0, "high_risk": 0, "ambiguous": 1},
        records=[record],
    )
    operator = agent_helpers.datasets().operator
    return SeedDatasets(batch, operator), record


async def _run_ambiguous(factories: dict[str, Any], source_clients: Any):
    data, record = _ambiguous_datasets(factories)
    with respx.mock(assert_all_called=False) as router:
        router.post(agent_helpers.GFW_URL).mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )
        router.get(url__regex=re.compile(agent_helpers.FIRMS_REGEX)).mock(
            return_value=httpx.Response(200, text="")
        )
        orchestrator = RunOrchestrator(
            gfw=source_clients.gfw,
            firms=source_clients.firms,
            datasets=data,
            models=agent_helpers.scripted_models(record),
            clock=lambda: agent_helpers.FIXED_TIME,
        )
        result = await orchestrator.run(record.record_id)
    return orchestrator, result


async def test_ambiguous_run_pauses_without_releasing_the_dds(factories, source_clients) -> None:
    _, result = await _run_ambiguous(factories, source_clients)

    assert result.state is RunState.AWAITING_REVIEW
    assert result.assessment is None
    assert result.pending_assessment is not None
    assert result.pending_assessment.assessment.verdict.value == "ambiguous"
    writer_steps = [step for step in result.trace if step.kind == "writer"]
    assert writer_steps and "withheld" in writer_steps[0].detail


async def test_resume_approve_releases_the_dds(factories, source_clients) -> None:
    orchestrator, result = await _run_ambiguous(factories, source_clients)
    resumed = await orchestrator.resume(
        result,
        ReviewDecision(decision=Decision.APPROVE, reviewer="alice", note="approved"),
    )

    assert resumed.state is RunState.COMPLETE
    assert resumed.assessment is not None
    assert resumed.pending_assessment is None
    assert resumed.review is not None
    assert resumed.review.reviewer == "alice"
    assert resumed.trace[-1].kind == "review"
    with pytest.raises(InvalidReviewDecisionError):
        await orchestrator.resume(resumed, ReviewDecision(decision=Decision.APPROVE))


async def test_resume_override_also_completes(factories, source_clients) -> None:
    orchestrator, result = await _run_ambiguous(factories, source_clients)
    resumed = await orchestrator.resume(
        result, ReviewDecision(decision=Decision.OVERRIDE, reviewer="bob", note="override")
    )
    assert resumed.state is RunState.COMPLETE
    assert resumed.assessment is not None
    assert resumed.review is not None
    assert resumed.review.decision is Decision.OVERRIDE
