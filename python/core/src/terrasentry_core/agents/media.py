"""Build the optional adverse-media lookup for a run (``ADVERSE_MEDIA_MODE=off|stub|live``)."""

from __future__ import annotations

from terrasentry_integrations.cache import CacheBackend
from terrasentry_integrations.settings import IntegrationSettings, get_integration_settings
from terrasentry_integrations.sources.media import AdverseMediaClient, MediaSearch, StubMediaClient

from terrasentry_core.agents.settings import AgentSettings, get_agent_settings
from terrasentry_core.errors import MissingModelError, ModelConfigurationError


def build_media_client(
    cache: CacheBackend,
    *,
    integration: IntegrationSettings | None = None,
    settings: AgentSettings | None = None,
) -> MediaSearch | None:
    """Return the lookup for the configured mode, or ``None`` when adverse media is off.

    ``live`` reuses the SAP AI Core credentials of ``--model sap`` and needs ``AICORE_MODEL_MEDIA``.
    """
    resolved = integration or get_integration_settings()
    if resolved.adverse_media_mode == "off":
        return None
    if resolved.adverse_media_mode == "stub":
        return StubMediaClient()
    agent = settings or get_agent_settings()
    model = agent.aicore_model_media.strip()
    if not model:
        raise MissingModelError("AICORE_MODEL_MEDIA")
    if not agent.aicore_credentials:
        raise ModelConfigurationError(
            "ADVERSE_MEDIA_MODE=live needs SAP AI Core credentials; provide AICORE_SERVICE_KEY "
            "(or AICORE_CLIENT_ID / AICORE_CLIENT_SECRET / AICORE_AUTH_URL / AICORE_BASE_URL) in .env"
        )
    return AdverseMediaClient(
        credentials=agent.aicore_credentials,
        model=model,
        cache=cache,
        timeout=resolved.adverse_media_timeout_seconds,
    )


__all__ = ["build_media_client"]
