"""Mission Control dashboard plugin — backend API routes.

Mounted by the Hermes dashboard at /api/plugins/mission-control/.

This file intentionally starts small. The old standalone Mission Control
service is being migrated into this plugin behind explicit contracts. Keep
core Hermes admin surfaces in upstream dashboard pages; only add ops-only
routes here.
"""

from __future__ import annotations

from fastapi import APIRouter

PLUGIN_NAME = "mission-control"
PLUGIN_VERSION = "0.1.0"

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Readiness endpoint for the Mission Control dashboard plugin."""
    return {
        "status": "ok",
        "plugin": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
    }


@router.get("/summary")
async def summary() -> dict[str, object]:
    """Minimal landing summary while panels are ported.

    The shape is deliberately stable and boring so the scaffold can render a
    useful landing page before fleet health, Hindsight, Linear harness, digest,
    and provider status endpoints are added.
    """
    return {
        "plugin": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "status": "scaffolded",
        "sections": [
            {"id": "fleet-health", "label": "Fleet Health", "status": "planned"},
            {"id": "hindsight", "label": "Hindsight Bank", "status": "planned"},
            {"id": "memory-ingest", "label": "Memory Ingest", "status": "planned"},
            {"id": "linear-harness", "label": "Linear Harness", "status": "planned"},
            {"id": "digest", "label": "Digest", "status": "planned"},
            {"id": "provider-status", "label": "Provider Status", "status": "planned"},
            {"id": "operations", "label": "Operations Stream", "status": "planned"},
        ],
    }
