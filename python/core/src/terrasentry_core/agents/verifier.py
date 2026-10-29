"""Verifier agent: independent prompt, read-only tools, structured report."""

from __future__ import annotations

from strands import Agent
from strands.hooks import BeforeToolCallEvent, MessageAddedEvent
from strands.models.model import Model

from terrasentry_core.agents import prompts
from terrasentry_core.agents.supervisor import make_thought_hook, make_tool_start_hook
from terrasentry_core.agents.verification import VerificationReport
from terrasentry_core.tools.agent_tools import ToolContext, build_verifier_tools


def build_verifier_agent(model: Model, context: ToolContext) -> Agent:
    """Build the verifier; it can inspect evidence but never write or score."""
    tools = build_verifier_tools(context)
    agent = Agent(
        model=model,
        name="verifier",
        description="Independently challenges the evidence package and the supervisor summary.",
        system_prompt=prompts.VERIFIER_PROMPT,
        tools=tools,
        structured_output_model=VerificationReport,
        callback_handler=None,
    )

    agent.add_hook(make_thought_hook(context), MessageAddedEvent)
    agent.add_hook(
        make_tool_start_hook(context, "verifier", (tool.tool_name for tool in tools)), BeforeToolCallEvent
    )
    return agent


__all__ = ["build_verifier_agent"]
