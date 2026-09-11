"""Supervisor agent: delegates to specialists via agents-as-tools."""

from __future__ import annotations

from collections.abc import Sequence

from strands import Agent
from strands.hooks import AfterInvocationEvent, BeforeToolCallEvent
from strands.models.model import Model
from strands.types.content import Messages

from terrasentry_core.agents import prompts
from terrasentry_core.tools.agent_tools import ToolContext


def _last_assistant_text(messages: Messages) -> str:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        texts = [
            text for block in message.get("content", []) if (text := block.get("text"))
        ]
        if texts:
            return " ".join(texts).strip()
    return ""


def build_supervisor(model: Model, specialists: Sequence[Agent], *, context: ToolContext) -> Agent:
    """Build the supervisor; every specialist becomes a delegatable tool."""
    names = {specialist.name for specialist in specialists}
    agent = Agent(
        model=model,
        name="supervisor",
        description="Delegates EUDR evidence collection to the specialist agents.",
        system_prompt=prompts.SUPERVISOR_PROMPT,
        tools=[
            specialist.as_tool(name=specialist.name, description=specialist.description)
            for specialist in specialists
        ],
        callback_handler=None,
    )

    def record_delegation(event: BeforeToolCallEvent) -> None:
        name = str(event.tool_use.get("name", ""))
        if name in names:
            context.trace.add("agent", name, "delegated by supervisor")

    def record_summary(event: AfterInvocationEvent) -> None:
        summary = _last_assistant_text(event.agent.messages)
        if summary:
            context.summary = summary

    agent.add_hook(record_delegation, BeforeToolCallEvent)
    agent.add_hook(record_summary, AfterInvocationEvent)
    return agent


__all__ = ["build_supervisor"]
