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
    return [
        {key: value for key, value in step.payload.items() if key in {"polygon_id", "supplier_id", "status"}}
        for step in result.trace
        if step.kind == "tool" and step.name == name and step.payload.get("event") == "tool_end"
    ]


async def test_every_tool_call_is_bracketed_by_start_and_end_events(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router, overlaps={"protected_areas": {"name": "Reserve", "desig": "National park"}})
        result = await _run(source_clients, "high_risk_live")

    tools = [
        step for step in result.trace if step.kind in {"tool", "verifier"} and "tool_use_id" in step.payload
    ]
    starts = {step.payload["tool_use_id"]: step for step in tools if step.payload["event"] == "tool_start"}
    ends = [step for step in tools if step.payload["event"] == "tool_end"]
    assert ends and {step.payload["tool_use_id"] for step in ends} == set(starts)
    for end in ends:
        start = starts[end.payload["tool_use_id"]]
        assert result.trace.index(start) < result.trace.index(end)
        assert start.payload["agent"] == end.payload["agent"]
    # Lifecycle steps say what happened instead of leaving the UI to parse detail strings.
    events = {(step.payload.get("agent"), step.payload.get("event")) for step in result.trace}
    for agent in ("supervisor", "geospatial_analyst", "thermal_analyst", "legality_analyst", "verifier"):
        assert {(agent, "start"), (agent, "finish")} <= events
    assert ("assessor", "finish") in events


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


async def test_configuration_and_first_inputs(source_clients, monkeypatch) -> None:
    original = agent_helpers.scripted_models

    def configured(*args, **kwargs):
        models = original(*args, **kwargs)
        models.orchestrator.update_config(params={"temperature": 0.2, "max_tokens": 8192})
        return models

    monkeypatch.setattr(agent_helpers, "scripted_models", configured)
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router)
        result = await _run(source_clients, "high_risk_live")
    configs = [step for step in result.trace if step.name == "configuration"]
    assert len(configs) == 1
    config = configs[0]
    assert result.trace.index(config) < next(i for i, step in enumerate(result.trace) if step.kind == "agent")
    agents = {agent["name"]: agent for agent in config.payload["agents"]}
    assert set(agents) == {
        "supervisor",
        "geospatial_analyst",
        "thermal_analyst",
        "legality_analyst",
        "verifier",
        "assessor",
        "dds_writer",
    }
    assert "check_concession_overlap" in agents["legality_analyst"]["tools"]
    assert config.payload["models"]["orchestrator"]
    assert config.payload["params"]["orchestrator"] == {"temperature": 0.2, "max_tokens": 8192}
    delegations = [step for step in result.trace if step.detail == "delegated by supervisor"]
    assert all(step.payload["input"] and step.payload["invocation"] == 1 for step in delegations)


async def test_tool_attribution_and_retask_invocation(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router, overlaps={"protected_areas": {"name": "Reserve"}})
        result = await _run(source_clients, "high_risk_live")
    fire = next(
        step
        for step in result.trace
        if step.name == "get_fire_hotspots" and step.payload["event"] == "tool_end"
    )
    assert fire.payload["agent"] == "thermal_analyst"
    assert fire.payload["input"] == {"polygon_id": "PLY-001"}
    assert fire.payload["duration_ms"] >= 0
    assert "detection_count" in fire.payload["result"]
    assert fire.payload["tool_use_id"]
    deep = next(
        step
        for step in result.trace
        if step.name == "get_context_layers" and step.payload["event"] == "tool_end"
    )
    assert deep.payload["agent"] == "geospatial_analyst" and deep.payload["invocation"] == 2


async def test_scripted_final_reports_are_not_duplicate_thoughts(source_clients) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_sources(router)
        result = await _run(source_clients, "high_risk_live")
    assert not [step for step in result.trace if step.kind == "thought"]
    finishes = [
        step
        for step in result.trace
        if step.kind == "report"
        or (step.name == "supervisor" and step.detail == "finished")
        or step.name == "verification"
    ]
    assert len(finishes) == 7  # five specialist invocations, supervisor, verifier
    assert all("usage" in step.payload and "invocation" in step.payload for step in finishes)


