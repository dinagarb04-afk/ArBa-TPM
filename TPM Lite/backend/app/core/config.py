from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ArBa Trade Promotion Plan capability API"
    app_env: Literal["local", "test", "staging", "production"] = "local"
    database_url: str = "postgresql+asyncpg://localhost:5432/tpm_lite"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    dashboard_upcoming_period_weeks: int = Field(default=4, ge=1, le=52)

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
