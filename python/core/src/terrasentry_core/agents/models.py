"""Model construction for the agent roles.

The app wires Bedrock or SAP AI Core here; tests and the offline demo inject a
:class:`~terrasentry_core.agents.scripted.ScriptedModel` instead, so importing
this module never needs AWS or SAP credentials. Which model fills each role is an
environment decision (``BEDROCK_MODEL_*`` for Bedrock, ``AICORE_MODEL_*`` for the
SAP AI Core ``sap`` mode); there is no default model id in the code.

The bedrock-runtime client follows the live-path best practices: adaptive
retries, an explicit read timeout (Strands applies its own default only when no
client config is passed), explicit ``max_tokens``, and opt-in prompt caching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import ProfileNotFound
from strands.models.model import CacheConfig, Model

from terrasentry_core.agents.settings import AgentSettings, ModelRole, get_agent_settings
from terrasentry_core.errors import MissingModelError, ModelConfigurationError

_MODEL_VARIABLE: dict[ModelRole, str] = {
    "orchestrator": "BEDROCK_MODEL_ORCHESTRATOR",
    "extraction": "BEDROCK_MODEL_EXTRACTION",
}
_AICORE_MODEL_VARIABLE: dict[ModelRole, str] = {
    "orchestrator": "AICORE_MODEL_ORCHESTRATOR",
    "extraction": "AICORE_MODEL_EXTRACTION",
}
CONNECT_TIMEOUT_SECONDS = 10


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

    @classmethod
    def from_aicore(cls, settings: AgentSettings | None = None) -> ModelBundle:
        resolved = settings or get_agent_settings()
        return cls(
            orchestrator=build_aicore_model("orchestrator", settings=resolved),
            extraction=build_aicore_model("extraction", settings=resolved),
        )


def client_config(settings: AgentSettings) -> BotocoreConfig:
    """Adaptive retries plus explicit connect/read timeouts for the runtime client."""
    return BotocoreConfig(
        retries={"max_attempts": settings.agent_retry_max_attempts, "mode": "adaptive"},
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        read_timeout=settings.agent_read_timeout_seconds,
    )


def cache_config(settings: AgentSettings) -> CacheConfig | None:
    """Opt-in prompt caching.

    Off by default: our static prefixes are below the model minimums (Claude
    Sonnet 4.5 needs 1,024 tokens, Haiku 4.5 needs 4,096), so a cache point
    would be silently ignored. ``anthropic`` is the explicit fallback for
    opaque ARN inference profiles, where ``auto`` cannot detect the model.
    """
    if settings.bedrock_prompt_cache == "off":
        return None
    return CacheConfig(strategy=settings.bedrock_prompt_cache)


def _session(settings: AgentSettings) -> boto3.Session:
    try:
        return boto3.Session(
            profile_name=settings.aws_profile,
            region_name=settings.aws_region,
        )
    except ProfileNotFound as exc:
        raise ModelConfigurationError(
            f"AWS profile {settings.aws_profile!r} was not found; "
            "check AWS_PROFILE or run `aws configure list-profiles`"
        ) from exc


def build_model(role: ModelRole, *, settings: AgentSettings | None = None) -> Model:
    """Build the Bedrock model for a role from the configured model id."""
    resolved = settings or get_agent_settings()
    model_id = resolved.model_for(role).strip()
    if not model_id:
        raise MissingModelError(_MODEL_VARIABLE[role])
    from strands.models import BedrockModel

    cached = cache_config(resolved)
    client = client_config(resolved)
    extra: dict[str, Any] = {}
    if resolved.bedrock_reasoning_effort:
        extra["additional_request_fields"] = {"reasoning_effort": resolved.bedrock_reasoning_effort}
    try:
        if resolved.has_profile:
            return BedrockModel(
                boto_session=_session(resolved),
                model_id=model_id,
                temperature=resolved.agent_temperature,
                max_tokens=resolved.agent_max_tokens,
                boto_client_config=client,
                cache_config=cached,
                **extra,
            )
        return BedrockModel(
            region_name=resolved.aws_region,
            model_id=model_id,
            temperature=resolved.agent_temperature,
            max_tokens=resolved.agent_max_tokens,
            boto_client_config=client,
            cache_config=cached,
            **extra,
        )
    except ProfileNotFound as exc:
        raise ModelConfigurationError(
            "AWS profile from the environment could not be found; check "
            "AWS_PROFILE / AWS_DEFAULT_PROFILE or run `aws configure list-profiles`"
        ) from exc


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

    return LiteLLMModel(
        client_args={
            "api_key": credentials,
            "timeout": resolved.agent_read_timeout_seconds,
            "num_retries": resolved.agent_retry_max_attempts,
        },
        model_id=f"sap/{model_id}",
        params={
            "temperature": resolved.agent_temperature,
            "max_tokens": resolved.agent_max_tokens,
        },
    )


def cap_max_tokens(model: Model, max_tokens: int) -> None:
    """Cap output tokens on any model; LiteLLM keeps it under ``params``, Bedrock at the top level."""
    from strands.models.litellm import LiteLLMModel

    if isinstance(model, LiteLLMModel):
        params = dict(model.get_config().get("params") or {})
        params["max_tokens"] = max_tokens
        model.update_config(params=params)
        return
    model.update_config(max_tokens=max_tokens)


__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "ModelBundle",
    "build_aicore_model",
    "build_model",
    "cache_config",
    "cap_max_tokens",
    "client_config",
]
