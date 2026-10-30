"""Configuration settings for LifeRescue API."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    nebius_model: str | None = Field(default=None)
    nvidia_base_url: str = Field(default="https://api.tokenfactory.nebius.com/v1/")
    nebius_base_url: str | None = Field(default=None)
    ai_timeout_s: float = Field(default=20.0, ge=1.0, le=60.0)

    @property
    def effective_model(self) -> str:
        return self.nebius_model or self.nvidia_model

    @property
    def effective_base_url(self) -> str:
        return self.nebius_base_url or self.nvidia_base_url

    # KAN-50: Tavily Search API key for live external research evidence (optional).
    tavily_api_key: str | None = Field(default=None, repr=False)
    # SEC-04: shared demo token. REQUIRED when host is not 127.0.0.1/localhost. Env var only; never commit.
    demo_access_token: str | None = Field(default=None, repr=False)
    # LR 08 N-05: DEMO_REQUIRE_TOKEN=1 forces the token even on localhost (use with any tunnel/proxy).
    demo_require_token: bool = Field(default=False)
    # SEC-06: explicit CORS allowlist (comma-separated). Empty -> localhost/127.0.0.1 on `port`.
    cors_origins: str = Field(default="")
    # KAN-50: per-client-IP limit on POST create/analyze/scenario-run/reset (0 disables).
    rate_limit_requests: int = Field(default=20, ge=0, le=10_000)
    rate_limit_window_s: float = Field(default=60.0, ge=1.0, le=86_400.0)
    # Honor the rightmost (proxy-appended) X-Forwarded-For hop only behind a trusted proxy (e.g. Render): TRUST_PROXY=1.
    trust_proxy: bool = Field(default=False)
    # Global per-minute rate limit on outbound model calls (all clients, all workers sharing db_path); 0 = no cap.
    ai_global_calls_per_minute: int = Field(default=30, ge=0, le=10_000)
    # Model calls per rolling 24 h window, all clients/workers; 0 = no live model calls at all.
    ai_daily_call_budget: int = Field(default=500, ge=0, le=1_000_000)

    def cors_allowlist(self) -> list[str]:
        if self.cors_origins.strip():
            return [
                o.strip().rstrip("/")
                for o in self.cors_origins.split(",")
                if o.strip() and o.strip() != "*"
            ]
        return [f"http://localhost:{self.port}", f"http://127.0.0.1:{self.port}"]


def get_settings() -> Settings:
    """Settings from environment variables, then .env (pydantic-settings; names are case-insensitive)."""
    return Settings()
