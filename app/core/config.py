"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "Mission Control API"
    app_version: str = "0.1.0"
    debug: bool = Field(default=False, description="Enable debug mode")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = Field(default=False, description="Enable auto-reload")

    # Environment
    environment: Literal["development", "staging", "production"] = "development"

    # Security
    cors_origins: list[str] = Field(default=["*"])
    api_key: str | None = Field(default=None, description="Optional API key for authentication")
    bearer_token: str = Field(default="dev-token", description="Bearer token for auth")
    auth_mode: Literal["write", "all"] = Field(
        default="write",
        description="Auth policy for HTTP API routes. 'write' protects mutating routes, 'all' protects all API routes.",
    )
    dashboard_auth_mode: Literal["public", "bearer", "cloudflare"] = Field(
        default="public",
        description="Dashboard access policy. 'cloudflare' requires Cloudflare Access headers.",
    )
    dashboard_shared_secret: str | None = Field(
        default=None,
        description="Optional shared secret required for dashboard requests (header: X-Hermes-Origin-Secret).",
    )
    expose_docs: bool = Field(
        default=False,
        description="Expose OpenAPI docs endpoints in non-development environments.",
    )

    # Paths
    base_dir: Path = Path(__file__).parent.parent.parent
    log_dir: Path = Field(default=Path("logs"))

    # Hermes specific paths
    hermes_home: Path = Field(default=Path.home() / ".hermes")
    worktree_root: Path = Field(default=Path("/tmp/hermes-linear-workers"))
    gateway_config_path: Path = Field(default=Path.home() / ".hermes" / "gateway-config.yaml")

    # Linear harness
    linear_webhook_url: str = Field(default="")
    linear_default_backend: str = Field(default="claude-code")
    pi_status_url: str | None = Field(
        default=None,
        description="Optional full URL for PI Mission Control status endpoint (for example https://pi-host/api/status).",
    )
    pi_digest_url: str | None = Field(
        default=None,
        description="Optional full URL for PI digest endpoint (for example https://pi-host/api/digest).",
    )
    pi_cron_url: str | None = Field(
        default=None,
        description="Optional full URL for PI cron endpoint (for example https://pi-host/api/cron).",
    )
    pi_bearer_token: str | None = Field(
        default=None,
        description="Optional bearer token for the PI Mission Control status endpoint. Falls back to bearer_token.",
    )

    # Memory ingest security + storage
    memory_ingest_hmac_secret: str | None = Field(default=None)
    memory_ingest_hmac_next_secret: str | None = Field(default=None)
    memory_ingest_db: Path | None = Field(default=None)
    memory_ingest_allowed_sources: list[str] = Field(default_factory=lambda: ["127.0.0.1"])
    memory_ingest_max_clock_skew_seconds: int = Field(default=300)
    memory_ingest_nonce_ttl_seconds: int = Field(default=900)
    memory_ingest_backend: Literal["honcho", "hindsight"] = Field(default="hindsight")
    memory_ingest_hindsight_base_url: str | None = Field(default=None)
    memory_ingest_hindsight_api_key: str | None = Field(default=None)
    memory_ingest_hindsight_bank: str = Field(default="hermes")

    # Metrics
    metrics_interval: float = Field(default=2.0, description="Metrics collection interval in seconds")

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        """Validate environment-sensitive security settings and derived paths."""
        if self.memory_ingest_db is None:
            self.memory_ingest_db = self.hermes_home / "memory" / "ingest.db"
        if self.environment == "production" and not self.memory_ingest_hmac_secret:
            raise ValueError("memory_ingest_hmac_secret is required in production")
        if self.environment == "production" and self.bearer_token.strip() in ("", "dev-token"):
            raise ValueError("bearer_token must be set to a non-default value in production")
        if self.environment == "production" and any(origin.strip() == "*" for origin in self.cors_origins):
            raise ValueError("cors_origins cannot include '*' in production")
        return self

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def memory_dir(self) -> Path:
        return self.hermes_home / "memory"

    @property
    def config_file(self) -> Path:
        return self.hermes_home / "config.yaml"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
