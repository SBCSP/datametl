from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
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

    # OpenAPI /docs. Disable in production deploy (see DOCS_ENABLED in .env.deploy.example).
    docs_enabled: bool = Field(True, alias="DOCS_ENABLED")

    # --- Licensing (offline Ed25519 keys; no Stripe secrets in the app) ---
    # DATAMETL_LICENSE_DEV_BYPASS=true → treat as Pro for local docker (never in prod).
    license_dev_bypass: bool = Field(False, alias="DATAMETL_LICENSE_DEV_BYPASS")
    # Optional override of the embedded verify key (base64url 32-byte Ed25519 public key).
    license_public_key: str = Field("", alias="LICENSE_PUBLIC_KEY")

    @field_validator("encryption_key")
    @classmethod
    def _reject_placeholder_encryption_key(cls, v: str) -> str:
        key = (v or "").strip()
        placeholders = {"", "CHANGE_ME", "CHANGE_ME_GENERATE_A_FERNET_KEY"}
        if key in placeholders or key.upper().startswith("CHANGE_ME"):
            raise ValueError(
                "ENCRYPTION_KEY is missing or a placeholder. "
                "Generate one with `make key` (or openssl rand -base64 32) "
                "and set it in .env before starting."
            )
        return key

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def _load() -> Settings:
    return Settings()


settings: Settings = _load()
