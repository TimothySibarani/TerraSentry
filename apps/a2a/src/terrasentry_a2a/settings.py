"""Environment-backed settings for the Joule A2A proxy."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class A2ASettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    #: Base URL of the TerraSentry API the proxy calls (a tunnel URL when the API runs locally).
    terrasentry_api_url: str = "http://localhost:8000"
    #: Bearer token for the API's write endpoints; leave empty when the API runs open.
    terrasentry_api_token: str = ""
    #: Base URL of the cockpit used for links in replies.
    cockpit_base_url: str = "http://localhost:3000"
    #: Joule's agent-request times out at 60 s; reply before it does.
    a2a_reply_budget_seconds: float = 40.0
    a2a_poll_interval_seconds: float = 1.0
    #: Model for the ``investigate`` skill.
    a2a_agent_model: Literal["scripted", "bedrock", "sap"] = "sap"
    #: Guard against a public route burning model quota.
    a2a_max_agent_runs_per_hour: int = 10
    #: Public URL advertised in the agent card; falls back to Cloud Foundry's VCAP_APPLICATION.
    a2a_public_url: str = ""
    port: int = 8080

    @property
    def public_url(self) -> str:
        if self.a2a_public_url:
            return self.a2a_public_url.rstrip("/")
        vcap = json.loads(os.environ.get("VCAP_APPLICATION", "{}"))
        uris = vcap.get("application_uris") or []
        return f"https://{uris[0]}" if uris else f"http://localhost:{self.port}"


@lru_cache
def get_a2a_settings() -> A2ASettings:
    return A2ASettings()


__all__ = ["A2ASettings", "get_a2a_settings"]
