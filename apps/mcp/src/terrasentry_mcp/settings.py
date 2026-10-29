"""Environment-backed settings for the MCP server."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    #: Base URL of the running TerraSentry API; runs started here appear in its cockpit.
    terrasentry_api_url: str = "http://localhost:8000"
    #: Bearer token for the API's write endpoints; leave empty when the API runs open.
    terrasentry_api_token: str = ""
    #: Base URL of the cockpit used for links in results.
    cockpit_base_url: str = "http://localhost:3000"
    #: How long a screening tool waits for a verdict before returning the run id to poll.
    mcp_wait_seconds: float = 40.0
    mcp_poll_interval_seconds: float = 1.0
    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8090


@lru_cache
def get_mcp_settings() -> McpSettings:
    return McpSettings()


__all__ = ["McpSettings", "get_mcp_settings"]
