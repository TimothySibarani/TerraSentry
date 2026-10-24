"""Environment-backed settings for the agent runtime.

Orchestration/verification and extraction are roles; the concrete model for each
role is chosen per environment, never hardcoded here: ``AICORE_MODEL_*`` for the
``sap`` mode (SAP AI Core / Generative AI Hub). Nothing validates credentials; a
live path fails when it is actually invoked, not at import time.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelRole = Literal["orchestrator", "extraction"]


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    agent_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    agent_max_tokens: int = Field(default=8192, gt=0)
    #: Opt-in model reasoning for the orchestrator role (``AGENT_REASONING_EFFORT``). When set,
    #: LiteLLM's ``reasoning_effort`` is sent and the reasoning shows in the trace; off by default
    #: because not every SAP AI Core model accepts it.
    agent_reasoning_effort: Literal["low", "medium", "high"] | None = None
    agent_retry_max_attempts: int = Field(default=5, ge=1, le=10)
    agent_read_timeout_seconds: int = Field(default=120, gt=0)
    #: SAP AI Core credentials: either the whole keybroker service-key JSON, or
    #: the individual fields below (the shape Cloud Foundry env vars use).
    aicore_service_key: str = ""
    aicore_client_id: str = ""
    aicore_client_secret: str = ""
    aicore_auth_url: str = ""
    aicore_base_url: str = ""
    aicore_resource_group: str = "default"
    aicore_model_orchestrator: str = ""
    aicore_model_extraction: str = ""
    # Web-search model for adverse-media context (Sonar); optional, only used when ADVERSE_MEDIA_MODE=live.
    aicore_model_media: str = ""

    def aicore_model_for(self, role: ModelRole) -> str:
        if role == "orchestrator":
            return self.aicore_model_orchestrator
        return self.aicore_model_extraction

    @property
    def aicore_credentials(self) -> str:
        """Service-key JSON for LiteLLM's ``sap/`` provider, or ``""`` when unset.

        An explicit ``AICORE_SERVICE_KEY`` wins; otherwise the individual fields are
        assembled into the same shape. LiteLLM normalises the auth/base URL suffixes and
        falls back to the ``default`` resource group when a service key does not carry one.
        """
        if self.aicore_service_key.strip():
            return self.aicore_service_key.strip()
        if not (
            self.aicore_client_id.strip()
            and self.aicore_client_secret.strip()
            and self.aicore_auth_url.strip()
            and self.aicore_base_url.strip()
        ):
            return ""
        return json.dumps(
            {
                "clientid": self.aicore_client_id.strip(),
                "clientsecret": self.aicore_client_secret.strip(),
                "url": self.aicore_auth_url.strip(),
                "serviceurls": {"AI_API_URL": self.aicore_base_url.strip()},
                "resource_group": self.aicore_resource_group.strip() or "default",
            }
        )

    @property
    def missing_aicore(self) -> list[str]:
        missing: list[str] = []
        if not self.aicore_credentials:
            missing.append("AICORE_SERVICE_KEY")
        if not self.aicore_model_orchestrator.strip():
            missing.append("AICORE_MODEL_ORCHESTRATOR")
        if not self.aicore_model_extraction.strip():
            missing.append("AICORE_MODEL_EXTRACTION")
        return missing


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()


__all__ = ["AgentSettings", "ModelRole", "get_agent_settings"]
