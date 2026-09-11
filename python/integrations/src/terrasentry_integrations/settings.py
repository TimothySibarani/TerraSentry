"""Environment-backed settings for external sources and the response cache."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gfw_api_key: str = ""
    gfw_api_base_url: str = "https://data-api.globalforestwatch.org"
    gfw_api_origin: str = "http://localhost"
    gfw_tcl_dataset: str = "umd_tree_cover_loss"
    gfw_tcl_version: str = "v1.13"
    gfw_rate_limit_per_min: int = 60

    firms_map_key: str = ""
    firms_api_base_url: str = "https://firms.modaps.eosdis.nasa.gov/api"
    firms_source: str = "VIIRS_SNPP_NRT"
    firms_rate_limit_per_10min: int = 300
    firms_day_range_max: int = 5

    cache_backend: Literal["redis", "memory"] = "redis"
    redis_url: str = "redis://localhost:6379/0"
    cache_prefix: str = "ts:cache:v1"
    cache_ttl_seconds: int = 7_776_000
    # Fixture-backed rehearsals: prime the cache from data/fixtures and refuse
    # external calls on a miss (see terrasentry_integrations.fixtures).
    cache_offline: bool = False
    cache_fixtures_dir: str = ""

    # SAP closed loop (M7). ``stub`` is the schema-accurate in-process fallback;
    # ``sandbox`` calls the Business Accelerator Hub with SAP_API_KEY; ``live``
    # uses OAuth client credentials. See docs/setup/sap.md.
    sap_mode: str = "stub"
    sap_base_url: str = ""
    sap_api_key: str = ""
    sap_token_url: str = ""
    sap_client_id: str = ""
    sap_client_secret: str = ""
    sap_rate_limit_per_min: int = 60

    @property
    def has_gfw_key(self) -> bool:
        return bool(self.gfw_api_key.strip())

    @property
    def has_firms_key(self) -> bool:
        return bool(self.firms_map_key.strip())

    @property
    def has_sap_credentials(self) -> bool:
        mode = self.sap_mode.strip().lower()
        if mode == "sandbox":
            return bool(self.sap_base_url.strip() and self.sap_api_key.strip())
        if mode == "live":
            return bool(
                self.sap_base_url.strip()
                and self.sap_token_url.strip()
                and self.sap_client_id.strip()
                and self.sap_client_secret.strip()
            )
        return True

    @property
    def missing_credentials(self) -> list[str]:
        missing: list[str] = []
        if not self.has_gfw_key:
            missing.append("GFW_API_KEY")
        if not self.has_firms_key:
            missing.append("FIRMS_MAP_KEY")
        return missing


@lru_cache
def get_integration_settings() -> IntegrationSettings:
    return IntegrationSettings()
