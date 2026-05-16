"""Digest/Daily Digest routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.models.digest import (
    DigestCreateRequest,
    DigestDetailResponse,
    DigestListResponse,
    DigestStatsResponse,
)
from app.services.digest_service import digest_service

router = APIRouter(prefix="/digest", tags=["digest"])


@router.get("", response_model=DigestListResponse)
async def get_digests(
    instance: Literal["all", "pc", "pi"] = Query(default="all", description="Filter by source instance"),
    source: str | None = Query(default=None, description="Filter by source type (arxiv, web, custom, telegram)"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=250, description="Items per page"),
    days: int | None = Query(default=None, ge=1, le=365, description="Filter to last N days"),
):
    """Get paginated digest entries with daily grouping.

    Supports filtering by instance (pc/pi/all) and source type.
    Returns entries grouped by day for easy browsing.
    """
    try:
        return digest_service.get_entries(
            instance_filter=instance,
            source_filter=source,
            page=page,
            page_size=page_size,
            days=days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/stats", response_model=DigestStatsResponse)
async def get_digest_stats(
    instance: Literal["all", "pc", "pi"] = Query(default="all", description="Filter by source instance"),
):
    """Get digest statistics including counts by source and instance."""
    try:
        return digest_service.get_stats(instance_filter=instance)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{entry_id}", response_model=DigestDetailResponse)
async def get_digest(entry_id: str):
    """Get a single digest entry by ID."""
    entry = digest_service.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Digest entry {entry_id} not found")
    return DigestDetailResponse(entry=entry)


@router.post("", response_model=DigestDetailResponse, status_code=201)
async def create_digest(request: DigestCreateRequest):
    """Create a new digest entry.

    This endpoint is primarily for testing and manual entry creation.
    Production entries are typically ingested via cron jobs or webhooks.
    """
    try:
        entry = digest_service.create_entry(request)
        return DigestDetailResponse(entry=entry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
