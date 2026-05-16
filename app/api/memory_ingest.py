"""Memory ingest routes (Pi -> PC replication pipeline)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.models.schemas import (
    DeadLetterResponse,
    MemoryIngestEvent,
    MemoryIngestMetricsResponse,
    MemoryIngestResponse,
)
from app.services.memory_ingest_service import IngestAuthError, get_memory_ingest_service

router = APIRouter(prefix="/memory/ingest", tags=["memory-ingest"])


@router.post("", response_model=MemoryIngestResponse)
async def ingest_memory(request: Request):
    """Accept HMAC-authenticated replicated memory events from Pi."""
    raw_body = await request.body()
    service = get_memory_ingest_service()

    try:
        service.authenticate_request(
            source_ip=request.client.host if request.client else None,
            raw_body=raw_body,
            timestamp=request.headers.get("X-Hermes-Timestamp"),
            nonce=request.headers.get("X-Hermes-Nonce"),
            signature=request.headers.get("X-Hermes-Signature"),
        )
    except IngestAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {exc}") from exc

    events_raw = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events_raw, list):
        raise HTTPException(status_code=422, detail="request body must include an 'events' array")

    events: list[MemoryIngestEvent] = []
    try:
        for item in events_raw:
            events.append(MemoryIngestEvent.model_validate(item))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    return await run_in_threadpool(service.ingest, events)


@router.get("/metrics", response_model=MemoryIngestMetricsResponse)
async def get_memory_ingest_metrics():
    """Get ingest pipeline checkpoints, lag, and dead-letter counters."""
    return get_memory_ingest_service().get_metrics()


@router.get("/dead-letter", response_model=DeadLetterResponse)
async def get_memory_dead_letters(limit: int = Query(default=50, ge=1, le=500)):
    """List dead-lettered ingest events for troubleshooting."""
    return get_memory_ingest_service().get_dead_letters(limit=limit)


@router.get("/health")
def get_memory_ingest_health():
    """Get ingest service backend health (sink + DB wiring)."""
    return get_memory_ingest_service().health()
