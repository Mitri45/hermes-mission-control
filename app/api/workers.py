"""Worker management routes."""

from fastapi import APIRouter

from app.models.schemas import WorkersResponse
from app.services.harness_service import harness_service

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("", response_model=WorkersResponse)
async def get_workers():
    """Get list of active worker processes."""
    return harness_service.get_workers()
