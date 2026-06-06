from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(..., alias="DATABASE_URL")
    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")
    encryption_key: str = Field(..., alias="ENCRYPTION_KEY")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    cors_origins: str = Field("http://localhost:3000", alias="CORS_ORIGINS")

    # Simple in-app login (single shared user). Off by default — when behind oauth2-proxy or
    # for local dev, leave AUTH_ENABLED unset. AUTH_PASSWORD only seeds the credential on first
    # run; after that the hash lives in the metadata DB and is changed via the API.
    auth_enabled: bool = Field(False, alias="AUTH_ENABLED")
    auth_username: str = Field("admin", alias="AUTH_USERNAME")
    auth_password: str = Field("", alias="AUTH_PASSWORD")
    auth_token_ttl_hours: int = Field(168, alias="AUTH_TOKEN_TTL_HOURS")

    # Prometheus scrape endpoint at /metrics (outside /api, so not gated by AUTH_ENABLED).
    # Set METRICS_TOKEN to require `Authorization: Bearer <token>` from the scraper.
    metrics_enabled: bool = Field(True, alias="METRICS_ENABLED")
    metrics_token: str = Field("", alias="METRICS_TOKEN")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def _load() -> Settings:
    return Settings()


settings: Settings = _load()
