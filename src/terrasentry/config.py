"""Configuration, read from the environment.

Model routing lives here. Hackathon credits are finite, and the orchestrator makes far
fewer calls than the extraction path does -- so they should not use the same model.

Both ids below are served through Amazon Bedrock. Confirm the exact model identifiers
available in your hackathon account and region before the build starts; Bedrock model
ids are region-specific and some require an inference profile prefix (e.g. "apac.").
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    aws_region: str = os.environ.get("AWS_REGION", "ap-southeast-1")

    # Branching decisions and final synthesis: the expensive, low-volume path.
    model_orchestrator: str = os.environ.get("MODEL_ORCHESTRATOR", "")

    # Parsing, normalising, tidying: the cheap, high-volume path.
    model_extraction: str = os.environ.get("MODEL_EXTRACTION", "")

    firms_map_key: str = os.environ.get("FIRMS_MAP_KEY", "")
    gfw_api_key: str = os.environ.get("GFW_API_KEY", "")

    forest_change_backend: str = os.environ.get("FOREST_CHANGE_BACKEND", "cache")

    data_dir: str = os.environ.get("TerraSentry_DATA_DIR", "data")
    max_agent_turns: int = int(os.environ.get("MAX_AGENT_TURNS", "12"))

    def require(self, *names: str) -> None:
        """Fail fast with a useful message instead of a confusing SDK error later."""
        missing = [n for n in names if not getattr(self, n, "")]
        if missing:
            raise RuntimeError(
                "Missing required configuration: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill it in."
            )


settings = Settings()
