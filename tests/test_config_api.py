"""Tests for config API compatibility with nested model config shape."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from app import main as main_module
from app.services.config_service import config_service

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}


def _configure_hermes_home(monkeypatch, tmp_path: Path) -> Path:
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(main_module.settings, "hermes_home", hermes_home)
    monkeypatch.setattr(config_service.settings, "hermes_home", hermes_home)
    return hermes_home


def test_get_config_supports_nested_model_shape(monkeypatch, tmp_path):
    hermes_home = _configure_hermes_home(monkeypatch, tmp_path)
    (hermes_home / "config.yaml").write_text(
        """
model:
  provider: kimi-coding
  default: kimi-k2
  base_url: https://api.moonshot.ai/v1
personality: noir
max_turns: 77
linear_backend: codex
""".strip()
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(app)
    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "kimi-k2"
    assert payload["provider"] == "kimi-coding"
    assert payload["base_url"] == "https://api.moonshot.ai/v1"
    assert payload["personality"] == "noir"


def test_update_config_preserves_nested_model_shape(monkeypatch, tmp_path):
    hermes_home = _configure_hermes_home(monkeypatch, tmp_path)
    config_path = hermes_home / "config.yaml"
    config_path.write_text(
        """
model:
  provider: kimi-coding
  default: kimi-k2
  base_url: https://api.moonshot.ai/v1
personality: concise
max_turns: 60
linear_backend: claude-code
""".strip()
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(app)
    response = client.post(
        "/api/config",
        json={"personality": "kawaii", "model": "kimi-k3"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["personality"] == "kawaii"
    assert payload["model"] == "kimi-k3"

    raw = config_path.read_text(encoding="utf-8")
    assert "default: kimi-k3" in raw
    assert "provider: kimi-coding" in raw
