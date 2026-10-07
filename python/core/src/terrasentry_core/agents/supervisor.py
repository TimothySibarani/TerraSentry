"""Supervisor agent: delegates to specialists via agents-as-tools."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from strands import Agent
from strands.hooks import AfterInvocationEvent, BeforeToolCallEvent, HookCallback
from strands.models.model import Model
from strands.types.content import Messages

from terrasentry_core.agents import prompts
from terrasentry_core.tools.agent_tools import ToolContext
from terrasentry_core.tools.trace import TraceCollector

RETASK_DETAIL_LIMIT = 160
NO_REASON = "(no reason given)"


def _last_assistant_text(messages: Messages) -> str:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        texts = [text for block in message.get("content", []) if (text := block.get("text"))]
        if texts:
            return " ".join(texts).strip()
    return ""


def delegation_reason(tool_use: Any) -> str:
    """The delegation input text from a Strands agents-as-tools call, or a placeholder."""
    raw = tool_use.get("input") if hasattr(tool_use, "get") else None
    text = raw.get("input") if isinstance(raw, dict) else raw
    return text.strip() if isinstance(text, str) and text.strip() else NO_REASON


def make_delegation_hook(names: set[str], trace: TraceCollector) -> HookCallback[BeforeToolCallEvent]:
    """Record delegations; a later delegation to the same specialist is a visible re-task."""
    counts: Counter[str] = Counter()

    def record_delegation(event: BeforeToolCallEvent) -> None:
        name = str(event.tool_use.get("name", ""))
        if name not in names:
            return
        counts[name] += 1
        if counts[name] == 1:
            trace.add("agent", name, "delegated by supervisor")
            return
        reason = delegation_reason(event.tool_use)
        detail = reason if len(reason) <= RETASK_DETAIL_LIMIT else reason[: RETASK_DETAIL_LIMIT - 1] + "…"
        trace.add("retask", name, detail, payload={"reason": reason, "ordinal": counts[name]})

    return record_delegation


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

    def record_summary(event: AfterInvocationEvent) -> None:
        summary = _last_assistant_text(event.agent.messages)
        if summary:
            context.summary = summary

    agent.add_hook(make_delegation_hook(names, context.trace), BeforeToolCallEvent)
    agent.add_hook(record_summary, AfterInvocationEvent)
    return agent


__all__ = ["build_supervisor", "delegation_reason", "make_delegation_hook"]
