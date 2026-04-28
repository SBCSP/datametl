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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def _load() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings: Settings = _load()
