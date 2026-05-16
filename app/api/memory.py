"""Memory management routes."""

from fastapi import APIRouter

from app.models.schemas import MemoryResponse
from app.services.memory_service import memory_service

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=MemoryResponse)
async def get_memory():
    """Get memory entries and personality info."""
    return memory_service.get_memory()
