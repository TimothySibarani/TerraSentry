"""Specialist agents: one source each, extraction model, ids-only tools."""

from __future__ import annotations

from strands import Agent
from strands.hooks import AfterInvocationEvent, BeforeToolCallEvent, HookCallback, MessageAddedEvent
from strands.models.model import Model

from terrasentry_core.agents import prompts
from terrasentry_core.agents.supervisor import invocation_usage, make_thought_hook, make_tool_start_hook
from terrasentry_core.tools.agent_tools import ToolContext, build_source_tools

SPECIALIST_NAMES = ("geospatial_analyst", "thermal_analyst", "legality_analyst")
#: A specialist's written report is kept in the trace so a reviewer can read what it concluded.
REPORT_LIMIT = 2000


def make_report_hook(name: str, context: ToolContext) -> HookCallback[AfterInvocationEvent]:
    """Record a specialist's final reply as a ``report`` trace step (context only, never scored)."""

    def record_report(event: AfterInvocationEvent) -> None:
        report = (
            " ".join(
                block["text"] for block in event.result.message.get("content", []) if "text" in block
            ).strip()
            if event.result is not None
            else ""
        )
        context.trace.add(
            "report",
            name,
            "reported" if report else "finished without a report",
            payload={
                "agent": name,
                "invocation": context.invocations.get(name, 1),
                "event": "finish",
                "report": report[:REPORT_LIMIT],
                "usage": invocation_usage(event.agent),
                "failed": event.result is None,
            },
        )

    return record_report


def build_specialists(model: Model, context: ToolContext) -> list[Agent]:
    """Build the geospatial, thermal, and legality agents for one run."""
    tools = {tool.tool_name: tool for tool in build_source_tools(context)}
    legality_tools = [
        tools["get_legality_record"],
        tools["get_consignment"],
        tools["check_concession_overlap"],
    ]
    if "search_adverse_media" in tools:
        legality_tools.append(tools["search_adverse_media"])
    specialists = [
        Agent(
            model=model,
            name="geospatial_analyst",
            description=(
                "Fetches Hansen GFC loss and screens context layers for a polygon; "
                "re-task it to read feature-level context layers."
            ),
            system_prompt=prompts.GEOSPATIAL_PROMPT,
            tools=[tools["get_tree_cover_loss"], tools["get_context_layers"]],
            callback_handler=None,
        ),
        Agent(
            model=model,
            name="thermal_analyst",
            description="Fetches NASA FIRMS thermal anomalies for a polygon.",
            system_prompt=prompts.THERMAL_PROMPT,
            tools=[tools["get_fire_hotspots"]],
            callback_handler=None,
        ),
        Agent(
            model=model,
            name="legality_analyst",
            description=(
                "Reads the declared legality and consignment records; "
                "re-task it to check concession overlap and permit coverage."
            ),
            system_prompt=prompts.LEGALITY_PROMPT,
            tools=legality_tools,
            callback_handler=None,
        ),
    ]
    for specialist in specialists:
        specialist.add_hook(make_report_hook(str(specialist.name), context), AfterInvocationEvent)
        specialist.add_hook(make_thought_hook(context), MessageAddedEvent)
        specialist.add_hook(make_tool_start_hook(context, "tool", tools), BeforeToolCallEvent)
    return specialists


__all__ = ["REPORT_LIMIT", "SPECIALIST_NAMES", "build_specialists", "make_report_hook"]
