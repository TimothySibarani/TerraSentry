from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API-owned configuration.

    Source credentials, cache settings, and Bedrock model ids have canonical
    homes in ``terrasentry_integrations.settings`` and
    ``terrasentry_core.agents.settings``; they are intentionally not duplicated
    here. ``sap_*`` is reserved for the M7 closed loop.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    api_cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/terrasentry"
    auto_seed: bool = True
    seed_data_dir: str = "data/seed"

    agent_model: str = "scripted"
    run_timeout_seconds: int = 900
    batch_concurrency: int = 4
    sse_ping_seconds: int = 15
    firms_window_days: int = 30
    loss_window_years: int = 5

    sap_mode: str = "stub"
    sap_base_url: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
