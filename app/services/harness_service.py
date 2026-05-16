"""Linear harness service."""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from app.core.config import get_settings
from app.models.schemas import (
    AgentSession,
    HarnessConfig,
    HarnessStatus,
    SessionLogsResponse,
    WebhookStatus,
    WorkerInfo,
    WorkersResponse,
)


class HarnessService:
    """Service for managing Linear harness state."""

    def __init__(self):
        self.settings = get_settings()
        self.worktree_root = Path(self.settings.worktree_root)
        self.sessions_dir = self.settings.hermes_home / "sessions"

    @staticmethod
    def _truncate_text(value: object, limit: int = 200) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        condensed = " ".join(text.split())
        if len(condensed) <= limit:
            return condensed
        return f"{condensed[: limit - 1].rstrip()}…"

    def get_webhook_status(self) -> WebhookStatus:
        """Get webhook health status."""
        # Get webhook URL from config
        webhook_url = self.settings.linear_webhook_url
        if not webhook_url:
            # Try to get from gateway config
            try:
                gateway_config = self.settings.gateway_config_path
                if gateway_config.exists():
                    import yaml

                    with open(gateway_config) as f:
                        config = yaml.safe_load(f)
                        base_url = config.get("base_url", "")
                        if base_url:
                            webhook_url = f"{base_url}/webhooks/linear_agent"
            except Exception:
                pass

        if not webhook_url:
            webhook_url = "https://hermes.taildde77c.ts.net/webhooks/linear_agent"

        # Count events in recent logs (simulated - in production this would come from a database)
        events_24h = 0
        errors_24h = 0
        last_event_at = None

        # Try to find webhook logs
        try:
            log_dir = self.settings.hermes_home / "logs"
            if log_dir.exists():
                cutoff = datetime.utcnow() - timedelta(hours=24)
                for log_file in log_dir.glob("gateway*.log"):
                    try:
                        with open(log_file) as f:
                            for line in f:
                                if "webhook" in line.lower() and "linear" in line.lower():
                                    events_24h += 1
                                    # Parse timestamp if possible
                                    try:
                                        ts_match = re.match(
                                            r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line
                                        )
                                        if ts_match:
                                            ts = datetime.fromisoformat(ts_match.group(1))
                                            if last_event_at is None or ts > last_event_at:
                                                last_event_at = ts
                                    except Exception:
                                        pass
                                if "error" in line.lower():
                                    errors_24h += 1
                    except Exception:
                        continue
        except Exception:
            pass

        status = "healthy" if errors_24h == 0 else "degraded"
        if events_24h == 0:
            status = "unknown"

        return WebhookStatus(
            url=webhook_url,
            status=status,
            last_event_at=last_event_at,
            events_24h=events_24h,
            errors_24h=errors_24h,
        )

    def get_harness_status(self) -> HarnessStatus:
        """Get full harness status."""
        return HarnessStatus(
            webhook=self.get_webhook_status(),
            config=HarnessConfig(
                default_backend=self.settings.linear_default_backend,
                worktree_root=str(self.worktree_root),
            ),
        )

    def get_active_sessions(self) -> list[AgentSession]:
        """Get list of active agent sessions."""
        sessions = []

        if not self.worktree_root.exists():
            return self._load_recent_archived_sessions()

        for worktree_dir in self.worktree_root.iterdir():
            if not worktree_dir.is_dir():
                continue

            # Parse directory name: e.g., "dim_208-abc123" or "DIM-207-abc123"
            match = re.match(r"([a-zA-Z]+[_-]?\d+)-(.+)", worktree_dir.name)
            if not match:
                continue

            issue_id = match.group(1).upper()
            session_suffix = match.group(2)
            session_id = f"{issue_id.lower()}-{session_suffix}"

            # Check for metadata file
            metadata_file = worktree_dir / "metadata.json"
            metadata = {}
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                except Exception:
                    pass

            # Check if process is still running
            pid_file = worktree_dir / "agent.pid"
            status = "unknown"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    if psutil.pid_exists(pid):
                        status = "running"
                    else:
                        status = "completed"
                except Exception:
                    status = "unknown"

            # Get issue title from plan if available
            issue_title = metadata.get("issue_title", f"Issue {issue_id}")
            if not issue_title or issue_title == f"Issue {issue_id}":
                plan_file = worktree_dir / "plans" / "plan.md"
                if plan_file.exists():
                    try:
                        content = plan_file.read_text()
                        title_match = re.search(r"#\s+(.+)", content)
                        if title_match:
                            issue_title = title_match.group(1).strip()
                    except Exception:
                        pass

            # Get start time from directory or metadata
            started_at = metadata.get("started_at")
            if started_at:
                try:
                    started_at = datetime.fromisoformat(started_at)
                except Exception:
                    started_at = datetime.fromtimestamp(worktree_dir.stat().st_ctime)
            else:
                started_at = datetime.fromtimestamp(worktree_dir.stat().st_ctime)

            last_updated_at = datetime.fromtimestamp(worktree_dir.stat().st_mtime)

            # Get prompt from metadata or plan
            prompt = metadata.get("prompt", "")
            if not prompt and plan_file.exists():
                try:
                    content = plan_file.read_text()
                    prompt = content[:200] + "..." if len(content) > 200 else content
                except Exception:
                    pass

            summary = self._truncate_text(metadata.get("summary") or prompt)

            sessions.append(
                AgentSession(
                    id=session_id,
                    issue_id=issue_id,
                    issue_title=issue_title,
                    backend=metadata.get("backend", self.settings.linear_default_backend),
                    status=status,
                    started_at=started_at,
                    worktree=str(worktree_dir),
                    platform=str(metadata.get("platform") or "linear-harness"),
                    base_url=metadata.get("base_url"),
                    message_count=metadata.get("message_count"),
                    last_updated_at=last_updated_at,
                    source="live",
                    summary=summary,
                    prompt=self._truncate_text(prompt, limit=280),
                )
            )

        # Sort by started_at desc
        sessions.sort(key=lambda x: x.started_at, reverse=True)
        if sessions:
            return sessions
        return self._load_recent_archived_sessions()

    def _load_recent_archived_sessions(self, limit: int = 8) -> list[AgentSession]:
        """Fallback to recent Hermes session archives when no live worktrees exist."""
        sessions: list[AgentSession] = []
        if not self.sessions_dir.exists():
            return sessions

        for session_file in sorted(self.sessions_dir.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if session_file.name.startswith("session_cron_"):
                continue
            try:
                payload = json.loads(session_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue

            session_id = str(payload.get("session_id") or session_file.stem.replace("session_", ""))
            platform = str(payload.get("platform") or "cli").strip() or "cli"
            model = str(payload.get("model") or payload.get("backend") or self.settings.linear_default_backend)
            started_at_raw = payload.get("session_start") or payload.get("last_updated")
            try:
                started_at = datetime.fromisoformat(str(started_at_raw)) if started_at_raw else datetime.fromtimestamp(session_file.stat().st_mtime)
            except Exception:
                started_at = datetime.fromtimestamp(session_file.stat().st_mtime)
            last_updated_raw = payload.get("last_updated")
            try:
                last_updated_at = (
                    datetime.fromisoformat(str(last_updated_raw))
                    if last_updated_raw
                    else datetime.fromtimestamp(session_file.stat().st_mtime)
                )
            except Exception:
                last_updated_at = datetime.fromtimestamp(session_file.stat().st_mtime)

            issue_title = str(payload.get("display_name") or payload.get("platform") or "Recent session")
            prompt = str(payload.get("system_prompt") or "")
            issue_id = platform.upper()
            message_count_raw = payload.get("message_count")
            try:
                message_count = int(message_count_raw) if message_count_raw is not None else None
            except (TypeError, ValueError):
                message_count = None
            summary = self._truncate_text(
                payload.get("messages", [{}])[-1].get("content")
                if isinstance(payload.get("messages"), list) and payload.get("messages")
                else payload.get("system_prompt")
            )

            sessions.append(
                AgentSession(
                    id=session_id,
                    issue_id=issue_id,
                    issue_title=issue_title,
                    backend=model,
                    status="recent",
                    started_at=started_at,
                    worktree=str(session_file),
                    platform=platform,
                    base_url=payload.get("base_url"),
                    message_count=message_count,
                    last_updated_at=last_updated_at,
                    source="archive",
                    summary=summary,
                    prompt=self._truncate_text(prompt, limit=280),
                )
            )
            if len(sessions) >= limit:
                break

        sessions.sort(key=lambda x: x.started_at, reverse=True)
        return sessions

    def get_workers(self) -> WorkersResponse:
        """Get list of active worker processes."""
        workers = []

        if not self.worktree_root.exists():
            return WorkersResponse(workers=workers)

        for worktree_dir in self.worktree_root.iterdir():
            if not worktree_dir.is_dir():
                continue

            # Parse directory name
            match = re.match(r"([a-zA-Z]+[_-]?\d+)-(.+)", worktree_dir.name)
            if not match:
                continue

            issue_id = match.group(1).upper()
            session_suffix = match.group(2)
            session_id = f"{issue_id.lower()}-{session_suffix}"

            # Check for PID file
            pid_file = worktree_dir / "agent.pid"
            if not pid_file.exists():
                continue

            try:
                pid = int(pid_file.read_text().strip())
                if not psutil.pid_exists(pid):
                    continue

                proc = psutil.Process(pid)
                runtime = int((datetime.utcnow() - datetime.fromtimestamp(proc.create_time())).total_seconds())

                # Get backend from metadata
                metadata_file = worktree_dir / "metadata.json"
                backend = self.settings.linear_default_backend
                if metadata_file.exists():
                    try:
                        with open(metadata_file) as f:
                            metadata = json.load(f)
                            backend = metadata.get("backend", backend)
                    except Exception:
                        pass

                workers.append(
                    WorkerInfo(
                        session_id=session_id,
                        pid=pid,
                        backend=backend,
                        issue_id=issue_id,
                        runtime_seconds=runtime,
                        log_file=str(worktree_dir / "agent.log"),
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                continue

        return WorkersResponse(workers=workers)

    def get_session_logs(self, session_id: str) -> SessionLogsResponse:
        """Get logs for a specific session."""
        # Parse session_id
        match = re.match(r"([a-zA-Z]+[_-]?\d+)-(.+)", session_id)
        if not match:
            return SessionLogsResponse(session_id=session_id, logs=[])

        # Find worktree
        prefix = match.group(1).lower()
        for worktree_dir in self.worktree_root.iterdir():
            if worktree_dir.name.startswith(prefix):
                log_file = worktree_dir / "agent.log"
                if log_file.exists():
                    try:
                        with open(log_file) as f:
                            logs = f.readlines()
                            return SessionLogsResponse(
                                session_id=session_id,
                                logs=[line.rstrip() for line in logs[-1000:]],  # Last 1000 lines
                            )
                    except Exception:
                        pass
                break

        return SessionLogsResponse(session_id=session_id, logs=[])

    def control_session(self, session_id: str, action: str) -> dict:
        """Control a session (retry, cancel)."""
        # Parse session_id
        match = re.match(r"([a-zA-Z]+[_-]?\d+)-(.+)", session_id)
        if not match:
            return {"success": False, "message": f"Invalid session ID: {session_id}"}

        prefix = match.group(1).lower()
        for worktree_dir in self.worktree_root.iterdir():
            if worktree_dir.name.startswith(prefix):
                pid_file = worktree_dir / "agent.pid"

                if action == "cancel":
                    if pid_file.exists():
                        try:
                            pid = int(pid_file.read_text().strip())
                            if psutil.pid_exists(pid):
                                proc = psutil.Process(pid)
                                proc.terminate()
                                proc.wait(timeout=5)
                                return {
                                    "success": True,
                                    "message": f"Session {session_id} cancelled",
                                    "session_id": session_id,
                                }
                        except Exception as e:
                            return {
                                "success": False,
                                "message": f"Failed to cancel: {e}",
                                "session_id": session_id,
                            }
                    return {
                        "success": False,
                        "message": "Session not running",
                        "session_id": session_id,
                    }

                elif action == "retry":
                    # This would trigger a re-run via the orchestrator
                    # For now, just return success
                    return {
                        "success": True,
                        "message": f"Retry requested for {session_id}",
                        "session_id": session_id,
                    }

        return {"success": False, "message": f"Session not found: {session_id}", "session_id": session_id}


# Singleton instance
harness_service = HarnessService()
