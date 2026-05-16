"""Cron job management routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import ApiResponse, CronJobsResponse, CronJobUpdate
from app.services.cron_service import cron_service

router = APIRouter(prefix="/cron", tags=["cron"])


def _raise_from_result(result: dict, default_status: int = 404) -> None:
    """Raise HTTPException using service-provided status codes."""
    if result.get("success"):
        return
    raise HTTPException(status_code=result.get("status_code", default_status), detail=result.get("message", "Unknown error"))


@router.get("", response_model=CronJobsResponse)
async def get_cron_jobs(
    instance: Literal["all", "pc", "pi"] = Query(default="all", description="Filter by instance: all, pc, pi"),
):
    """Get list of scheduled cron jobs with optional instance filter."""
    try:
        return cron_service.get_cron_jobs(instance_filter=instance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{job_id}/pause", response_model=ApiResponse)
async def pause_job(job_id: str, instance: Literal["pc", "pi"] = Query(description="Execution instance for this action")):
    """Pause a cron job."""
    result = cron_service.control_job(job_id, "pause", action_instance=instance)
    _raise_from_result(result)
    return ApiResponse(success=True, message=result["message"])


@router.post("/{job_id}/resume", response_model=ApiResponse)
async def resume_job(job_id: str, instance: Literal["pc", "pi"] = Query(description="Execution instance for this action")):
    """Resume a paused cron job."""
    result = cron_service.control_job(job_id, "resume", action_instance=instance)
    _raise_from_result(result)
    return ApiResponse(success=True, message=result["message"])


@router.post("/{job_id}/run", response_model=ApiResponse)
async def run_job(job_id: str, instance: Literal["pc", "pi"] = Query(description="Execution instance for this action")):
    """Trigger a cron job to run immediately."""
    result = cron_service.control_job(job_id, "run", action_instance=instance)
    _raise_from_result(result)
    return ApiResponse(success=True, message=result["message"])


@router.post("/{job_id}/retry", response_model=ApiResponse)
async def retry_job(job_id: str, instance: Literal["pc", "pi"] = Query(description="Execution instance for this action")):
    """Retry the last failed run of a cron job."""
    result = cron_service.control_job(job_id, "retry", action_instance=instance)
    _raise_from_result(result)
    return ApiResponse(success=True, message=result["message"])


@router.patch("/{job_id}", response_model=ApiResponse)
async def update_job(job_id: str, update: CronJobUpdate):
    """Update cron job settings (schedule, enabled, target, instance)."""
    result = cron_service.update_job(job_id, update)
    _raise_from_result(result)
    return ApiResponse(success=True, message=result["message"])


@router.get("/{job_id}/logs")
async def get_job_logs(job_id: str, lines: int = Query(default=50, ge=1, le=500)):
    """Get recent logs for a cron job."""
    result = cron_service.get_job_logs(job_id, lines)
    _raise_from_result(result)
    return result
