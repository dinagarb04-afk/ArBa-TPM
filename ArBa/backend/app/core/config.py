from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "ArBa Promo Volume Predictor"
    api_prefix: str = "/api/v1"
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "arba"
    db_user: str = "arba"
    db_password: SecretStr = SecretStr("arba_dev")
    jwt_secret: SecretStr = Field(default=SecretStr("dev-only-secret-change-before-deployment"))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, gt=0, le=1440)
    cors_origins: str = "http://localhost:5173"

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+asyncpg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        ).render_as_string(hide_password=False)

    @property
    def allowed_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",")]
        return [origin for origin in origins if origin]

    @model_validator(mode="after")
    def validate_production_secret(self) -> "Settings":
        if self.app_env.lower() == "production":
            secret = self.jwt_secret.get_secret_value()
            if secret == "dev-only-secret-change-before-deployment" or len(secret) < 32:
                raise ValueError("Production requires a JWT_SECRET of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
