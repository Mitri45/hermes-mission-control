"""Provider visibility routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import ProviderStatusResponse
from app.services.provider_status_service import provider_status_service

router = APIRouter(prefix="/v1/provider-status", tags=["provider-status"])


@router.get("", response_model=ProviderStatusResponse)
async def get_provider_status(
    instance: Literal["all", "pc", "pi"] = Query(default="all", description="Filter providers by instance"),
):
    """Get consolidated provider status across known Hermes flows."""
    try:
        return provider_status_service.get_provider_status(instance=instance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
