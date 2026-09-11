"""Model construction for the agent roles.

The app wires Bedrock here; tests and the offline demo inject a
:class:`~terrasentry_core.agents.scripted.ScriptedModel` instead, so importing
this module never needs AWS credentials. Which model fills each role is an
environment decision (``BEDROCK_MODEL_ORCHESTRATOR`` / ``BEDROCK_MODEL_EXTRACTION``);
there is no default model id in the code.
"""

from __future__ import annotations

from dataclasses import dataclass

from strands.models.model import Model

from terrasentry_core.agents.settings import AgentSettings, ModelRole, get_agent_settings
from terrasentry_core.errors import MissingModelError

_MODEL_VARIABLE: dict[ModelRole, str] = {
    "orchestrator": "BEDROCK_MODEL_ORCHESTRATOR",
    "extraction": "BEDROCK_MODEL_EXTRACTION",
}


@dataclass(frozen=True)
class ModelBundle:
    """The model pair for one run: one for judgement roles, one for extraction."""

    orchestrator: Model
    extraction: Model

    @classmethod
    def from_settings(cls, settings: AgentSettings | None = None) -> ModelBundle:
        resolved = settings or get_agent_settings()
        return cls(
            orchestrator=build_model("orchestrator", settings=resolved),
            extraction=build_model("extraction", settings=resolved),
        )


def build_model(role: ModelRole, *, settings: AgentSettings | None = None) -> Model:
    """Build the Bedrock model for a role from the configured model id."""
    resolved = settings or get_agent_settings()
    model_id = resolved.model_for(role).strip()
    if not model_id:
        raise MissingModelError(_MODEL_VARIABLE[role])
    from strands.models import BedrockModel

    common = {
        "model_id": model_id,
        "temperature": resolved.agent_temperature,
        "max_tokens": resolved.agent_max_tokens,
    }
    if resolved.has_profile:
        import boto3

        session = boto3.Session(
            profile_name=resolved.aws_profile,
            region_name=resolved.aws_region,
        )
        return BedrockModel(boto_session=session, **common)
    return BedrockModel(region_name=resolved.aws_region, **common)


__all__ = ["ModelBundle", "build_model"]

