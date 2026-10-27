"""Configuration settings for LifeRescue API."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "LifeRescue Emergency Platform"
    app_env: str = Field(default="development")
    db_path: str = Field(default="./liferescue.db")
    ai_provider: str = Field(default="mock")
    demo_mode: bool = Field(default=True)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    log_level: str = Field(default="INFO")
    # Nebius Token Factory (OpenAI-compatible) serving NVIDIA Nemotron. Key goes in NEBIUS_API_KEY
    # (NVIDIA_API_KEY accepted as an alias). Never commit it; .env is git-ignored.
    nebius_api_key: str | None = Field(default=None, repr=False)
    nvidia_api_key: str | None = Field(default=None, repr=False)
    nvidia_model: str = Field(default="nvidia/nemotron-3-super-120b-a12b")
    nvidia_base_url: str = Field(default="https://api.tokenfactory.nebius.com/v1/")
    ai_timeout_s: float = Field(default=20.0, ge=1.0, le=60.0)


def get_settings() -> Settings:
    """Settings from environment variables, then .env (pydantic-settings; names are case-insensitive)."""
    return Settings()
