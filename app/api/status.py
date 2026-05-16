"""System status routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException

from app.models.schemas import SystemStatus
from app.services.system_monitor import system_monitor

router = APIRouter(prefix="/status", tags=["status"])


@router.get("", response_model=SystemStatus)
async def get_system_status(instance: Literal["all", "pc", "pi"] = "all"):
    """Get current system health status.

    Returns CPU temperature, usage, memory, disk, services, and Tailscale info.
    """
    try:
        return system_monitor.get_system_status(instance=instance)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/health", response_model=dict)
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "mission-control-api"}
