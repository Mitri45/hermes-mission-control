"""Cron job management service."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

try:
    from cron.jobs import (
        get_job as scheduler_get_job,
        list_jobs as scheduler_list_jobs,
        pause_job as scheduler_pause_job,
        resume_job as scheduler_resume_job,
        trigger_job as scheduler_trigger_job,
        update_job as scheduler_update_job,
    )
    from cron.scheduler import tick as scheduler_tick
except ModuleNotFoundError:
    scheduler_get_job = None
    scheduler_list_jobs = None
    scheduler_pause_job = None
    scheduler_resume_job = None
    scheduler_trigger_job = None
    scheduler_update_job = None
    scheduler_tick = None

from app.core.config import get_settings
from app.models.schemas import CronJob, CronJobsResponse, CronJobUpdate

_VALID_INSTANCE_FILTERS = {"all", "pc", "pi"}
_VALID_ACTION_INSTANCES = {"pc", "pi"}
_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_VALID_STATUSES = {"active", "paused", "running", "error", "scheduled"}
_VALID_LAST_RESULTS = {"success", "failed", "triggered"}


class CronService:
    """Service for managing cron jobs."""

    def __init__(self):
        self.settings = get_settings()
        self._jobs_lock = threading.Lock()

    def _normalize_scheduler_job(self, job: dict, *, default_instance: str) -> dict:
        """Normalize modern scheduler jobs into the dashboard schema."""
        schedule_value = job.get("schedule")
        schedule_display = job.get("schedule_display")
        if isinstance(schedule_display, str) and schedule_display.strip():
            schedule = schedule_display.strip()
        elif isinstance(schedule_value, dict):
            schedule = str(schedule_value.get("display") or schedule_value.get("expr") or "").strip()
        else:
            schedule = str(schedule_value or "").strip()

        state = str(job.get("state") or "paused").strip().lower()
        if state == "scheduled":
            status = "scheduled"
        elif state in _VALID_STATUSES:
            status = state
        else:
            status = "paused"

        enabled = bool(job.get("enabled", True))
        if not enabled and status == "scheduled":
            status = "paused"

        last_status = str(job.get("last_status") or "").strip().lower()
        if last_status == "ok":
            last_result = "success"
        elif last_status in {"failed", "error"}:
            last_result = "failed"
        elif last_status:
            last_result = "triggered"
        else:
            last_result = None

        failure_reason = job.get("last_error") or job.get("last_delivery_error")
        failure_count = 1 if last_result == "failed" else 0
        has_explicit_instance = bool(str(job.get("instance") or "").strip())
        instance = str(job.get("instance") or default_instance)
        if instance not in {"pc", "pi", "both"}:
            instance = default_instance

        return {
            "id": str(job.get("id") or ""),
            "name": str(job.get("name") or ""),
            "schedule": schedule,
            "status": status,
            "enabled": enabled,
            "target": str(job.get("deliver") or job.get("target") or "local"),
            "instance": instance,
            "last_result": last_result,
            "last_run": job.get("last_run_at"),
            "next_run": job.get("next_run_at"),
            "runtime_seconds": None,
            "failure_reason": failure_reason,
            "failure_count": failure_count,
            "_inferred_instance": not has_explicit_instance,
        }

    def _resolve_pi_cron_url(self) -> str | None:
        """Resolve PI cron URL from explicit config or the PI status base."""
        explicit = (self.settings.pi_cron_url or "").strip()
        if explicit:
            return explicit.rstrip("/")

        pi_status_url = (self.settings.pi_status_url or "").strip()
        if pi_status_url:
            parsed = urlparse(pi_status_url)
            if parsed.scheme and parsed.netloc:
                if parsed.path.startswith("/api/"):
                    return f"{parsed.scheme}://{parsed.netloc}/api/cron"
                return f"{parsed.scheme}://{parsed.netloc}/cron"
        return None

    def _request_remote_pi_json(
        self,
        path_suffix: str = "",
        *,
        method: str = "GET",
        params: dict[str, str] | None = None,
        body: dict | None = None,
    ) -> dict:
        """Perform an authenticated request to the remote PI cron API."""
        base_url = self._resolve_pi_cron_url()
        if not base_url:
            raise RuntimeError("PI cron endpoint is not configured")

        url = f"{base_url}{path_suffix}"
        if params:
            query = urlencode({key: value for key, value in params.items() if value != ""})
            if query:
                url = f"{url}?{query}"

        bearer_token = (self.settings.pi_bearer_token or self.settings.bearer_token or "").strip()
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        request = Request(url, headers=headers, data=data, method=method)
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"PI cron request failed with HTTP {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"PI cron request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("PI cron response was not valid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("PI cron response was not a JSON object")
        return payload

    def _load_local_jobs(self) -> list[dict]:
        """Load and normalize the local scheduler jobs."""
        if scheduler_list_jobs is None:
            return []
        return [
            self._normalize_scheduler_job(job, default_instance="pi")
            for job in scheduler_list_jobs(include_disabled=True)
        ]

    def _fetch_remote_jobs(self, instance_filter: str = "pi") -> list[dict]:
        """Fetch and normalize PI scheduler jobs from the remote lightweight API."""
        payload = self._request_remote_pi_json(params={"instance": instance_filter})
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            raise RuntimeError("PI cron response did not include a valid jobs list")
        normalized: list[dict] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            normalized.append(
                {
                    "id": str(job.get("id") or ""),
                    "name": str(job.get("name") or ""),
                    "schedule": str(job.get("schedule") or ""),
                    "status": str(job.get("status") or "paused"),
                    "enabled": bool(job.get("enabled", True)),
                    "target": str(job.get("target") or "local"),
                    "instance": str(job.get("instance") or "pi"),
                    "last_result": job.get("last_result"),
                    "last_run": job.get("last_run"),
                    "next_run": job.get("next_run"),
                    "runtime_seconds": job.get("runtime_seconds"),
                    "failure_reason": job.get("failure_reason"),
                    "failure_count": int(job.get("failure_count") or 0),
                    "_inferred_instance": False,
                }
            )
        return normalized

    def _read_local_job_logs(self, job_id: str, lines: int) -> list[str]:
        """Read recent local cron log lines from saved markdown output."""
        output_dir = Path(self.settings.hermes_home) / "cron" / "output" / job_id
        if not output_dir.exists():
            return []

        log_files = sorted(output_dir.glob("*.md"), reverse=True)
        collected: list[str] = []
        for log_file in log_files:
            try:
                file_lines = log_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            if not file_lines:
                continue
            collected = file_lines + collected
            if len(collected) >= lines:
                break
        if lines <= 0:
            return collected
        return collected[-lines:]

    def _build_response(self, jobs_data: list[dict], instance_filter: str) -> CronJobsResponse:
        """Convert normalized job dicts into API models."""
        jobs: list[CronJob] = []
        for job_data in jobs_data:
            job_instance = job_data.get("instance", "pc")
            if job_instance not in {"pc", "pi", "both"}:
                job_instance = "pc"
            if instance_filter != "all" and job_instance not in (instance_filter, "both"):
                continue

            next_run_raw = job_data.get("next_run")
            last_run_raw = job_data.get("last_run")
            parsed_next_run = None
            parsed_last_run = None
            if next_run_raw:
                try:
                    parsed_next_run = datetime.fromisoformat(str(next_run_raw))
                except ValueError:
                    parsed_next_run = None
            if last_run_raw:
                try:
                    parsed_last_run = datetime.fromisoformat(str(last_run_raw))
                except ValueError:
                    parsed_last_run = None

            job_status = str(job_data.get("status") or "paused")
            if job_status not in _VALID_STATUSES:
                job_status = "paused"
            last_result = job_data.get("last_result")
            if last_result not in _VALID_LAST_RESULTS:
                last_result = None

            jobs.append(
                CronJob(
                    id=str(job_data.get("id") or ""),
                    name=str(job_data.get("name") or ""),
                    schedule=str(job_data.get("schedule") or ""),
                    next_run=parsed_next_run,
                    last_run=parsed_last_run,
                    status=job_status,
                    enabled=bool(job_data.get("enabled", True)),
                    target=str(job_data.get("target") or ""),
                    instance=job_instance,
                    last_result=last_result,
                    runtime_seconds=job_data.get("runtime_seconds"),
                    failure_reason=job_data.get("failure_reason"),
                    failure_count=int(job_data.get("failure_count") or 0),
                )
            )
        return CronJobsResponse(jobs=jobs)

    def get_cron_jobs(self, instance_filter: str = "all") -> CronJobsResponse:
        """Get list of cron jobs with optional instance filter."""
        if instance_filter not in _VALID_INSTANCE_FILTERS:
            raise ValueError(f"Invalid instance filter: {instance_filter}")

        with self._jobs_lock:
            jobs_data: list[dict] = self._load_local_jobs()
            if instance_filter in {"all", "pi"} and self._resolve_pi_cron_url():
                try:
                    remote_jobs = self._fetch_remote_jobs("pi")
                    if remote_jobs:
                        jobs_data = [
                            job
                            for job in jobs_data
                            if not (job.get("_inferred_instance") and job.get("instance") == "pi")
                        ]
                    jobs_data.extend(remote_jobs)
                except RuntimeError:
                    pass

        return self._build_response(jobs_data, instance_filter)

    def _local_control_job(self, job_id: str, action: str) -> bool:
        if (
            scheduler_pause_job is None
            or scheduler_resume_job is None
            or scheduler_trigger_job is None
            or scheduler_tick is None
        ):
            return False
        if action == "pause":
            return scheduler_pause_job(job_id) is not None
        if action == "resume":
            return scheduler_resume_job(job_id) is not None
        if action in {"run", "retry"}:
            triggered = scheduler_trigger_job(job_id)
            if triggered is not None:
                threading.Thread(
                    target=scheduler_tick,
                    kwargs={"verbose": False},
                    daemon=True,
                    name=f"cron-trigger-{job_id}",
                ).start()
                return True
            return False
        raise ValueError(f"Unknown action: {action}")

    def control_job(self, job_id: str, action: str, action_instance: str) -> dict:
        """Control a cron job (pause, resume, run, retry) for an explicit instance."""
        if action_instance not in _VALID_ACTION_INSTANCES:
            return {"success": False, "status_code": 400, "message": f"Invalid action instance: {action_instance}"}
        if not _JOB_ID_PATTERN.match(job_id):
            return {"success": False, "status_code": 400, "message": f"Invalid job id: {job_id}"}

        with self._jobs_lock:
            try:
                if action_instance == "pi":
                    payload = self._request_remote_pi_json(f"/{job_id}/{action}", method="POST")
                    message = str(payload.get("message") or f"Job {job_id} {action} requested for PI")
                    return {"success": True, "message": message}

                if not self._local_control_job(job_id, action):
                    return {"success": False, "status_code": 404, "message": f"Job not found: {job_id}"}
                return {"success": True, "message": f"Job {job_id} {action} requested for PC"}
            except RuntimeError as exc:
                return {"success": False, "status_code": 500, "message": str(exc)}

    def _find_job_instance(self, job_id: str) -> str | None:
        """Determine which instance owns a job id."""
        if scheduler_get_job is not None and scheduler_get_job(job_id):
            return "pc"
        if self._resolve_pi_cron_url():
            try:
                remote_jobs = self._fetch_remote_jobs("pi")
                if any(job.get("id") == job_id for job in remote_jobs):
                    return "pi"
            except RuntimeError:
                return None
        return None

    def update_job(self, job_id: str, update: CronJobUpdate) -> dict:
        """Update cron job settings."""
        if not _JOB_ID_PATTERN.match(job_id):
            return {"success": False, "status_code": 400, "message": f"Invalid job id: {job_id}"}

        with self._jobs_lock:
            try:
                target_instance = self._find_job_instance(job_id)
                if not target_instance:
                    return {"success": False, "status_code": 404, "message": f"Job not found: {job_id}"}

                payload = update.model_dump(exclude_none=True)
                if target_instance == "pi":
                    result = self._request_remote_pi_json(f"/{job_id}", method="PATCH", body=payload)
                    return {"success": True, "message": str(result.get("message") or f"Job {job_id} updated")}

                updates: dict = {}
                if update.name is not None:
                    updates["name"] = update.name
                if update.schedule is not None:
                    updates["schedule"] = {"kind": "cron", "expr": update.schedule, "display": update.schedule}
                    updates["schedule_display"] = update.schedule
                if update.enabled is not None:
                    updates["enabled"] = update.enabled
                    updates["state"] = "scheduled" if update.enabled else "paused"
                if update.target is not None:
                    updates["deliver"] = update.target
                if update.instance is not None:
                    updates["instance"] = update.instance

                if scheduler_update_job is None:
                    return {"success": False, "status_code": 404, "message": f"Job not found: {job_id}"}
                if scheduler_update_job(job_id, updates) is None:
                    return {"success": False, "status_code": 404, "message": f"Job not found: {job_id}"}
                return {"success": True, "message": f"Job {job_id} updated"}
            except RuntimeError as exc:
                return {"success": False, "status_code": 500, "message": str(exc)}

    def get_job_logs(self, job_id: str, lines: int = 50) -> dict:
        """Get recent logs for a job."""
        if not _JOB_ID_PATTERN.match(job_id):
            return {"success": False, "status_code": 400, "message": f"Invalid job id: {job_id}"}

        if self._resolve_pi_cron_url():
            try:
                remote_jobs = self._fetch_remote_jobs("pi")
                if any(job.get("id") == job_id for job in remote_jobs):
                    return self._request_remote_pi_json(f"/{job_id}/logs", params={"lines": str(lines)})
            except RuntimeError:
                pass

        return {
            "success": True,
            "job_id": job_id,
            "logs": self._read_local_job_logs(job_id, lines),
        }


# Singleton instance
cron_service = CronService()
