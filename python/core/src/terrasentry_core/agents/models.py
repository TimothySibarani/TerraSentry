"""Model construction for the agent roles.

The app wires SAP AI Core (Generative AI Hub) here; tests and the offline demo inject a
:class:`~terrasentry_core.agents.scripted.ScriptedModel` instead, so importing this module never
needs SAP credentials. Which model fills each role is an environment decision
(``AICORE_MODEL_*``); there is no default model id in the code.
"""

from __future__ import annotations

from dataclasses import dataclass

from strands.models.model import Model
from terrasentry_integrations.sap_ai_core import prepare_litellm

from terrasentry_core.agents.settings import AgentSettings, ModelRole, get_agent_settings
from terrasentry_core.errors import MissingModelError, ModelConfigurationError

_AICORE_MODEL_VARIABLE: dict[ModelRole, str] = {
    "orchestrator": "AICORE_MODEL_ORCHESTRATOR",
    "extraction": "AICORE_MODEL_EXTRACTION",
}


@dataclass(frozen=True)
class ModelBundle:
    """The model pair for one run: one for judgement roles, one for extraction."""

    orchestrator: Model
    extraction: Model

    @classmethod
    def from_aicore(cls, settings: AgentSettings | None = None) -> ModelBundle:
        resolved = settings or get_agent_settings()
        return cls(
            orchestrator=build_aicore_model("orchestrator", settings=resolved),
            extraction=build_aicore_model("extraction", settings=resolved),
        )


def build_aicore_model(role: ModelRole, *, settings: AgentSettings | None = None) -> Model:
    """Build the SAP AI Core (Generative AI Hub) model for a role via LiteLLM's ``sap/`` route.

    The service key travels as the per-call ``api_key`` (LiteLLM's SAP provider treats it
    as the service key), so credentials stay in settings and never touch ``os.environ``.
    """
    resolved = settings or get_agent_settings()
    model_id = resolved.aicore_model_for(role).strip()
    if not model_id:
        raise MissingModelError(_AICORE_MODEL_VARIABLE[role])
    credentials = resolved.aicore_credentials
    if not credentials:
        raise ModelConfigurationError(
            "SAP AI Core credentials are not set; provide AICORE_SERVICE_KEY (or "
            "AICORE_CLIENT_ID / AICORE_CLIENT_SECRET / AICORE_AUTH_URL / AICORE_BASE_URL) in .env"
        )
    from strands.models.litellm import LiteLLMModel

    # Build LiteLLM's unbuilt SDK models (streamed tool calls) and cache its per-call lookups.
    prepare_litellm()
    return LiteLLMModel(
        client_args={
            "api_key": credentials,
            "timeout": resolved.agent_read_timeout_seconds,
            "num_retries": resolved.agent_retry_max_attempts,
        },
        model_id=f"sap/{model_id}",
        params=_params(role, resolved),
    )


def _params(role: ModelRole, settings: AgentSettings) -> dict[str, object]:
    params: dict[str, object] = {"max_tokens": settings.agent_max_tokens}
    if role == "orchestrator" and settings.agent_reasoning_effort is not None:
        # Reasoning models reject a pinned temperature; the rubric, not sampling, decides.
        params["reasoning_effort"] = settings.agent_reasoning_effort
    else:
        params["temperature"] = settings.agent_temperature
    return params


def cap_max_tokens(model: Model, max_tokens: int) -> None:
    """Cap output tokens on any model; LiteLLM keeps it under ``params``."""
    from strands.models.litellm import LiteLLMModel

    if isinstance(model, LiteLLMModel):
        params = dict(model.get_config().get("params") or {})
        params["max_tokens"] = max_tokens
        model.update_config(params=params)
        return
    model.update_config(max_tokens=max_tokens)


__all__ = ["ModelBundle", "build_aicore_model", "cap_max_tokens"]
