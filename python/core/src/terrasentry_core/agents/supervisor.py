"""Supervisor agent: delegates to specialists via agents-as-tools."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from strands import Agent
from strands.hooks import AfterInvocationEvent, BeforeToolCallEvent, HookCallback, MessageAddedEvent
from strands.models.model import Model
from strands.types.content import Messages

from terrasentry_core.agents import prompts
from terrasentry_core.tools.agent_tools import ToolContext, capped_payload
from terrasentry_core.tools.trace import TraceCollector, TraceKind

RETASK_DETAIL_LIMIT = 160
NO_REASON = "(no reason given)"


def last_assistant_text(messages: Messages) -> str:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        texts = [text for block in message.get("content", []) if (text := block.get("text"))]
        if texts:
            return " ".join(texts).strip()
    return ""


def invocation_usage(agent: Agent) -> dict[str, int]:
    usage = agent.event_loop_metrics.accumulated_usage
    return {key: int(usage.get(key, 0)) for key in ("inputTokens", "outputTokens", "totalTokens")}


def make_thought_hook(context: ToolContext) -> HookCallback[MessageAddedEvent]:
    """Record model-authored notes and reasoning, never inferred reasoning."""

    def record_thought(event: MessageAddedEvent) -> None:
        message = event.message
        if message.get("role") != "assistant":
            return
        blocks = message.get("content", [])
        reasoning = "\n".join(
            block["reasoningContent"].get("reasoningText", {}).get("text", "")
            for block in blocks
            if "reasoningContent" in block
        ).strip()
        # Final assistant text belongs to the report; pre-tool notes belong here.
        text = (
            "\n".join(block["text"] for block in blocks if "text" in block).strip()
            if any("toolUse" in block for block in blocks)
            else ""
        )
        if not reasoning and not text:
            return
        name = str(event.agent.name)
        remaining = 2048
        bounded = {}
        for key, value in (("reasoning", reasoning), ("text", text)):
            bounded[key] = value.encode()[:remaining].decode("utf-8", errors="ignore")
            remaining -= len(bounded[key].encode())
        context.trace.add(
            "thought",
            name,
            "model reasoning" if reasoning else "agent note",
            payload={
                "agent": name,
                "invocation": context.invocations.get(name, 1),
                "event": "thought",
                **bounded,
                "truncated": len(reasoning.encode()) + len(text.encode()) > 2048,
            },
        )

    return record_thought


def make_tool_start_hook(
    context: ToolContext, kind: TraceKind, names: Iterable[str]
) -> HookCallback[BeforeToolCallEvent]:
    """Record a ``tool_start`` before a source call so live views can show it running.

    Coverage never trusts these: they carry no result (see ``coverage_checks``).
    """
    tracked = set(names)

    def record_start(event: BeforeToolCallEvent) -> None:
        name = str(event.tool_use.get("name", ""))
        if name not in tracked:
            return
        agent = str(event.agent.name)
        context.trace.add(
            kind,
            name,
            "called",
            payload={
                "agent": agent,
                "invocation": context.invocations.get(agent, 1),
                "event": "tool_start",
                "tool_use_id": event.tool_use.get("toolUseId"),
                "input": capped_payload(event.tool_use.get("input"), 1024),
            },
        )

    return record_start


def delegation_reason(tool_use: Any) -> str:
    """The delegation input text from a Strands agents-as-tools call, or a placeholder."""
    raw = tool_use.get("input") if hasattr(tool_use, "get") else None
    text = raw.get("input") if isinstance(raw, dict) else raw
    return text.strip() if isinstance(text, str) and text.strip() else NO_REASON


def make_delegation_hook(
    names: set[str], trace: TraceCollector, *, context: ToolContext | None = None
) -> HookCallback[BeforeToolCallEvent]:
    """Record delegations; a later delegation to the same specialist is a visible re-task."""
    counts: Counter[str] = Counter()

    def record_delegation(event: BeforeToolCallEvent) -> None:
        name = str(event.tool_use.get("name", ""))
        if name not in names:
            return
        counts[name] += 1
        if context is not None:
            context.invocations[name] = counts[name]
        reason = delegation_reason(event.tool_use)
        payload = {"agent": name, "invocation": counts[name], "input": reason, "event": "start"}
        if counts[name] == 1:
            trace.add("agent", name, "delegated by supervisor", payload=payload)
            return
        reason = delegation_reason(event.tool_use)
        detail = reason if len(reason) <= RETASK_DETAIL_LIMIT else reason[: RETASK_DETAIL_LIMIT - 1] + "…"
        trace.add("retask", name, detail, payload={**payload, "reason": reason, "ordinal": counts[name]})

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
        summary = last_assistant_text(event.agent.messages)
        if summary:
            context.summary = summary
        context.trace.add(
            "agent",
            "supervisor",
            "finished",
            payload={
                "agent": "supervisor",
                "invocation": 1,
                "event": "finish",
                "report": summary,
                "usage": invocation_usage(event.agent),
                "failed": event.result is None,
            },
        )

    agent.add_hook(make_delegation_hook(names, context.trace, context=context), BeforeToolCallEvent)
    agent.add_hook(record_summary, AfterInvocationEvent)
    agent.add_hook(make_thought_hook(context), MessageAddedEvent)
    return agent


__all__ = [
    "build_supervisor",
    "delegation_reason",
    "last_assistant_text",
    "make_delegation_hook",
    "make_tool_start_hook",
]
