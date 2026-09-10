"""The agent package must actually be reachable, and its tools must match their schemas."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from terrasentry.agent.orchestrator import Orchestrator
from terrasentry.agent.prompts import ORCHESTRATOR_SYSTEM
from terrasentry.agent.toolspec import ALL_TOOLS
from terrasentry.agent.tools_registry import ScreeningSession


def _spec_names():
    return {t["toolSpec"]["name"] for t in ALL_TOOLS}


def test_every_declared_tool_has_an_implementation():
    """A schema the model can see but nothing can execute is a runtime crash waiting."""
    session = ScreeningSession("SUP-001")
    assert _spec_names() == set(session.build())


def test_tool_arguments_match_their_schemas():
    """Each tool must accept exactly the required arguments its schema advertises."""
    import inspect

    session = ScreeningSession("SUP-001")
    tools = session.build()
    for spec in ALL_TOOLS:
        ts = spec["toolSpec"]
        params = inspect.signature(tools[ts["name"]]).parameters
        for required in ts["inputSchema"]["json"]["required"]:
            assert required in params, f"{ts['name']} cannot accept required arg '{required}'"


def test_full_loop_runs_offline_and_matches_the_reference_pipeline():
    from run_agent import ScriptedClient

    from terrasentry import pipeline

    session = ScreeningSession("SUP-001")
    agent = Orchestrator(
        client=ScriptedClient(),
        model_id="dry-run",
        tools=session.build(),
        tool_specs=ALL_TOOLS,
        system_prompt=ORCHESTRATOR_SYSTEM,
        ledger=session.ledger,
    )
    result = agent.run(supplier=session.supplier["legal_name"], task=session.task_prompt())

    assert result.stop_reason == "end_turn"
    assert all(r["status"] == "success" for t in result.turns for r in t.tool_results)

    # to_dict() rounds; compare on the same basis rather than raw float vs rounded.
    reference = pipeline.run("SUP-001")
    assert session.assessment.to_dict()["score"] == reference["assessment"]["score"]
    assert session.assessment.to_dict()["components"] == reference["assessment"]["components"]
    assert session.assessment.recommendation.value == reference["assessment"]["recommendation"]


def test_tool_failures_are_returned_to_the_model_not_raised():
    """The agent must be able to recover, so a broken tool becomes a result, not a crash."""
    class OneBadCall:
        def __init__(self):
            self.done = False

        def converse(self, **kw):
            if self.done:
                return {"stopReason": "end_turn",
                        "output": {"message": {"content": [{"text": "recovered"}]}}}
            self.done = True
            return {"stopReason": "tool_use", "output": {"message": {"content": [
                {"toolUse": {"toolUseId": "x", "name": "verify_permit", "input": {}}}]}}}

    session = ScreeningSession("SUP-001")
    agent = Orchestrator(
        client=OneBadCall(), model_id="fake", tools=session.build(),
        tool_specs=ALL_TOOLS, system_prompt="", ledger=session.ledger,
    )
    result = agent.run(supplier="x", task="y")
    assert result.turns[0].tool_results[0]["status"] == "error"
    assert result.final_text == "recovered"


def test_score_before_geometry_is_refused_not_guessed():
    session = ScreeningSession("SUP-001")
    out = session.build()["compute_risk_score"](supplier_id="SUP-001")
    assert "error" in out
