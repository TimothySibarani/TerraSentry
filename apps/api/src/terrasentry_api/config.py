from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    api_cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/terrasentry"

    aws_region: str = "us-east-1"
    bedrock_model_orchestrator: str = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_model_extraction: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

    sap_mode: str = "stub"
    sap_base_url: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
