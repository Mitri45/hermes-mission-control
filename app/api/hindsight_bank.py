"""Hindsight bank management routes (DIM-211)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.models.schemas import (
    HindsightBankStatsResponse,
    HindsightBulkDeleteRequest,
    HindsightFactDetailResponse,
    HindsightFactUpdateRequest,
    HindsightFactsResponse,
    HindsightHealthResponse,
    HindsightMutationResponse,
    HindsightStaleFactsResponse,
)
from app.services.hindsight_bank_service import (
    QueryParams,
    date_to_utc_end,
    date_to_utc_start,
    hindsight_bank_service,
)

router = APIRouter(prefix="/hindsight/bank", tags=["hindsight-bank"])


@router.get("/stats", response_model=HindsightBankStatsResponse)
async def get_bank_stats(source: Literal["all", "pc", "pi"] = "all"):
    """Return high-level bank usage stats."""
    return await run_in_threadpool(hindsight_bank_service.stats, source=source)


@router.get("/health", response_model=HindsightHealthResponse)
async def get_bank_health():
    """Return direct Hindsight API reachability and bank readiness."""
    return await run_in_threadpool(hindsight_bank_service.health)


@router.get("/facts", response_model=HindsightFactsResponse)
async def list_facts(
    q: str | None = None,
    context: str | None = None,
    source: Literal["all", "pc", "pi"] = "all",
    from_date: date | None = None,
    to_date: date | None = None,
    stale_only: bool = False,
    sort: Literal["newest", "oldest"] = "newest",
    limit: int = Query(default=50, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
):
    """List normalized memory facts with filter and pagination support."""
    params = QueryParams(
        q=q,
        context=context,
        source=source,
        from_ts=date_to_utc_start(from_date),
        to_ts=date_to_utc_end(to_date),
        stale_only=stale_only,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return await run_in_threadpool(hindsight_bank_service.list_facts, params)


@router.get("/facts/{fact_id}", response_model=HindsightFactDetailResponse)
async def get_fact(fact_id: str):
    """Fetch one fact and related audit events."""
    try:
        fact = await run_in_threadpool(hindsight_bank_service.get_fact, fact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "fact": fact,
        "audit_log": await run_in_threadpool(hindsight_bank_service.get_audit_log, fact_id),
    }


@router.put("/facts/{fact_id}", response_model=HindsightFactDetailResponse)
async def update_fact(fact_id: str, payload: HindsightFactUpdateRequest):
    """Update fact fields through auditable overlay edits."""
    try:
        fact, _audit_id = await run_in_threadpool(
            hindsight_bank_service.update_fact,
            fact_id,
            content=payload.content,
            context=payload.context,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "fact": fact,
        "audit_log": await run_in_threadpool(hindsight_bank_service.get_audit_log, fact_id),
    }


@router.delete("/facts/{fact_id}", response_model=HindsightMutationResponse)
async def delete_fact(fact_id: str, soft_delete: bool = True):
    """Delete one fact (soft by default, hard for doc-backed facts only)."""
    try:
        audit_id = await run_in_threadpool(hindsight_bank_service.delete_fact, fact_id, soft_delete=soft_delete)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return HindsightMutationResponse(
        success=True,
        message="Fact deleted" if not soft_delete else "Fact soft-deleted",
        affected_ids=[fact_id],
        audit_id=audit_id,
    )


@router.post("/facts/bulk-delete", response_model=HindsightMutationResponse)
async def bulk_delete_facts(payload: HindsightBulkDeleteRequest):
    """Bulk soft-delete facts."""
    try:
        deleted_ids, audit_id = await run_in_threadpool(
            hindsight_bank_service.bulk_delete,
            payload.fact_ids,
            soft_delete=payload.soft_delete,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return HindsightMutationResponse(
        success=True,
        message=f"Soft-deleted {len(deleted_ids)} facts",
        affected_ids=deleted_ids,
        audit_id=audit_id,
    )


@router.get("/search", response_model=HindsightFactsResponse)
async def search_facts(
    q: str = Query(min_length=1),
    source: Literal["all", "pc", "pi"] = "all",
    context: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    sort: Literal["newest", "oldest"] = "newest",
    limit: int = Query(default=50, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
):
    """Full-text search endpoint for facts."""
    params = QueryParams(
        q=q,
        context=context,
        source=source,
        from_ts=date_to_utc_start(from_date),
        to_ts=date_to_utc_end(to_date),
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return await run_in_threadpool(hindsight_bank_service.list_facts, params)


@router.get("/stale", response_model=HindsightStaleFactsResponse)
async def list_stale_facts(source: Literal["all", "pc", "pi"] = "all"):
    """Return stale memory candidates for review workflows."""
    return await run_in_threadpool(hindsight_bank_service.stale_facts, source=source)
