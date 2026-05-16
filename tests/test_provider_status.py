"""Tests for provider visibility API (DIM-235)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from app import main as main_module
from app.services.provider_status_service import _PROVIDER_REGISTRY, provider_status_service

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}


def _configure_hermes_home(monkeypatch, tmp_path: Path) -> Path:
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    for meta in _PROVIDER_REGISTRY.values():
        for key in meta.env_keys:
            monkeypatch.delenv(key, raising=False)
        if meta.base_url_env:
            monkeypatch.delenv(meta.base_url_env, raising=False)
    monkeypatch.delenv("HONCHO_ENV_FILE", raising=False)
    monkeypatch.delenv("HINDSIGHT_PROFILE_ENV", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(main_module.settings, "hermes_home", hermes_home)
    monkeypatch.setattr(provider_status_service.settings, "hermes_home", hermes_home)
    return hermes_home


def _write_auth_pool(hermes_home: Path, pool: dict) -> None:
    payload = {
        "version": 1,
        "providers": {},
        "credential_pool": pool,
    }
    (hermes_home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")


def test_provider_status_endpoint_reports_active_and_off_limits(monkeypatch, tmp_path):
    hermes_home = _configure_hermes_home(monkeypatch, tmp_path)

    (hermes_home / "config.yaml").write_text(
        """
model:
  provider: kimi
  default: kimi-k2
  base_url: https://api.moonshot.ai/v1
linear_backend: codex
fallback_providers:
  - provider: minimax
    model: MiniMax-M2.7
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (hermes_home / ".env").write_text("KIMI_API_KEY=sk-kimi-test\n", encoding="utf-8")

    _write_auth_pool(
        hermes_home,
        {
            "openai-codex": [
                {
                    "id": "codex1",
                    "label": "device-code",
                    "auth_type": "oauth",
                    "priority": 0,
                    "source": "device_code",
                    "access_token": "tok-codex",
                    "last_status": "exhausted",
                    "last_status_at": time.time(),
                    "last_error_code": 429,
                }
            ]
        },
    )

    client = TestClient(app)
    response = client.get("/api/v1/provider-status?instance=all", headers=AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()

    providers = {item["provider"]: item for item in payload["providers"]}
    assert "kimi-coding" in providers
    assert providers["kimi-coding"]["status"] == "active"
    assert providers["kimi-coding"]["key_source"] == "env"

    assert "openai-codex" in providers
    assert providers["openai-codex"]["status"] == "off-limits"
    assert providers["openai-codex"]["recovery_eta_seconds"] is not None
    assert providers["openai-codex"]["key_source"] == "device_code"

    assert "minimax" in providers
    assert providers["minimax"]["status"] == "misconfigured"

    assert payload["summary"]["active"] >= 1
    assert payload["summary"]["off_limits"] >= 1


def test_provider_status_endpoint_honors_instance_filter(monkeypatch, tmp_path):
    hermes_home = _configure_hermes_home(monkeypatch, tmp_path)
    (hermes_home / "config.yaml").write_text(
        """
model:
  provider: minimax
  default: MiniMax-M2.7
  base_url: https://api.minimax.io/anthropic
""".strip()
        + "\n",
        encoding="utf-8",
    )

    honcho_env = tmp_path / "honcho.env"
    honcho_env.write_text(
        "DIALECTIC_PROVIDER=anthropic\nDIALECTIC_MODEL=claude-sonnet-4.6\nANTHROPIC_API_KEY=sk-ant-test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HONCHO_ENV_FILE", str(honcho_env))

    client = TestClient(app)
    response = client.get("/api/v1/provider-status?instance=pi", headers=AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()

    providers = payload["providers"]
    assert len(providers) == 1
    assert providers[0]["provider"] == "anthropic"
    assert providers[0]["primary_flows"][0]["instance"] == "pi"


def test_provider_status_includes_hindsight_runtime_flow(monkeypatch, tmp_path):
    hermes_home = _configure_hermes_home(monkeypatch, tmp_path)
    (hermes_home / "config.yaml").write_text(
        """
model:
  provider: kimi
  default: kimi-k2.5
""".strip()
        + "\n",
        encoding="utf-8",
    )

    hindsight_env = tmp_path / "hindsight.env"
    hindsight_env.write_text(
        "\n".join(
            [
                "HINDSIGHT_API_LLM_PROVIDER=anthropic",
                "HINDSIGHT_API_LLM_MODEL=MiniMax-M2.7",
                "HINDSIGHT_API_LLM_BASE_URL=https://api.minimax.io/anthropic",
                "HINDSIGHT_API_LLM_API_KEY=sk-minimax-hindsight",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HINDSIGHT_PROFILE_ENV", str(hindsight_env))

    client = TestClient(app)
    response = client.get("/api/v1/provider-status?instance=pc", headers=AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()

    providers = {item["provider"]: item for item in payload["providers"]}
    assert "anthropic" in providers
    hindsight_flow = next(
        flow for flow in providers["anthropic"]["primary_flows"] if flow["flow"] == "Hindsight Memory"
    )
    assert hindsight_flow["instance"] == "pc"
    assert providers["anthropic"]["status"] == "active"
    assert providers["anthropic"]["key_source"] == "config"


def test_provider_status_endpoint_requires_bearer_auth():
    client = TestClient(app)
    response = client.get("/api/v1/provider-status?instance=all")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid authorization header"
