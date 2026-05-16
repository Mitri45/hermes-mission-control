"""Security-focused settings tests for production deployment."""

from pathlib import Path

import pytest

from app.core.config import Settings


def test_production_rejects_default_bearer_token(tmp_path: Path):
    """Production config must not run with default dev token."""
    with pytest.raises(ValueError, match="bearer_token must be set"):
        Settings(
            environment="production",
            hermes_home=tmp_path,
            memory_ingest_hmac_secret="secret",
            cors_origins=["https://hermes.example"],
            bearer_token="dev-token",
        )


def test_production_rejects_wildcard_cors(tmp_path: Path):
    """Production config must declare explicit origins."""
    with pytest.raises(ValueError, match="cors_origins cannot include '\\*'"):
        Settings(
            environment="production",
            hermes_home=tmp_path,
            memory_ingest_hmac_secret="secret",
            cors_origins=["*"],
            bearer_token="real-token",
        )


def test_production_requires_ingest_hmac_secret(tmp_path: Path):
    """Memory ingest HMAC is mandatory for production."""
    with pytest.raises(ValueError, match="memory_ingest_hmac_secret is required"):
        Settings(
            environment="production",
            hermes_home=tmp_path,
            cors_origins=["https://hermes.example"],
            bearer_token="real-token",
        )


def test_secure_production_defaults_include_hindsight(tmp_path: Path):
    """DIM-237 baseline should default ingest backend to hindsight."""
    settings = Settings(
        environment="production",
        hermes_home=tmp_path,
        memory_ingest_hmac_secret="secret",
        cors_origins=["https://hermes.example"],
        bearer_token="real-token",
    )
    assert settings.memory_ingest_backend == "hindsight"