async def test_real_pretool_note_is_recorded_before_tool(source_clients) -> None:
    from strands import Agent
    from strands.hooks import MessageAddedEvent
    from terrasentry_core.agents.scripted import ScriptedModel, ScriptedTurn, ToolCall
    from terrasentry_core.agents.supervisor import make_thought_hook
    from terrasentry_core.tools.agent_tools import ToolContext, build_source_tools
    from terrasentry_core.tools.trace import TraceCollector

    context = ToolContext(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=agent_helpers.datasets(),
        trace=TraceCollector(),
    )
    model = ScriptedModel(
        [
            ScriptedTurn(
                text="I will inspect the permit.",
                tool_calls=(ToolCall("get_legality_record", {"supplier_id": "SUP-001"}),),
            ),
            ScriptedTurn(text="Reported."),
        ]
    )
    agent = Agent(
        name="legality_analyst", model=model, tools=build_source_tools(context), callback_handler=None
    )
    agent.add_hook(make_thought_hook(context), MessageAddedEvent)
    await agent.invoke_async("Inspect SUP-001")
    assert [step.kind for step in context.trace.steps] == ["thought", "tool"]
    assert context.trace.steps[0].payload["text"] == "I will inspect the permit."
    assert context.trace.steps[0].payload["agent"] == "legality_analyst"


def test_reasoning_blocks_and_empty_report_finish(source_clients) -> None:
    from strands import Agent
    from strands.hooks import AfterInvocationEvent, MessageAddedEvent
    from terrasentry_core.agents.scripted import ScriptedModel
    from terrasentry_core.agents.specialists import make_report_hook
    from terrasentry_core.agents.supervisor import make_thought_hook
    from terrasentry_core.tools.agent_tools import ToolContext
    from terrasentry_core.tools.trace import TraceCollector

    context = ToolContext(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=agent_helpers.datasets(),
        trace=TraceCollector(),
    )
    agent = Agent(name="thermal_analyst", model=ScriptedModel(), callback_handler=None)
    make_thought_hook(context)(
        MessageAddedEvent(
            agent=agent,
            message={
                "role": "assistant",
                "content": [{"reasoningContent": {"reasoningText": {"text": "Emitted reasoning " * 300}}}],
            },
        )
    )
    thought = context.trace.steps[-1]
    assert thought.payload["reasoning"].startswith("Emitted reasoning")
    assert len(thought.payload["reasoning"].encode()) <= 2048 and thought.payload["truncated"]
    make_report_hook("thermal_analyst", context)(AfterInvocationEvent(agent=agent))
    finish = context.trace.steps[-1]
    assert finish.kind == "report" and finish.detail == "finished without a report"
    assert finish.payload["usage"]["totalTokens"] == 0


async def test_successful_specialist_with_empty_response_still_finishes(source_clients) -> None:
    from terrasentry_core.agents.scripted import ScriptedModel, ScriptedTurn
    from terrasentry_core.agents.specialists import build_specialists
    from terrasentry_core.tools.agent_tools import ToolContext
    from terrasentry_core.tools.trace import TraceCollector

    context = ToolContext(
        gfw=source_clients.gfw,
        firms=source_clients.firms,
        datasets=agent_helpers.datasets(),
        trace=TraceCollector(),
    )
    agent = build_specialists(ScriptedModel([ScriptedTurn(text="")]), context)[0]
    await agent.invoke_async("Finish without a report")
    [finish] = context.trace.steps
    assert finish.kind == "report" and finish.detail == "finished without a report"
    assert finish.payload["agent"] == "geospatial_analyst"
    assert finish.payload["invocation"] == 1
    assert finish.payload["report"] == "" and finish.payload["failed"] is False
    assert finish.payload["usage"]["totalTokens"] == 0
