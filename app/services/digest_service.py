"""Digest service for managing daily digest entries."""

import json
import os
import re
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from app.models.digest import (
    DigestCreateRequest,
    DigestDayGroup,
    DigestEntry,
    DigestListResponse,
    DigestStatsResponse,
)
from app.core.config import get_settings

settings = get_settings()

# Default storage path - can be overridden via env
DIGEST_STORAGE_PATH = Path(
    getattr(settings, 'digest_storage_path', '~/.hermes/mission-control/digests')
).expanduser()


class DigestService:
    """Service for managing digest entries."""

    def __init__(self, storage_path: Path | None = None):
        self.settings = get_settings()
        self.storage_path = storage_path or DIGEST_STORAGE_PATH
        self._entries_file = self.storage_path / "entries.jsonl"

    def _parse_datetime(self, value: str | datetime | None) -> datetime | None:
        """Normalize API/storage datetimes to timezone-aware UTC values."""
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _extract_response_content(self, text: str) -> str | None:
        parts = re.split(r"^## Response\s*$", text, maxsplit=1, flags=re.MULTILINE)
        if len(parts) >= 2:
            content = parts[1].strip()
            return content or None
        content = text.strip()
        return content or None

    def _hydrate_entry_content(self, entry: DigestEntry) -> DigestEntry:
        if entry.content:
            return entry

        output_file = entry.metadata.get("output_file")
        if not isinstance(output_file, str) or not output_file.strip():
            return entry

        path = Path(output_file).expanduser()
        try:
            content = self._extract_response_content(path.read_text(encoding="utf-8"))
        except OSError:
            return entry
        if not content:
            return entry

        return entry.model_copy(update={"content": content})

    def _ensure_storage_path(self) -> None:
        """Create storage directory lazily to avoid import-time side effects."""
        self.storage_path.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked_file(self, path: Path, mode: str, lock_type: int) -> Iterator:
        """Open a file with an advisory lock when available."""
        with open(path, mode, encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), lock_type)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _generate_id(self) -> str:
        """Generate a unique digest entry ID."""
        return f"dig_{uuid.uuid4().hex[:16]}"

    def _parse_entry_line(self, line: str) -> DigestEntry | None:
        """Parse a single JSONL line into a DigestEntry."""
        try:
            data = json.loads(line)
            # Convert ISO strings back to datetime
            for field in ['ingested_at', 'updated_at', 'replicated_at']:
                if data.get(field):
                    data[field] = self._parse_datetime(data[field])
            return DigestEntry(**data)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    def _serialize_entry(self, entry: DigestEntry) -> str:
        """Serialize a DigestEntry to JSONL format."""
        data = entry.model_dump()
        # Convert datetimes to ISO strings
        for field in ['ingested_at', 'updated_at', 'replicated_at']:
            if data.get(field):
                data[field] = data[field].isoformat()
        return json.dumps(data, default=str)

    def _normalized_summary(self, entry: DigestEntry) -> str:
        return " ".join((entry.summary or "").strip().split()).lower()

    def _is_low_signal_entry(self, entry: DigestEntry) -> bool:
        summary = self._normalized_summary(entry)
        return summary in {"", "---"} or summary.startswith("silent")

    def _dedupe_entries(self, entries: list[DigestEntry]) -> list[DigestEntry]:
        """Collapse obvious duplicate digest entries while preserving latest-first order."""
        deduped: list[DigestEntry] = []
        seen: set[tuple[str, str, str, str, str]] = set()

        for entry in sorted(entries, key=lambda item: item.ingested_at, reverse=True):
            if self._is_low_signal_entry(entry):
                continue
            dedupe_key = (
                entry.source_instance,
                entry.source,
                entry.title.strip().lower(),
                self._normalized_summary(entry),
                entry.ingested_at.strftime("%Y-%m-%d"),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            deduped.append(entry)

        return deduped

    def create_entry(self, request: DigestCreateRequest) -> DigestEntry:
        """Create a new digest entry."""
        now = datetime.now(timezone.utc)
        entry = DigestEntry(
            id=self._generate_id(),
            title=request.title,
            summary=request.summary,
            content=request.content,
            source=request.source,
            source_url=request.source_url,
            source_instance=request.source_instance,
            tags=request.tags,
            ingested_at=now,
            updated_at=now,
            metadata=request.metadata,
        )

        self._ensure_storage_path()

        # Append to storage with an exclusive lock for multi-process safety
        with self._locked_file(self._entries_file, 'a', fcntl.LOCK_EX if fcntl else 0) as handle:
            handle.write(self._serialize_entry(entry) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

        return entry

    def _resolve_pi_digest_url(self) -> str | None:
        """Resolve the remote PI digest URL from explicit config or PI status URL."""
        explicit = (self.settings.pi_digest_url or "").strip()
        if explicit:
            return explicit.rstrip("/")

        pi_status_url = (self.settings.pi_status_url or "").strip()
        if pi_status_url:
            parsed = urlparse(pi_status_url)
            if parsed.scheme and parsed.netloc:
                if parsed.path.startswith("/api/"):
                    return f"{parsed.scheme}://{parsed.netloc}/api/digest"
                return f"{parsed.scheme}://{parsed.netloc}/digest"

        webhook_url = (self.settings.linear_webhook_url or "").strip()
        if not webhook_url:
            return None

        parsed = urlparse(webhook_url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}/api/digest"

    def _request_remote_digest_json(self, path_suffix: str = "", params: dict[str, str] | None = None) -> dict:
        """Perform an authenticated request to the remote PI digest API."""
        base_url = self._resolve_pi_digest_url()
        if not base_url:
            raise RuntimeError("PI digest endpoint is not configured")

        url = f"{base_url}{path_suffix}"
        if params:
            query = urlencode({key: value for key, value in params.items() if value != ""})
            if query:
                url = f"{url}?{query}"

        bearer_token = (self.settings.pi_bearer_token or self.settings.bearer_token or "").strip()
        headers = {"Accept": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"PI digest request failed with HTTP {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"PI digest request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("PI digest response was not valid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("PI digest response was not a JSON object")
        return payload

    def _load_local_entries(
        self,
        instance_filter: Literal['all', 'pc', 'pi'] = 'all',
        source_filter: str | None = None,
        days: int | None = None,
    ) -> list[DigestEntry]:
        """Load local digest entries with optional filters."""
        entries: list[DigestEntry] = []
        date_threshold = None
        if days:
            date_threshold = datetime.now(timezone.utc) - timedelta(days=days)

        if self._entries_file.exists():
            with open(self._entries_file, 'r', encoding='utf-8') as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    entry = self._parse_entry_line(line)
                    if not entry:
                        continue
                    if instance_filter != 'all' and entry.source_instance != instance_filter:
                        continue
                    if source_filter and entry.source != source_filter:
                        continue
                    if date_threshold and entry.ingested_at < date_threshold:
                        continue
                    entries.append(entry)

        return self._dedupe_entries(entries)

    def _fetch_remote_entries(
        self,
        source_filter: str | None = None,
        page: int = 1,
        page_size: int = 50,
        days: int | None = None,
    ) -> list[DigestEntry]:
        """Fetch PI digest entries from the remote lightweight API."""
        payload = self._request_remote_digest_json(
            params={
                "instance": "pi",
                "source": source_filter or "",
                "page": str(page),
                "page_size": str(page_size),
                "days": str(days or ""),
            }
        )
        remote_entries = payload.get("entries", [])
        if not isinstance(remote_entries, list):
            raise RuntimeError("PI digest response did not include a valid entries list")

        entries: list[DigestEntry] = []
        for item in remote_entries:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            for field in ['ingested_at', 'updated_at', 'replicated_at']:
                if normalized.get(field):
                    normalized[field] = self._parse_datetime(normalized[field])
            entries.append(DigestEntry(**normalized))
        return self._dedupe_entries(entries)

    def _fetch_remote_stats(self, instance_filter: Literal['all', 'pc', 'pi'] = 'pi') -> DigestStatsResponse:
        """Fetch digest statistics from the remote PI API."""
        payload = self._request_remote_digest_json("/stats", params={"instance": instance_filter})
        return DigestStatsResponse.model_validate(payload)

    def _build_list_response(
        self,
        entries: list[DigestEntry],
        page: int,
        page_size: int,
    ) -> DigestListResponse:
        """Build a paginated/grouped digest response from in-memory entries."""
        entries = self._dedupe_entries(entries)
        entries.sort(key=lambda e: e.ingested_at, reverse=True)
        total = len(entries)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_entries = entries[start_idx:end_idx]

        day_groups: dict[str, list[DigestEntry]] = defaultdict(list)
        for entry in paginated_entries:
            day_key = entry.ingested_at.strftime('%Y-%m-%d')
            day_groups[day_key].append(entry)

        groups = [
            DigestDayGroup(date=date, entries=day_entries, count=len(day_entries))
            for date, day_entries in sorted(day_groups.items(), reverse=True)
        ]

        return DigestListResponse(
            entries=paginated_entries,
            groups=groups,
            total=total,
            page=page,
            page_size=page_size,
            has_more=end_idx < total,
        )

    def _build_stats_response(self, entries: list[DigestEntry]) -> DigestStatsResponse:
        """Build digest statistics from a set of entries."""
        now = datetime.now(timezone.utc)
        last_24h = sum(1 for e in entries if e.ingested_at > now - timedelta(hours=24))
        last_7d = sum(1 for e in entries if e.ingested_at > now - timedelta(days=7))

        by_source: dict[str, int] = defaultdict(int)
        by_instance: dict[str, int] = defaultdict(int)
        for entry in entries:
            by_source[entry.source] += 1
            by_instance[entry.source_instance] += 1

        replication_lag = None
        replicated_entries = [e for e in entries if e.replicated_at]
        if replicated_entries:
            lags = [
                (e.replicated_at - e.ingested_at).total_seconds()
                for e in replicated_entries
                if e.replicated_at
            ]
            if lags:
                replication_lag = sum(lags) / len(lags)

        return DigestStatsResponse(
            total_entries=len(entries),
            by_source=dict(by_source),
            by_instance=dict(by_instance),
            last_24h=last_24h,
            last_7d=last_7d,
            replication_lag_seconds=replication_lag,
        )

    def get_entries(
        self,
        instance_filter: Literal['all', 'pc', 'pi'] = 'all',
        source_filter: str | None = None,
        page: int = 1,
        page_size: int = 50,
        days: int | None = None,
    ) -> DigestListResponse:
        """Get paginated digest entries with optional filters."""
        entries: list[DigestEntry] = []
        should_fetch_remote = instance_filter in {'all', 'pi'} and bool(self._resolve_pi_digest_url())

        if instance_filter == 'pc':
            entries.extend(self._load_local_entries('pc', source_filter=source_filter, days=days))
        elif instance_filter == 'pi':
            if should_fetch_remote:
                entries.extend(self._fetch_remote_entries(source_filter=source_filter, page=1, page_size=250, days=days))
            else:
                entries.extend(self._load_local_entries('pi', source_filter=source_filter, days=days))
        else:
            entries.extend(self._load_local_entries('pc' if should_fetch_remote else 'all', source_filter=source_filter, days=days))
            if should_fetch_remote:
                entries.extend(self._fetch_remote_entries(source_filter=source_filter, page=1, page_size=250, days=days))

        return self._build_list_response(entries, page=page, page_size=page_size)

    def get_entry(self, entry_id: str) -> DigestEntry | None:
        """Get a single digest entry by ID."""
        if not self._entries_file.exists():
            if self._resolve_pi_digest_url():
                try:
                    payload = self._request_remote_digest_json(f"/{entry_id}")
                    entry_payload = payload.get("entry")
                    if isinstance(entry_payload, dict):
                        normalized = dict(entry_payload)
                        for field in ['ingested_at', 'updated_at', 'replicated_at']:
                            if normalized.get(field):
                                normalized[field] = self._parse_datetime(normalized[field])
                        return self._hydrate_entry_content(DigestEntry(**normalized))
                except RuntimeError:
                    return None
            return None

        with open(self._entries_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = self._parse_entry_line(line)
                if entry and entry.id == entry_id:
                    return self._hydrate_entry_content(entry)

        if self._resolve_pi_digest_url():
            try:
                payload = self._request_remote_digest_json(f"/{entry_id}")
                entry_payload = payload.get("entry")
                if isinstance(entry_payload, dict):
                    normalized = dict(entry_payload)
                    for field in ['ingested_at', 'updated_at', 'replicated_at']:
                        if normalized.get(field):
                            normalized[field] = self._parse_datetime(normalized[field])
                    return self._hydrate_entry_content(DigestEntry(**normalized))
            except RuntimeError:
                return None
        return None

    def get_stats(self, instance_filter: Literal['all', 'pc', 'pi'] = 'all') -> DigestStatsResponse:
        """Get digest statistics for the requested instance filter."""
        should_fetch_remote = instance_filter in {'all', 'pi'} and bool(self._resolve_pi_digest_url())

        if instance_filter == 'pc':
            return self._build_stats_response(self._load_local_entries('pc'))
        elif instance_filter == 'pi':
            if should_fetch_remote:
                return self._build_stats_response(self._fetch_remote_entries(page=1, page_size=1000))
            return self._build_stats_response(self._load_local_entries('pi'))

        entries = self._load_local_entries('pc' if should_fetch_remote else 'all')
        if should_fetch_remote:
            entries.extend(self._fetch_remote_entries(page=1, page_size=1000))
        return self._build_stats_response(entries)

    def mark_replicated(
        self,
        entry_id: str,
        replicated_at: datetime,
        seq: int,
    ) -> bool:
        """Mark an entry as replicated (for dual-instance sync)."""
        if not self._entries_file.exists():
            return False

        if replicated_at.tzinfo is None:
            replicated_at = replicated_at.replace(tzinfo=timezone.utc)
        replicated_at = replicated_at.astimezone(timezone.utc)

        entries: list[DigestEntry] = []
        updated = False

        # Lock the whole read-modify-write sequence to prevent lost updates.
        with self._locked_file(self._entries_file, 'r+', fcntl.LOCK_EX if fcntl else 0) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                entry = self._parse_entry_line(line)
                if entry:
                    if entry.id == entry_id:
                        entry.replicated_at = replicated_at
                        entry.replication_seq = seq
                        updated = True
                    entries.append(entry)

            if not updated:
                return False

            handle.seek(0)
            handle.truncate()
            for entry in entries:
                handle.write(self._serialize_entry(entry) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

        return True


# Singleton instance
digest_service = DigestService()
