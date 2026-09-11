from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    api_cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/terrasentry"

    aws_region: str = "us-east-1"
    bedrock_model_orchestrator: str = ""
    bedrock_model_extraction: str = ""

    gfw_api_key: str = ""
    gfw_api_base_url: str = "https://data-api.globalforestwatch.org"
    gfw_api_origin: str = "http://localhost"
    gfw_tcl_version: str = "v1.13"
    firms_map_key: str = ""
    firms_source: str = "VIIRS_SNPP_NRT"

    cache_backend: str = "redis"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 7_776_000

    sap_mode: str = "stub"
    sap_base_url: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
