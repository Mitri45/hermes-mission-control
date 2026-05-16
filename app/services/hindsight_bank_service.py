"""Hindsight bank management service for DIM-211."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import asyncio
import inspect
import time as time_module
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from difflib import SequenceMatcher
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from uuid import uuid4

from app.core.config import get_settings
from app.models.schemas import HindsightFact
from app.services.memory_service import memory_service


def _resolve_hindsight_base_url(explicit: str | None = None) -> str:
    """Resolve Hindsight base URL from explicit value or environment variables."""
    if explicit:
        return explicit.strip().rstrip("/")

    api_url = (os.environ.get("HINDSIGHT_API_URL") or os.environ.get("HINDSIGHT_BASE_URL") or "").strip()
    if api_url:
        return api_url.rstrip("/")

    host = (os.environ.get("HINDSIGHT_HOST") or "").strip()
    port = (os.environ.get("HINDSIGHT_PORT") or "").strip()
    scheme = (os.environ.get("HINDSIGHT_SCHEME") or "http").strip() or "http"
    if host:
        if host.startswith(("http://", "https://")):
            return host.rstrip("/")
        if port:
            return f"{scheme}://{host}:{port}"
        return f"{scheme}://{host}"

    return "https://api.hindsight.vectorize.io"


@dataclass(slots=True)
class QueryParams:
    """Fact list/search query parameters."""

    q: str | None = None
    context: str | None = None
    source: Literal["all", "pc", "pi"] = "all"
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    stale_only: bool = False
    sort: Literal["newest", "oldest"] = "newest"
    limit: int = 50
    offset: int = 0


class HindsightBankService:
    """Service wrapper around Hindsight memory APIs with local audit overlays."""

    _MAX_AUDIT_ENTRIES = 2000
    _MAX_UPDATED_ENTRIES = 5000
    _MAX_SOFT_DELETED_ENTRIES = 5000
    _RECOVERY_COOLDOWN_SECONDS = 15.0

    def __init__(self):
        self.settings = get_settings()
        self.base_url = _resolve_hindsight_base_url(self.settings.memory_ingest_hindsight_base_url)
        self.api_key = self.settings.memory_ingest_hindsight_api_key or os.environ.get("HINDSIGHT_API_KEY")
        self.bank_id = (
            self.settings.memory_ingest_hindsight_bank
            or os.environ.get("HINDSIGHT_BANK")
            or os.environ.get("HINDSIGHT_BANK_ID")
            or "hermes"
        ).strip() or "hermes"
        self._client_local = threading.local()
        self._bank_initialized = False
        self._lock = threading.RLock()
        self._overlay_path = self.settings.hermes_home / "memory" / "hindsight_overrides.json"
        self._hindsight_enabled = not (
            not self.api_key and "api.hindsight.vectorize.io" in self.base_url
        )
        self._last_recovery_attempt_monotonic = 0.0

    def _maybe_recover_hindsight(self, *, force: bool = False) -> None:
        """Re-enable Hindsight after transient failures without requiring a process restart."""
        if self._hindsight_enabled:
            return

        now = time_module.monotonic()
        if not force and (now - self._last_recovery_attempt_monotonic) < self._RECOVERY_COOLDOWN_SECONDS:
            return

        self._last_recovery_attempt_monotonic = now
        try:
            self._ensure_bank()
            self._get_client().list_memories(bank_id=self.bank_id, limit=1, offset=0)
        except Exception:
            return

        self._hindsight_enabled = True

    def _get_client(self) -> Any:
        with self._lock:
            client = getattr(self._client_local, "client", None)
            if client is not None:
                return client
            from hindsight_client import Hindsight

            try:
                client = Hindsight(base_url=self.base_url, api_key=self.api_key or None, timeout=30.0)
            except TypeError:
                client = Hindsight(self.base_url, self.api_key or None, 30.0)
            self._client_local.client = client
            return client

    def _reset_client(self) -> None:
        """Close and discard the current thread-local Hindsight client."""
        with self._lock:
            client = getattr(self._client_local, "client", None)
            if client is None:
                return
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    self._resolve_client_result(close())
            except Exception:
                pass
            finally:
                self._client_local.client = None

    @staticmethod
    def _resolve_client_result(value: Any) -> Any:
        """Run coroutine-returning SDK methods from sync service code."""
        if inspect.isawaitable(value):
            return asyncio.run(value)
        return value

    def _ensure_bank(self) -> None:
        if self._bank_initialized:
            return
        client = self._get_client()
        try:
            client.create_bank(bank_id=self.bank_id, name=self.bank_id)
            self._bank_initialized = True
            return
        except Exception as exc:  # pragma: no cover - network-dependent
            message = str(exc).lower()
            if any(token in message for token in ("already exists", "already-exists", "conflict", "409")):
                self._bank_initialized = True
                return
            raise

    def _hindsight_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        token = (self.api_key or "").strip()
        if token:
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        return headers

    def _http_get_hindsight_json(self, path: str, query: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        if query:
            params = {key: value for key, value in query.items() if value is not None}
            if params:
                url = f"{url}?{urlencode(params)}"

        request = Request(url, headers=self._hindsight_headers(), method="GET")
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Hindsight HTTP {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Hindsight request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Hindsight response was not valid JSON") from exc

    @staticmethod
    def _coerce_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        return None

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            out: dict[str, str] = {}
            for key, val in value.items():
                if val is None:
                    continue
                out[str(key)] = str(val)
            return out
        return {}

    @staticmethod
    def _safe_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        return []

    def _overlay_template(self) -> dict[str, Any]:
        return {
            "updated": {},
            "soft_deleted": {},
            "audit": [],
        }

    def _load_overlay(self) -> dict[str, Any]:
        base = self._overlay_template()
        if not self._overlay_path.exists():
            return base
        try:
            data = json.loads(self._overlay_path.read_text(encoding="utf-8"))
        except Exception:
            return base
        if not isinstance(data, dict):
            return base
        updated = data.get("updated")
        soft_deleted = data.get("soft_deleted")
        audit = data.get("audit")
        base["updated"] = updated if isinstance(updated, dict) else {}
        base["soft_deleted"] = soft_deleted if isinstance(soft_deleted, dict) else {}
        base["audit"] = audit if isinstance(audit, list) else []
        return base

    def _save_overlay(self, overlay: dict[str, Any]) -> None:
        self._overlay_path.parent.mkdir(parents=True, exist_ok=True)
        self._prune_overlay(overlay)
        serialized = json.dumps(overlay, indent=2)

        # Write atomically to avoid file corruption on abrupt process termination.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._overlay_path.parent,
            prefix=f"{self._overlay_path.name}.tmp-",
            delete=False,
        ) as tmp:
            tmp.write(serialized)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_name = tmp.name

        os.replace(tmp_name, self._overlay_path)

    def _prune_overlay(self, overlay: dict[str, Any]) -> None:
        updated = overlay.get("updated")
        if isinstance(updated, dict) and len(updated) > self._MAX_UPDATED_ENTRIES:
            sorted_items = sorted(
                updated.items(),
                key=lambda item: self._coerce_datetime(item[1].get("updated_at") if isinstance(item[1], dict) else None)
                or datetime(1970, 1, 1, tzinfo=timezone.utc),
            )
            overlay["updated"] = dict(sorted_items[-self._MAX_UPDATED_ENTRIES :])

        soft_deleted = overlay.get("soft_deleted")
        if isinstance(soft_deleted, dict) and len(soft_deleted) > self._MAX_SOFT_DELETED_ENTRIES:
            sorted_items = sorted(
                soft_deleted.items(),
                key=lambda item: self._coerce_datetime(item[1].get("deleted_at") if isinstance(item[1], dict) else None)
                or datetime(1970, 1, 1, tzinfo=timezone.utc),
            )
            overlay["soft_deleted"] = dict(sorted_items[-self._MAX_SOFT_DELETED_ENTRIES :])

        audit = overlay.get("audit")
        if isinstance(audit, list) and len(audit) > self._MAX_AUDIT_ENTRIES:
            overlay["audit"] = audit[-self._MAX_AUDIT_ENTRIES :]

    def _append_audit(
        self,
        overlay: dict[str, Any],
        *,
        action: str,
        affected_ids: list[str],
        details: dict[str, Any] | None = None,
    ) -> str:
        audit_id = str(uuid4())
        entry = {
            "id": audit_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
            "action": action,
            "affected_ids": affected_ids,
            "details": details or {},
        }
        audit = overlay.setdefault("audit", [])
        if isinstance(audit, list):
            audit.append(entry)
            if len(audit) > self._MAX_AUDIT_ENTRIES:
                del audit[:-self._MAX_AUDIT_ENTRIES]
        else:
            overlay["audit"] = [entry]
        return audit_id

    def _list_raw_memories_from_hindsight(self, *, search_query: str | None = None, max_items: int = 1000) -> list[dict[str, Any]]:
        self._ensure_bank()
        items: list[dict[str, Any]] = []
        offset = 0
        while len(items) < max_items:
            batch_size = min(200, max_items - len(items))
            response = self._http_get_hindsight_json(
                f"/v1/default/banks/{quote(self.bank_id, safe='')}/memories/list",
                {
                    "q": search_query or None,
                    "limit": batch_size,
                    "offset": offset,
                },
            )
            batch = list((response or {}).get("items") or [])
            if not batch:
                break
            for row in batch:
                if isinstance(row, dict):
                    items.append(row)
                elif hasattr(row, "to_dict"):
                    items.append(row.to_dict())
                elif hasattr(row, "model_dump"):
                    items.append(row.model_dump())
            if len(batch) < batch_size:
                break
            offset += len(batch)
        return items

    @staticmethod
    def _is_not_found_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(token in message for token in ("404", "not found", "does not exist", "no memory found"))

    def _find_memory_via_listing(self, fact_id: str, *, search_query: str | None = None) -> dict[str, Any] | None:
        """Find one raw memory by walking list results and matching normalized ids."""
        try:
            raw_items = self._list_raw_memories_from_hindsight(search_query=search_query, max_items=5000)
        except Exception:
            return None

        for raw in raw_items:
            normalized_id = self._normalize_raw_fact(raw).id
            if normalized_id == fact_id:
                return raw
        return None

    def _list_raw_memories_fallback(self, search_query: str | None = None) -> list[dict[str, Any]]:
        response = memory_service.get_memory()
        facts: list[dict[str, Any]] = []
        q = (search_query or "").strip().lower()
        for entry in response.entries:
            context = "uncategorized"
            if "." in entry.key:
                context = entry.key.split(".", 1)[0] or context
            content = str(entry.value)
            if q and q not in content.lower() and q not in entry.key.lower():
                continue
            facts.append(
                {
                    "id": f"legacy:{entry.key}",
                    "content": content,
                    "context": context,
                    "timestamp": entry.updated_at.isoformat() if entry.updated_at else None,
                    "metadata": {"source": "legacy-memory", "key": entry.key},
                    "tags": ["legacy"],
                    "entities": [],
                    "type": "world",
                }
            )
        return facts

    def _list_raw_memories(self, *, search_query: str | None = None) -> list[dict[str, Any]]:
        self._maybe_recover_hindsight()
        if not self._hindsight_enabled:
            return self._list_raw_memories_fallback(search_query=search_query)
        try:
            return self._list_raw_memories_from_hindsight(search_query=search_query)
        except Exception:
            # Disable repeated retries when Hindsight is unavailable in this runtime.
            self._reset_client()
            self._hindsight_enabled = False
            return self._list_raw_memories_fallback(search_query=search_query)

    def _get_raw_memory(self, fact_id: str) -> dict[str, Any] | None:
        if fact_id.startswith("legacy:"):
            legacy = self._list_raw_memories_fallback()
            return next((item for item in legacy if item.get("id") == fact_id), None)
        self._maybe_recover_hindsight()
        if not self._hindsight_enabled:
            return None

        try:
            self._ensure_bank()
            payload = self._http_get_hindsight_json(
                f"/v1/default/banks/{quote(self.bank_id, safe='')}/memories/{quote(fact_id, safe='')}"
            )
            if isinstance(payload, dict):
                return payload
            if hasattr(payload, "to_dict"):
                return payload.to_dict()
            if hasattr(payload, "model_dump"):
                return payload.model_dump()
        except Exception as exc:
            fallback = self._find_memory_via_listing(fact_id)
            if fallback is not None:
                return fallback
            if not self._is_not_found_error(exc):
                self._reset_client()
                self._hindsight_enabled = False
            return None
        return None

    @staticmethod
    def _extract_entities(raw_entities: Any) -> list[str]:
        entities: list[str] = []
        if isinstance(raw_entities, str):
            return [part.strip() for part in raw_entities.split(",") if part.strip()]
        if not isinstance(raw_entities, list):
            return entities
        for entity in raw_entities:
            if isinstance(entity, str):
                entities.append(entity)
                continue
            if isinstance(entity, dict):
                for key in ("name", "value", "entity", "label"):
                    value = entity.get(key)
                    if isinstance(value, str) and value.strip():
                        entities.append(value.strip())
                        break
        return entities

    def _extract_source_peer(self, metadata: dict[str, str], tags: list[str], content: str) -> Literal["pc", "pi", "unknown"]:
        for key in ("source_peer", "source", "instance", "peer", "node"):
            raw = metadata.get(key, "").strip().lower()
            if raw in {"pc", "desktop", "main"}:
                return "pc"
            if raw in {"pi", "raspberrypi", "raspberry-pi"}:
                return "pi"
        tags_norm = {tag.strip().lower() for tag in tags}
        if tags_norm & {"pc", "desktop"}:
            return "pc"
        if tags_norm & {"pi", "raspberrypi", "raspberry-pi"}:
            return "pi"
        lowered = content.lower()
        if "raspberry pi" in lowered or "source_peer=pi" in lowered:
            return "pi"
        return "unknown"

    def _normalize_raw_fact(self, raw: dict[str, Any]) -> HindsightFact:
        metadata = self._safe_dict(raw.get("metadata"))
        tags = [str(tag) for tag in self._safe_list(raw.get("tags")) if str(tag).strip()]
        content = str(raw.get("content") or raw.get("text") or raw.get("fact") or "").strip()
        context = str(raw.get("context") or metadata.get("context") or "uncategorized").strip() or "uncategorized"
        fact_id = str(raw.get("id") or raw.get("memory_id") or raw.get("memoryId") or "").strip()
        if not fact_id:
            # Fallback keeps rows stable enough for rendering while avoiding crashes.
            fact_id = f"synthetic:{hash((context, content, str(raw.get('timestamp'))))}"

        timestamp = self._coerce_datetime(
            raw.get("timestamp") or raw.get("date") or raw.get("mentioned_at") or raw.get("created_at") or raw.get("updated_at")
        )
        created_at = self._coerce_datetime(raw.get("created_at") or raw.get("timestamp"))
        updated_at = self._coerce_datetime(raw.get("updated_at") or raw.get("mentioned_at") or raw.get("timestamp") or raw.get("date"))
        document_id = raw.get("document_id")
        fact_type = raw.get("type") or raw.get("fact_type")
        entities = self._extract_entities(raw.get("entities"))
        source_peer = self._extract_source_peer(metadata, tags, content)

        return HindsightFact(
            id=fact_id,
            content=content,
            context=context,
            timestamp=timestamp,
            source_peer=source_peer,
            entities=entities,
            metadata=metadata,
            tags=tags,
            document_id=str(document_id) if document_id else None,
            fact_type=str(fact_type) if fact_type else None,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _apply_overlay(self, fact: HindsightFact, overlay: dict[str, Any]) -> HindsightFact:
        update = overlay.get("updated", {}).get(fact.id)
        if isinstance(update, dict):
            if isinstance(update.get("content"), str) and update["content"].strip():
                fact.content = update["content"].strip()
            if isinstance(update.get("context"), str) and update["context"].strip():
                fact.context = update["context"].strip()
            patched = self._coerce_datetime(update.get("updated_at"))
            if patched:
                fact.updated_at = patched

        deleted = overlay.get("soft_deleted", {}).get(fact.id)
        if isinstance(deleted, dict):
            fact.soft_deleted = True
        return fact

    @staticmethod
    def _score_similarity(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    def _detect_stale(self, facts: list[HindsightFact]) -> dict[str, list[str]]:
        reasons: dict[str, list[str]] = defaultdict(list)
        active = [fact for fact in facts if not fact.soft_deleted]

        # 1) Duplicate detection by high content similarity in same context.
        for index, left in enumerate(active):
            left_text = left.content.lower().strip()
            if len(left_text) < 16:
                continue
            for right in active[index + 1 :]:
                if left.context.lower() != right.context.lower():
                    continue
                ratio = self._score_similarity(left_text, right.content.lower().strip())
                if ratio >= 0.9:
                    reasons[left.id].append("Potential duplicate in same context")
                    reasons[right.id].append("Potential duplicate in same context")

        # 2) Migration-era obsolescence heuristics.
        migration_terms = ("honcho", "honcho-buffered", "dim-237", "migration")
        for fact in active:
            text = fact.content.lower()
            if any(token in text for token in migration_terms):
                reasons[fact.id].append("References migration-era system details (review for obsolescence)")

        # 3) Value conflicts: key/value statements with conflicting values in same context.
        value_pattern = re.compile(r"^\s*([a-zA-Z0-9_.\- ]{2,64})\s*(?:=|:|is)\s*(.{1,300})\s*$")
        statements: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for fact in active:
            first_line = fact.content.splitlines()[0] if fact.content else ""
            match = value_pattern.match(first_line)
            if not match:
                continue
            key = match.group(1).strip().lower()
            value = match.group(2).strip().lower()
            statements[(fact.context.lower(), key)][value].append(fact.id)

        for grouped_values in statements.values():
            if len(grouped_values) <= 1:
                continue
            for ids in grouped_values.values():
                for fact_id in ids:
                    reasons[fact_id].append("Conflicting value with another fact in this context")

        # 4) Entity obsolescence: explicit references to removed systems.
        for fact in active:
            entities = [entity.lower() for entity in fact.entities]
            if any("honcho" in entity for entity in entities):
                reasons[fact.id].append("Entity references removed/legacy Honcho component")

        deduped: dict[str, list[str]] = {}
        for fact_id, entries in reasons.items():
            seen: set[str] = set()
            clean: list[str] = []
            for entry in entries:
                if entry in seen:
                    continue
                seen.add(entry)
                clean.append(entry)
            deduped[fact_id] = clean
        return deduped

    def _apply_filters(self, facts: list[HindsightFact], params: QueryParams) -> list[HindsightFact]:
        filtered = [fact for fact in facts if not fact.soft_deleted]

        if params.source in {"pc", "pi"}:
            filtered = [fact for fact in filtered if fact.source_peer == params.source]

        if params.context:
            needle = params.context.strip().lower()
            filtered = [fact for fact in filtered if fact.context.lower() == needle]

        if params.from_ts:
            filtered = [fact for fact in filtered if fact.timestamp and fact.timestamp >= params.from_ts]

        if params.to_ts:
            filtered = [fact for fact in filtered if fact.timestamp and fact.timestamp <= params.to_ts]

        if params.stale_only:
            filtered = [fact for fact in filtered if fact.stale_reasons]

        reverse = params.sort == "newest"
        filtered.sort(
            key=lambda fact: fact.timestamp or datetime(1970, 1, 1, tzinfo=timezone.utc),
            reverse=reverse,
        )
        return filtered

    def list_facts(self, params: QueryParams) -> dict[str, Any]:
        raw_items = self._list_raw_memories(search_query=params.q)
        with self._lock:
            overlay = self._load_overlay()

        normalized = [self._apply_overlay(self._normalize_raw_fact(raw), overlay) for raw in raw_items]
        stale = self._detect_stale(normalized)
        for fact in normalized:
            fact.stale_reasons = stale.get(fact.id, [])

        filtered = self._apply_filters(normalized, params)
        total = len(filtered)
        page = filtered[params.offset : params.offset + params.limit]

        return {
            "items": page,
            "total": total,
            "limit": params.limit,
            "offset": params.offset,
            "has_more": params.offset + len(page) < total,
        }

    def get_fact(self, fact_id: str, *, include_deleted: bool = False) -> HindsightFact:
        raw = self._get_raw_memory(fact_id)
        if raw is None:
            raise KeyError(f"Fact '{fact_id}' was not found")

        with self._lock:
            overlay = self._load_overlay()
        fact = self._apply_overlay(self._normalize_raw_fact(raw), overlay)
        if fact.soft_deleted and not include_deleted:
            raise KeyError(f"Fact '{fact_id}' was soft-deleted")
        return fact

    def get_audit_log(self, fact_id: str) -> list[dict[str, Any]]:
        with self._lock:
            overlay = self._load_overlay()
        audit = overlay.get("audit", [])
        if not isinstance(audit, list):
            return []
        return [entry for entry in audit if isinstance(entry, dict) and fact_id in entry.get("affected_ids", [])]

    def update_fact(self, fact_id: str, *, content: str, context: str | None) -> tuple[HindsightFact, str]:
        _ = self.get_fact(fact_id)
        with self._lock:
            overlay = self._load_overlay()
            updates = overlay.setdefault("updated", {})
            updates[fact_id] = {
                "content": content.strip(),
                "context": (context or "").strip() or None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            audit_id = self._append_audit(
                overlay,
                action="fact_update",
                affected_ids=[fact_id],
                details={"mode": "overlay"},
            )
            self._save_overlay(overlay)
        return self.get_fact(fact_id, include_deleted=True), audit_id

    def delete_fact(self, fact_id: str, *, soft_delete: bool = True) -> str:
        fact = self.get_fact(fact_id, include_deleted=True)
        with self._lock:
            overlay = self._load_overlay()
            if soft_delete:
                soft_deleted = overlay.setdefault("soft_deleted", {})
                soft_deleted[fact.id] = {
                    "deleted_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "soft",
                }
                audit_id = self._append_audit(
                    overlay,
                    action="fact_soft_delete",
                    affected_ids=[fact.id],
                    details={"mode": "soft"},
                )
                self._save_overlay(overlay)
                return audit_id

        # Hard-delete mode is intentionally limited to document-backed facts.
        if not fact.document_id:
            raise ValueError("Hard delete requires a document-backed fact (document_id is missing)")

        self._ensure_bank()
        self._resolve_client_result(
            self._get_client().documents.delete_document(bank_id=self.bank_id, document_id=fact.document_id)
        )
        with self._lock:
            overlay = self._load_overlay()
            soft_deleted = overlay.setdefault("soft_deleted", {})
            soft_deleted[fact.id] = {
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "mode": "hard",
                "document_id": fact.document_id,
            }
            audit_id = self._append_audit(
                overlay,
                action="fact_hard_delete",
                affected_ids=[fact.id],
                details={"mode": "hard", "document_id": fact.document_id},
            )
            self._save_overlay(overlay)
        return audit_id

    def bulk_delete(self, fact_ids: list[str], *, soft_delete: bool = True) -> tuple[list[str], str]:
        cleaned = [fact_id.strip() for fact_id in fact_ids if fact_id.strip()]
        if not cleaned:
            raise ValueError("No fact ids provided")

        if not soft_delete:
            raise ValueError("Bulk hard delete is disabled for safety")

        deleted: list[str] = []
        with self._lock:
            overlay = self._load_overlay()
            soft_deleted = overlay.setdefault("soft_deleted", {})
            now = datetime.now(timezone.utc).isoformat()
            for fact_id in cleaned:
                soft_deleted[fact_id] = {"deleted_at": now, "mode": "soft"}
                deleted.append(fact_id)

            audit_id = self._append_audit(
                overlay,
                action="fact_bulk_soft_delete",
                affected_ids=deleted,
                details={"mode": "soft", "count": len(deleted)},
            )
            self._save_overlay(overlay)
        return deleted, audit_id

    def stale_facts(self, *, source: Literal["all", "pc", "pi"] = "all") -> dict[str, Any]:
        data = self.list_facts(
            QueryParams(
                source=source,
                stale_only=True,
                sort="newest",
                limit=500,
                offset=0,
            )
        )
        return {
            "items": data["items"],
            "total": data["total"],
        }

    def stats(self, *, source: Literal["all", "pc", "pi"] = "all") -> dict[str, Any]:
        data = self.list_facts(
            QueryParams(
                source=source,
                stale_only=False,
                sort="newest",
                limit=1000,
                offset=0,
            )
        )
        items: list[HindsightFact] = data["items"]
        per_context: dict[str, int] = defaultdict(int)
        per_source: dict[str, int] = defaultdict(int)
        storage_estimate = 0
        last_sync: datetime | None = None
        stale_candidates = 0

        for fact in items:
            per_context[fact.context] += 1
            per_source[fact.source_peer] += 1
            storage_estimate += len(fact.content.encode("utf-8"))
            if fact.stale_reasons:
                stale_candidates += 1
            if fact.source_peer == "pi" and fact.timestamp:
                if not last_sync or fact.timestamp > last_sync:
                    last_sync = fact.timestamp

        return {
            "total_facts": len(items),
            "facts_per_context": dict(sorted(per_context.items(), key=lambda item: item[0])),
            "facts_per_source": dict(sorted(per_source.items(), key=lambda item: item[0])),
            "storage_estimate_bytes": storage_estimate,
            "last_sync_timestamp": last_sync,
            "stale_candidates": stale_candidates,
        }

    def health(self) -> dict[str, Any]:
        """Direct Hindsight API reachability and bank readiness."""
        payload = {
            "backend": "hindsight",
            "ok": False,
            "bank_id": self.bank_id,
            "base_url": self.base_url,
            "error": None,
        }
        self._maybe_recover_hindsight(force=True)
        if not self._hindsight_enabled:
            payload["error"] = "Hindsight API unavailable; bank service is using legacy memory fallback."
            return payload

        try:
            self._ensure_bank()
            self._get_client().list_memories(bank_id=self.bank_id, limit=1, offset=0)
            payload["ok"] = True
            return payload
        except Exception as exc:
            payload["error"] = str(exc)
            return payload


hindsight_bank_service = HindsightBankService()


def date_to_utc_start(value: date | None) -> datetime | None:
    """Convert a date to UTC day-start."""
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def date_to_utc_end(value: date | None) -> datetime | None:
    """Convert a date to UTC day-end."""
    if value is None:
        return None
    return datetime.combine(value, time.max, tzinfo=timezone.utc)
