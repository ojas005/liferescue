"""Configuration settings for LifeRescue API."""

from __future__ import annotations

import os
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
    nvidia_api_key: str | None = Field(default=None)
    nvidia_model: str = Field(default="meta/llama-3.1-70b-instruct")
    nvidia_base_url: str = Field(default="https://integrate.api.nvidia.com/v1")


def get_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        db_path=os.getenv("DB_PATH", "./liferescue.db"),
        ai_provider=os.getenv("AI_PROVIDER", "mock"),
        demo_mode=os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes"),
        nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
        nvidia_model=os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"),
        nvidia_base_url=os.getenv(
            "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
        ),
    )
