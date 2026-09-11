"""Specialist agents: one source each, extraction model, ids-only tools."""

from __future__ import annotations

from strands import Agent
from strands.models.model import Model

from terrasentry_core.agents import prompts
from terrasentry_core.tools.agent_tools import ToolContext, build_source_tools

SPECIALIST_NAMES = ("geospatial_analyst", "thermal_analyst", "legality_analyst")


def build_specialists(model: Model, context: ToolContext) -> list[Agent]:
    """Build the geospatial, thermal, and legality agents for one run."""
    tools = {tool.tool_name: tool for tool in build_source_tools(context)}
    return [
        Agent(
            model=model,
            name="geospatial_analyst",
            description="Fetches Hansen GFC tree cover loss for a polygon.",
            system_prompt=prompts.GEOSPATIAL_PROMPT,
            tools=[tools["get_tree_cover_loss"]],
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
            description="Reads the synthetic legality and consignment records.",
            system_prompt=prompts.LEGALITY_PROMPT,
            tools=[tools["get_legality_record"], tools["get_consignment"]],
            callback_handler=None,
        ),
    ]


__all__ = ["SPECIALIST_NAMES", "build_specialists"]
