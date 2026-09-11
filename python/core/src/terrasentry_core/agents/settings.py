"""Environment-backed settings for the M3 agent runtime.

Orchestration/verification and extraction are roles; the concrete Bedrock model
for each role is chosen per environment via ``BEDROCK_MODEL_ORCHESTRATOR`` and
``BEDROCK_MODEL_EXTRACTION``, never hardcoded here. Nothing validates
credentials; the live Bedrock path fails when it is actually invoked, not at
import time.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ModelRole = Literal["orchestrator", "extraction"]


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    aws_region: str = "us-east-1"
    aws_profile: str = ""
    bedrock_model_orchestrator: str = ""
    bedrock_model_extraction: str = ""
    agent_temperature: float = 0.0
    agent_max_tokens: int = 2048

    def model_for(self, role: ModelRole) -> str:
        if role == "orchestrator":
            return self.bedrock_model_orchestrator
        return self.bedrock_model_extraction

    @property
    def has_profile(self) -> bool:
        return bool(self.aws_profile.strip())

    @property
    def missing_models(self) -> list[str]:
        missing: list[str] = []
        if not self.bedrock_model_orchestrator.strip():
            missing.append("BEDROCK_MODEL_ORCHESTRATOR")
        if not self.bedrock_model_extraction.strip():
            missing.append("BEDROCK_MODEL_EXTRACTION")
        return missing


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()


__all__ = ["AgentSettings", "ModelRole", "get_agent_settings"]

