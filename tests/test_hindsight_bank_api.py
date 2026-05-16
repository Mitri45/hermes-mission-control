"""Tests for DIM-211 Hindsight bank API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from app.services.hindsight_bank_service import hindsight_bank_service

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}


def _fact_payload(fact_id: str = "fact-1") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": fact_id,
        "content": "Pi uses hindsight buffered replication",
        "context": "infrastructure",
        "timestamp": now,
        "source_peer": "pi",
        "entities": ["hindsight"],
        "metadata": {"source_peer": "pi"},
        "tags": ["pi"],
        "document_id": "doc-1",
        "fact_type": "world",
        "created_at": now,
        "updated_at": now,
        "stale_reasons": ["Potential duplicate in same context"],
        "soft_deleted": False,
    }


def test_hindsight_list_facts_route(monkeypatch):
    monkeypatch.setattr(
        hindsight_bank_service,
        "list_facts",
        lambda _params: {
            "items": [_fact_payload()],
            "total": 1,
            "limit": 50,
            "offset": 0,
            "has_more": False,
        },
    )

    client = TestClient(app)
    response = client.get("/api/hindsight/bank/facts?source=all")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "fact-1"


def test_hindsight_health_route(monkeypatch):
    monkeypatch.setattr(
        hindsight_bank_service,
        "health",
        lambda: {
            "backend": "hindsight",
            "ok": True,
            "bank_id": "hermes",
            "base_url": "http://127.0.0.1:9177",
            "error": None,
        },
    )

    client = TestClient(app)
    response = client.get("/api/hindsight/bank/health", headers=AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["bank_id"] == "hermes"


def test_hindsight_get_fact_404(monkeypatch):
    def _missing(_fact_id: str):
        raise KeyError("not found")

    monkeypatch.setattr(hindsight_bank_service, "get_fact", _missing)

    client = TestClient(app)
    response = client.get("/api/hindsight/bank/facts/missing")
    assert response.status_code == 404


def test_hindsight_update_fact_route(monkeypatch):
    monkeypatch.setattr(
        hindsight_bank_service,
        "update_fact",
        lambda *_args, **_kwargs: (_fact_payload("fact-2"), "audit-2"),
    )
    monkeypatch.setattr(hindsight_bank_service, "get_audit_log", lambda _fact_id: [{"id": "audit-2"}])

    client = TestClient(app)
    response = client.put(
        "/api/hindsight/bank/facts/fact-2",
        json={"content": "updated", "context": "preferences"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["fact"]["id"] == "fact-2"
    assert payload["audit_log"][0]["id"] == "audit-2"


def test_hindsight_delete_fact_route(monkeypatch):
    monkeypatch.setattr(hindsight_bank_service, "delete_fact", lambda *_args, **_kwargs: "audit-3")

    client = TestClient(app)
    response = client.delete("/api/hindsight/bank/facts/fact-3?soft_delete=true", headers=AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["audit_id"] == "audit-3"


def test_hindsight_bulk_delete_validation(monkeypatch):
    def _bulk(_ids, soft_delete: bool = True):
        if not soft_delete:
            raise ValueError("Bulk hard delete is disabled for safety")
        return _ids, "audit-4"

    monkeypatch.setattr(hindsight_bank_service, "bulk_delete", _bulk)

    client = TestClient(app)
    response = client.post(
        "/api/hindsight/bank/facts/bulk-delete",
        json={"fact_ids": ["a", "b"], "soft_delete": False},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"].lower()
