"""Tests for the packaged Mission Control Hermes dashboard plugin."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[1] / "plugins" / "mission-control" / "dashboard"


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
        "version": "0.1.0",
    }


def test_mission_control_plugin_dist_assets_exist():
    assert (plugin_root() / "dist" / "index.js").is_file()
    assert (plugin_root() / "dist" / "style.css").is_file()
    bundle = (plugin_root() / "dist" / "index.js").read_text(encoding="utf-8")
    assert "__HERMES_PLUGIN_SDK__" in bundle
    assert "mission-control" in bundle
    assert "/api/plugins/mission-control" in bundle
