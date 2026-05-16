"""Linear harness routes."""

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import (
    HarnessStatus,
    HarnessControlResponse,
    SessionsResponse,
    SessionLogsResponse,
    WorkersResponse,
)
from app.services.harness_service import harness_service

router = APIRouter(prefix="/harness", tags=["harness"])


@router.get("/status", response_model=HarnessStatus)
async def get_harness_status():
    """Get Linear harness status including webhook health and configuration."""
    return harness_service.get_harness_status()


@router.get("/sessions", response_model=SessionsResponse)
async def get_sessions():
    """Get list of active agent sessions."""
    sessions = harness_service.get_active_sessions()
    return SessionsResponse(sessions=sessions)


@router.post("/{session_id}/retry", response_model=HarnessControlResponse)
async def retry_session(session_id: str):
    """Retry a failed session."""
    result = harness_service.control_session(session_id, "retry")
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return HarnessControlResponse(**result)


@router.post("/{session_id}/cancel", response_model=HarnessControlResponse)
async def cancel_session(session_id: str):
    """Cancel a running session."""
    result = harness_service.control_session(session_id, "cancel")
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return HarnessControlResponse(**result)


@router.get("/logs/{session_id}", response_model=SessionLogsResponse)
async def get_session_logs(session_id: str):
    """Get logs for a specific session."""
    return harness_service.get_session_logs(session_id)
