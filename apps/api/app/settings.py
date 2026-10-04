"""Environment-driven settings. No secret values live here: API keys are read ONLY by app/security/keys.py
(the credential_broker adapter) and by the model/tool adapters through it."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://liferescue:liferescue_dev@localhost:5432/liferescue"
DEFAULT_CORS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def normalize_database_url(url: str) -> str:
    """Make plain postgres URLs use the psycopg (v3) driver this project installs."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # Names follow the platform contract (interfaces.model_adapter_from_env): fail closed by default.
    liferescue_env: str = Field(
        default="production", validation_alias=AliasChoices("LIFERESCUE_ENV", "liferescue_env")
    )
    model_adapter: Literal["nebius", "mock"] = Field(
        default="nebius", validation_alias=AliasChoices("LIFERESCUE_MODEL_ADAPTER", "model_adapter")
    )
    log_level: str = "INFO"
    database_url: str = DEFAULT_DATABASE_URL
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: list(DEFAULT_CORS))
    # Per-request/per-run limits (SECURITY-REQUIREMENTS U4)
    max_body_bytes: int = 64 * 1024
    max_input_text_chars: int = 20 * 1024
    max_input_urls: int = 10

    @field_validator("database_url")
    @classmethod
    def _norm_db(cls, v: str) -> str:
        return normalize_database_url(v)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [o.strip() for o in s.split(",") if o.strip()]
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, v: list[str]) -> list[str]:
        if any(o == "*" for o in v):
            raise ValueError("wildcard CORS origin is not allowed")
        return v

    @property
    def docs_enabled(self) -> bool:
        return self.liferescue_env not in ("production", "prod", "staging")

    def database_password(self) -> str | None:
        try:
            from sqlalchemy.engine import make_url

            return make_url(self.database_url).password
        except Exception:  # noqa: BLE001 - unparsable URL: nothing to redact
            return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
