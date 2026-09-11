"""The scripted model must drive real Strands agents with no network."""

from __future__ import annotations

from pydantic import BaseModel
from strands import Agent, tool
from terrasentry_core.agents.scripted import ScriptedModel, ScriptedTurn, ToolCall


class Answer(BaseModel):
    value: int
    note: str = ""


@tool
def add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: First addend.
        b: Second addend.
    """
    return a + b


def test_scripted_model_runs_a_tool_then_final_text() -> None:
    model = ScriptedModel(
        turns=[
            ScriptedTurn(tool_calls=(ToolCall("add", {"a": 2, "b": 3}),)),
            ScriptedTurn(text="The sum is 5."),
        ]
    )
    agent = Agent(model=model, tools=[add], callback_handler=None)
    result = agent("add 2 and 3")
    assert "5" in str(result)
    assert model.call_count == 2
    tool_uses = [
        block["toolUse"]["name"]
        for message in agent.messages
        for block in message.get("content", [])
        if "toolUse" in block
    ]
    assert tool_uses == ["add"]


def test_scripted_model_returns_structured_output() -> None:
    model = ScriptedModel(turns=[ScriptedTurn(structured_output=Answer(value=7, note="ok"))])
    agent = Agent(model=model, structured_output_model=Answer, callback_handler=None)
    result = agent("give me an answer")
    assert isinstance(result.structured_output, Answer)
    assert result.structured_output.value == 7


def test_scripted_model_text_defaults_when_queue_is_empty() -> None:
    model = ScriptedModel(default_text="nothing queued")
    agent = Agent(model=model, callback_handler=None)
    result = agent("hello")
    assert "nothing queued" in str(result)
