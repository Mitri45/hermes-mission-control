"""Mission Control chat service backed by the real Hermes runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_SCRIPT = REPO_ROOT / "scripts" / "mission_control_chat_turn.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from hermes_state import SessionDB
except ModuleNotFoundError:
    SessionDB = None  # type: ignore[assignment]

from app.models.schemas import ChatMessage, ChatResponse, ChatSessionResponse


class ChatService:
    """Stateful Mission Control chat facade for the web UI."""

    def __init__(self):
        self._session_db = SessionDB() if SessionDB is not None else None
        self._runtime_python = self._resolve_runtime_python()

    def _resolve_runtime_python(self) -> Path:
        candidate = REPO_ROOT / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
        candidate = REPO_ROOT / "venv" / "bin" / "python"
        if candidate.exists():
            return candidate
        return Path(sys.executable)

    @staticmethod
    def _derive_session_id(seed: str) -> str:
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
        return f"mc_{digest}"

    def normalize_session_id(self, session_id: str | None) -> str:
        cleaned = (session_id or "").strip()
        if cleaned and _SAFE_SESSION_ID.fullmatch(cleaned):
            return cleaned
        return self._derive_session_id("mission-control-default")

    async def send_message(self, message: str, session_id: str | None = None) -> ChatResponse:
        normalized_session_id = self.normalize_session_id(session_id)
        if not RUNNER_SCRIPT.exists():
            raise RuntimeError(f"Mission Control chat runner is missing: {RUNNER_SCRIPT}")

        payload = {
            "session_id": normalized_session_id,
            "message": message,
        }

        def _run_subprocess() -> dict[str, object]:
            completed = subprocess.run(
                [str(self._runtime_python), str(RUNNER_SCRIPT)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                cwd=str(REPO_ROOT),
                check=True,
            )
            return json.loads(completed.stdout)

        result = await asyncio.to_thread(_run_subprocess)
        transcript = await self.get_session(normalized_session_id)

        return ChatResponse(
            response=str(result.get("response") or ""),
            type="text",
            session_id=normalized_session_id,
            model=str(result.get("model") or "") or None,
            provider=str(result.get("provider") or "") or None,
            base_url=str(result.get("base_url") or "") or None,
            message_count=transcript.message_count,
        )

    async def get_session(self, session_id: str | None) -> ChatSessionResponse:
        normalized_session_id = self.normalize_session_id(session_id)
        if self._session_db is None:
            return ChatSessionResponse(
                session_id=normalized_session_id,
                model=None,
                provider=None,
                base_url=None,
                message_count=0,
                messages=[],
            )

        session_row = await asyncio.to_thread(self._session_db.get_session, normalized_session_id)
        rows = await asyncio.to_thread(self._session_db.get_messages, normalized_session_id)

        messages = [
            ChatMessage(
                role=str(row.get("role") or "unknown"),
                content=row.get("content"),
                timestamp=(None if row.get("timestamp") is None else datetime.fromtimestamp(float(row["timestamp"]))),
                tool_name=row.get("tool_name"),
            )
            for row in rows
            if isinstance(row, dict)
        ]

        return ChatSessionResponse(
            session_id=normalized_session_id,
            model=(session_row or {}).get("model") if isinstance(session_row, dict) else None,
            provider=None,
            base_url=None,
            message_count=len(messages),
            messages=messages,
        )
