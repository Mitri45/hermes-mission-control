"""Helpers for writing Daily Digest entries from cron job runs."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from hermes_constants import get_hermes_home
except ModuleNotFoundError:
    def get_hermes_home() -> Path:
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()

_URL_RE = re.compile(r"https?://[^\s)>\]]+")
_MARKDOWN_RE = re.compile(r"[*_`#>\[\]\|]")
_LOW_SIGNAL_SUMMARIES = {"silent", "---"}


def digest_entries_file() -> Path:
    """Return the append-only digest journal path."""
    return get_hermes_home() / "mission-control" / "digests" / "entries.jsonl"


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clean_text(text: str) -> str:
    """Collapse markdown-heavy output into a short preview-safe string."""
    cleaned = _MARKDOWN_RE.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _summary_from_response(response: str) -> str:
    """Build a compact digest summary from the job response body."""
    lines = [line.strip() for line in (response or "").splitlines() if line.strip()]
    if not lines:
        return ""
    for line in lines:
        if line.startswith(("Cronjob Response:", "Note: The agent cannot see")):
            continue
        cleaned = _clean_text(line)
        if cleaned:
            return cleaned[:500]
    return _clean_text(response)[:500]


def _content_from_response(response: str) -> str | None:
    content = (response or "").strip()
    return content or None


def _is_low_signal_summary(summary: str) -> bool:
    normalized = _clean_text(summary).strip().lower()
    return not normalized or normalized in _LOW_SIGNAL_SUMMARIES or normalized.startswith("silent")


def _infer_source(job: dict[str, Any], response: str) -> str:
    """Infer digest source classification from job metadata/content."""
    skills = [str(skill).strip().lower() for skill in job.get("skills") or [] if str(skill).strip()]
    job_name = str(job.get("name") or "").lower()
    response_lower = response.lower()
    if "arxiv" in skills or "arxiv" in job_name or "arxiv.org" in response_lower:
        return "arxiv"
    if "http://" in response_lower or "https://" in response_lower:
        return "web"
    return "custom"


def _infer_tags(job: dict[str, Any], source: str) -> list[str]:
    tags: list[str] = []
    for skill in job.get("skills") or []:
        normalized = str(skill).strip().lower()
        if normalized and normalized not in tags:
            tags.append(normalized)
    if source not in tags:
        tags.append(source)
    return tags[:8]


def _extract_source_url(response: str) -> str | None:
    match = _URL_RE.search(response or "")
    return match.group(0) if match else None


def build_digest_entry(
    job: dict[str, Any],
    response: str,
    *,
    run_at: datetime,
    source_instance: str = "pi",
    output_file: str | None = None,
) -> dict[str, Any] | None:
    """Build a digest entry payload from a successful cron run."""
    summary = _summary_from_response(response)
    if _is_low_signal_summary(summary):
        return None

    run_at = _ensure_utc(run_at)
    source = _infer_source(job, response)
    job_id = str(job.get("id") or "")
    entry_id = f"dig_{uuid.uuid5(uuid.NAMESPACE_URL, f'{job_id}:{run_at.isoformat()}').hex[:16]}"
    return {
        "id": entry_id,
        "title": str(job.get("name") or job.get("id") or "Cron Job"),
        "summary": summary,
        "content": _content_from_response(response),
        "source": source,
        "source_url": _extract_source_url(response),
        "source_instance": source_instance,
        "tags": _infer_tags(job, source),
        "ingested_at": run_at.isoformat(),
        "updated_at": run_at.isoformat(),
        "replicated_at": None,
        "replication_seq": None,
        "metadata": {
            "job_id": str(job.get("id") or ""),
            "job_name": str(job.get("name") or ""),
            "schedule_display": str(job.get("schedule_display") or ""),
            "skills": list(job.get("skills") or []),
            "deliver": str(job.get("deliver") or ""),
            "output_file": output_file,
        },
    }


def append_digest_entry(entry: dict[str, Any]) -> bool:
    """Append a digest entry unless the same id already exists."""
    path = digest_entries_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids: set[str] = set()
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("id"):
                existing_ids.add(str(payload["id"]))

    entry_id = str(entry.get("id") or "")
    if not entry_id or entry_id in existing_ids:
        return False

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return True


def append_digest_for_job_run(
    job: dict[str, Any],
    response: str,
    *,
    run_at: datetime,
    source_instance: str = "pi",
    output_file: str | None = None,
) -> bool:
    """Build and append a digest entry for a cron run."""
    entry = build_digest_entry(
        job,
        response,
        run_at=run_at,
        source_instance=source_instance,
        output_file=output_file,
    )
    if not entry:
        return False
    return append_digest_entry(entry)
