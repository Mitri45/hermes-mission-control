"""Tests for the packaged Mission Control Hermes dashboard plugin."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def plugin_root() -> Path:
    return repo_root() / "plugins" / "mission-control" / "dashboard"


def test_mission_control_plugin_manifest():
    manifest = json.loads((plugin_root() / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "mission-control"
    assert manifest["label"] == "Mission Control"
    assert manifest["tab"]["path"] == "/mission-control"
    assert manifest["entry"] == "dist/index.js"
    assert manifest["css"] == "dist/style.css"
    assert manifest["api"] == "plugin_api.py"


def test_mission_control_plugin_api_health():
    plugin_file = plugin_root() / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("mission_control_plugin_api_test", plugin_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/mission-control")
    client = TestClient(app)

    response = client.get("/api/plugins/mission-control/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "plugin": "mission-control",
        "version": "0.6.0",
    }

    fleet_response = client.get("/api/plugins/mission-control/fleet/status")
    assert fleet_response.status_code == 200
    fleet = fleet_response.json()
    assert set(fleet["instances"]) == {"pc", "pi"}
    assert "generated_at" in fleet
    assert fleet["instances"]["pc"]["ok"] in {True, False}

    hindsight_health_response = client.get("/api/plugins/mission-control/hindsight/health")
    assert hindsight_health_response.status_code == 200
    hindsight_health = hindsight_health_response.json()
    assert hindsight_health["backend"] == "hindsight"
    assert hindsight_health["bank_id"]

    hindsight_facts_response = client.get("/api/plugins/mission-control/hindsight/facts?limit=5")
    assert hindsight_facts_response.status_code in {200, 500}
    if hindsight_facts_response.status_code == 200:
        hindsight_facts = hindsight_facts_response.json()
        assert "items" in hindsight_facts
        assert "total" in hindsight_facts

    provider_status_response = client.get("/api/plugins/mission-control/providers/status")
    assert provider_status_response.status_code == 200
    provider_status = provider_status_response.json()
    assert "providers" in provider_status
    assert "summary" in provider_status

    memory_ingest_response = client.get("/api/plugins/mission-control/memory-ingest/metrics")
    assert memory_ingest_response.status_code == 200
    memory_ingest = memory_ingest_response.json()
    assert "checkpoints" in memory_ingest
    assert "totals" in memory_ingest
    assert "dead_letters" in memory_ingest

    digest_stats_response = client.get("/api/plugins/mission-control/digest/stats")
    assert digest_stats_response.status_code == 200
    digest_stats = digest_stats_response.json()
    assert "total_entries" in digest_stats
    assert "by_source" in digest_stats

    digest_list_response = client.get("/api/plugins/mission-control/digest?page=1&page_size=5")
    assert digest_list_response.status_code == 200
    digest_list = digest_list_response.json()
    assert "entries" in digest_list
    assert "groups" in digest_list

    harness_status_response = client.get("/api/plugins/mission-control/harness/status")
    assert harness_status_response.status_code == 200
    harness_status = harness_status_response.json()
    assert "webhook" in harness_status
    assert "config" in harness_status

    harness_sessions_response = client.get("/api/plugins/mission-control/harness/sessions")
    assert harness_sessions_response.status_code == 200
    assert "sessions" in harness_sessions_response.json()

    operations_recent_response = client.get("/api/plugins/mission-control/operations/recent?limit=5")
    assert operations_recent_response.status_code == 200
    assert "events" in operations_recent_response.json()


def test_mission_control_cutover_document_exists():
    doc = repo_root() / "docs" / "consolidation" / "dashboard-cutover.md"
    content = doc.read_text(encoding="utf-8")
    assert "Fleet Health" in content
    assert "Hindsight Bank" in content
    assert "Provider Status" in content
    assert "upstream `hermes dashboard`" in content
    assert "No secrets" in content


def test_mission_control_plugin_dist_assets_exist():
    assert (plugin_root() / "dist" / "index.js").is_file()
    assert (plugin_root() / "dist" / "style.css").is_file()
    bundle = (plugin_root() / "dist" / "index.js").read_text(encoding="utf-8")
    assert "__HERMES_PLUGIN_SDK__" in bundle
    assert "mission-control" in bundle
    assert "/api/plugins/mission-control" in bundle
    assert "Hindsight Bank" in bundle
    assert "Provider Status" in bundle
    assert "Memory Ingest" in bundle
    assert "Daily Digest" in bundle
    assert "Linear Harness" in bundle
    assert "Recent Operations" in bundle


def test_readable_dashboard_theme_is_packaged():
    theme = repo_root() / "themes" / "dima-readable.yaml"
    content = theme.read_text(encoding="utf-8")
    assert "name: dima-readable" in content
    assert "label: Dima Readable" in content
    assert "fontSans:" in content
    assert "customCSS: |" in content
    assert "font-mondwest" in content
    assert "font-expanded" in content
    assert "var(--theme-font-sans)" in content


def test_installer_deploys_plugin_and_theme(tmp_path):
    hermes_repo = tmp_path / "hermes-agent"
    (hermes_repo / "hermes_cli").mkdir(parents=True)
    theme_dir = tmp_path / "dashboard-themes"

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root() / "scripts" / "install_dashboard_plugin.py"),
            "--hermes-repo",
            str(hermes_repo),
            "--theme-dir",
            str(theme_dir),
            "--skip-theme-activation",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (hermes_repo / "plugins" / "mission-control" / "dashboard" / "manifest.json").is_file()
    assert (hermes_repo / "plugins" / "mission-control" / "dashboard" / "dist" / "index.js").is_file()
    assert (theme_dir / "dima-readable.yaml").is_file()
    assert "Installed Mission Control dashboard plugin" in result.stdout
    assert "Installed readable dashboard theme" in result.stdout
