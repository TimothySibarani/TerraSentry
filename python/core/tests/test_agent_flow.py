"""Graph flow: the verify-before-write edge gates the writer, and the trace shows it."""

from __future__ import annotations

from typing import Any

import agent_helpers
import httpx
import respx
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


async def test_accepted_verification_releases_the_dds(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router, loss="empty", fire="empty")
        result = await _run(source_clients, "compliant_live")

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


# -- adaptive investigation -------------------------------------------------------------


def _mock_sources(
    router: Any,
    *,
    loss: str = "default",
    fire: str = "default",
    overlaps: dict[str, dict[str, Any]] | None = None,
    unavailable: frozenset[str] = frozenset(),
) -> Any:
    """Mock GFW loss, FIRMS and context layers; returns the loss route for call counting."""
    if loss == "empty":
        loss_route = router.post(agent_helpers.GFW_URL).mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )
    elif loss == "fail":
        loss_route = router.post(agent_helpers.GFW_URL).mock(return_value=httpx.Response(422))
    else:
        loss_route = router.post(agent_helpers.GFW_URL).mock(side_effect=agent_helpers.gfw_side_effect)
    if fire == "empty":
        router.get(url__regex=agent_helpers.FIRMS_REGEX).mock(return_value=httpx.Response(200, text=""))
    else:
        router.get(url__regex=agent_helpers.FIRMS_REGEX).mock(side_effect=agent_helpers.firms_side_effect)
    agent_helpers.mock_context_layers(router, overlaps=overlaps, unavailable=unavailable)
    return loss_route


async def _run(source_clients: Any, scenario: str, *, skip_deep_dives: bool = False) -> Any:
    data = agent_helpers.datasets()
    record = data.record_for_scenario(scenario)
    orchestrator = RunOrchestrator(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=data,
        models=agent_helpers.scripted_models(record, skip_deep_dives=skip_deep_dives),
        clock=lambda: agent_helpers.FIXED_TIME,
    )
    return await orchestrator.run(record.record_id)


def _delegations(result: Any, kind: str) -> list[str]:
    return [step.name for step in result.trace if step.kind == kind and step.name != "supervisor"]


def _tool_calls(result: Any, name: str) -> list[dict[str, Any]]:
    return [step.payload for step in result.trace if step.kind == "tool" and step.name == name]


async def test_clean_record_runs_one_pass_with_no_retask(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router, loss="empty", fire="empty")
        result = await _run(source_clients, "compliant_live")

    assert result.state is RunState.COMPLETE
    assert sorted(_delegations(result, "agent")) == [
        "geospatial_analyst",
        "legality_analyst",
        "thermal_analyst",
    ]
    assert _delegations(result, "retask") == []
    assert _tool_calls(result, "get_context_layers") == []
    assert result.verification is not None and result.verification.accepted
    assert not [c for c in result.verification.challenges if c.kind == "coverage"]


async def test_high_risk_record_retasks_legality_and_geospatial_with_reasons(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router, overlaps={"protected_areas": {"name": "Reserve", "desig": "National park"}})
        result = await _run(source_clients, "high_risk_live")

    # A high-risk verdict is held for a person; the DDS is withheld until they decide.
    assert result.state is RunState.AWAITING_REVIEW
    retasks = [step for step in result.trace if step.kind == "retask"]
    assert sorted(step.name for step in retasks) == ["geospatial_analyst", "legality_analyst"]
    assert all("protected_overlap" in step.detail and step.payload["ordinal"] == 2 for step in retasks)
    ids = {"polygon_id": "PLY-001", "supplier_id": "SUP-001", "status": "ok"}
    assert _tool_calls(result, "get_context_layers") == [{"polygon_id": "PLY-001", "status": "ok"}]
    assert _tool_calls(result, "check_concession_overlap") == [ids]
    assert result.assessment is None
    assert result.pending_assessment is not None
    assert result.pending_assessment.assessment.verdict == "high_risk"
    assert result.verification is not None and result.verification.accepted
    assert "coverage.get_context_layers" in result.verification.checked_claims


async def test_specialist_reports_reach_the_trace_without_changing_the_verdict(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router, loss="empty", fire="empty")
        result = await _run(source_clients, "compliant_live")

    reports = [step for step in result.trace if step.kind == "report"]
    assert {step.name for step in reports} == {"geospatial_analyst", "legality_analyst", "thermal_analyst"}
    assert all(step.payload["report"] and len(step.payload["report"]) <= 2000 for step in reports)
    assert result.assessment is not None and result.assessment.assessment.verdict == "compliant"


async def test_skipped_deep_dive_is_rejected_by_the_coverage_gate(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router, overlaps={"protected_areas": {"name": "Reserve"}})
        result = await _run(source_clients, "high_risk_live", skip_deep_dives=True)

    assert result.state is RunState.FAILED
    assert _delegations(result, "retask") == []
    assert "dds_writer" not in [step.name for step in result.trace]
    assert result.verification is not None and not result.verification.accepted
    missing = {c.detail.split()[2] for c in result.verification.errors if c.kind == "coverage"}
    assert missing == {"get_context_layers", "check_concession_overlap"}
    assert result.error is not None and result.error.startswith("Verifier rejected the run: coverage:")
    assert not result.verification.llm_reviewed


async def test_unavailable_context_layer_during_the_deep_dive_is_covered_with_a_data_gap(
    source_clients,
) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(
            router,
            overlaps={"protected_areas": {"name": "Reserve"}},
            unavailable=frozenset({"moratorium"}),
        )
        result = await _run(source_clients, "high_risk_live")

    assert _tool_calls(result, "get_context_layers") == [{"polygon_id": "PLY-001", "status": "error"}]
    assert result.verification is not None and result.verification.accepted
    info = [c for c in result.verification.challenges if c.kind == "coverage" and c.severity == "info"]
    # Moratorium is not a concession layer, so only the context deep dive carries the gap.
    assert {c.detail.split()[0] for c in info} == {"get_context_layers"}
    assert _tool_calls(result, "check_concession_overlap") == [
        {"polygon_id": "PLY-001", "supplier_id": "SUP-001", "status": "ok"}
    ]
    assert result.state in {RunState.COMPLETE, RunState.AWAITING_REVIEW}


async def test_loss_failure_does_not_suppress_the_retask(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router, loss="fail", fire="empty", overlaps={"protected_areas": {"name": "Reserve"}})
        result = await _run(source_clients, "high_risk_live")

    assert sorted(_delegations(result, "retask")) == ["geospatial_analyst", "legality_analyst"]
    assert _tool_calls(result, "get_context_layers")
    candidate = result.assessment or result.pending_assessment
    assert candidate is not None
    assert any(f.code == "protected_area" for f in candidate.assessment.findings)


async def test_phase_one_specialists_share_one_source_acquisition(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        loss_route = _mock_sources(router, overlaps={"protected_areas": {"name": "Reserve"}})
        result = await _run(source_clients, "high_risk_live")

    assert _delegations(result, "retask")
    # Two phases, five specialist invocations, still one GFW loss acquisition.
    assert loss_route.call_count == 1
