"""Unit tests for Hindsight bank service internals."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.hindsight_bank_service import HindsightBankService


def test_overlay_save_prunes_large_maps(tmp_path):
    service = HindsightBankService()
    service._overlay_path = tmp_path / "hindsight_overrides.json"

    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    updated = {
        f"u-{index}": {"content": f"content-{index}", "updated_at": (base_time + timedelta(seconds=index)).isoformat()}
        for index in range(service._MAX_UPDATED_ENTRIES + 7)
    }
    soft_deleted = {
        f"d-{index}": {"deleted_at": (base_time + timedelta(seconds=index)).isoformat(), "mode": "soft"}
        for index in range(service._MAX_SOFT_DELETED_ENTRIES + 9)
    }
    audit = [
        {"id": f"a-{index}", "timestamp": (base_time + timedelta(seconds=index)).isoformat()}
        for index in range(service._MAX_AUDIT_ENTRIES + 11)
    ]

    service._save_overlay({"updated": updated, "soft_deleted": soft_deleted, "audit": audit})

    loaded = json.loads(service._overlay_path.read_text(encoding="utf-8"))
    assert len(loaded["updated"]) == service._MAX_UPDATED_ENTRIES
    assert len(loaded["soft_deleted"]) == service._MAX_SOFT_DELETED_ENTRIES
    assert len(loaded["audit"]) == service._MAX_AUDIT_ENTRIES

    # Ensure newest entries are preserved after prune.
    assert f"u-{service._MAX_UPDATED_ENTRIES + 6}" in loaded["updated"]
    assert f"d-{service._MAX_SOFT_DELETED_ENTRIES + 8}" in loaded["soft_deleted"]
    assert loaded["audit"][-1]["id"] == f"a-{service._MAX_AUDIT_ENTRIES + 10}"


def test_health_recovers_after_transient_hindsight_disable(monkeypatch):
    service = HindsightBankService()
    service._hindsight_enabled = False

    class FakeClient:
        def list_memories(self, **_kwargs):
            return SimpleNamespace()

    monkeypatch.setattr(service, "_ensure_bank", lambda: None)
    monkeypatch.setattr(service, "_get_client", lambda: FakeClient())

    payload = service.health()

    assert payload["ok"] is True
    assert payload["error"] is None
    assert service._hindsight_enabled is True


def test_get_fact_falls_back_to_list_lookup_when_direct_fetch_404(monkeypatch):
    service = HindsightBankService()
    service._hindsight_enabled = True
    monkeypatch.setattr(service, "_ensure_bank", lambda: None)
    calls: list[str] = []

    def fake_http_get(path: str, query=None):
        calls.append(path)
        if path.endswith("/memories/57d1d4ee-5c92-43ee-8a3e-99aa49c8c4c7"):
            raise RuntimeError("Hindsight HTTP 404: not found")
        if path.endswith("/memories/list"):
            return {
                "items": [
                    {
                        "id": "57d1d4ee-5c92-43ee-8a3e-99aa49c8c4c7",
                        "text": "Mission Control architecture correction",
                        "context": "mission_control_architecture_correction",
                        "date": "2026-04-17T00:00:00Z",
                        "fact_type": "world",
                        "entities": "pc",
                    }
                ]
            }
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(service, "_http_get_hindsight_json", fake_http_get)

    fact = service.get_fact("57d1d4ee-5c92-43ee-8a3e-99aa49c8c4c7")

    assert fact.id == "57d1d4ee-5c92-43ee-8a3e-99aa49c8c4c7"
    assert fact.content == "Mission Control architecture correction"
    assert fact.context == "mission_control_architecture_correction"
    assert "/memories/list" in calls[-1]
    assert service._hindsight_enabled is True


def test_get_fact_uses_http_detail_payload(monkeypatch):
    service = HindsightBankService()
    service._hindsight_enabled = True
    monkeypatch.setattr(service, "_ensure_bank", lambda: None)
    monkeypatch.setattr(
        service,
        "_http_get_hindsight_json",
        lambda path, query=None: {
            "id": "57d1d4ee-5c92-43ee-8a3e-99aa49c8c4c7",
            "text": "Mission Control architecture correction",
            "context": "mission_control_architecture_correction",
            "date": "2026-04-17T00:00:00Z",
            "fact_type": "world",
            "entities": ["pc"],
        },
    )

    fact = service.get_fact("57d1d4ee-5c92-43ee-8a3e-99aa49c8c4c7")

    assert fact.id == "57d1d4ee-5c92-43ee-8a3e-99aa49c8c4c7"
    assert fact.content == "Mission Control architecture correction"
    assert fact.fact_type == "world"


def test_normalize_raw_fact_supports_hindsight_http_summary_shape():
    service = HindsightBankService()

    fact = service._normalize_raw_fact(
        {
            "id": "53fe58f3-e6db-4702-b1cf-4e2f79d42706",
            "text": "Cron jobs are working",
            "context": "Mission Control architecture correction",
            "date": "2026-04-13T09:30:52.083372+00:00",
            "fact_type": "world",
            "entities": "Pi, entries.jsonl",
            "tags": [],
        }
    )

    assert fact.id == "53fe58f3-e6db-4702-b1cf-4e2f79d42706"
    assert fact.content == "Cron jobs are working"
    assert fact.context == "Mission Control architecture correction"
    assert fact.fact_type == "world"
    assert fact.entities == ["Pi", "entries.jsonl"]
    assert fact.timestamp is not None
