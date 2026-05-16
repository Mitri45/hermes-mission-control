"""Memory ingest service for cross-node replication into memory backends."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Literal

from app.core.config import get_settings
from app.models.schemas import (
    DeadLetterEntry,
    DeadLetterResponse,
    MemoryIngestCheckpoint,
    MemoryIngestEvent,
    MemoryIngestEventResult,
    MemoryIngestMetricsResponse,
    MemoryIngestResponse,
)

logger = logging.getLogger(__name__)

_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")


class TransientIngestError(RuntimeError):
    """Raised for retryable ingest failures (network/downstream unavailable)."""


class PermanentIngestError(RuntimeError):
    """Raised for non-retryable ingest failures."""


class IngestAuthError(RuntimeError):
    """Raised when memory ingest request authentication fails."""

    def __init__(self, detail: str, status_code: int = 401):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class SessionMapping:
    """Stable mapping from external session metadata to Honcho IDs."""

    source_peer: str
    external_session_key: str
    workspace_id: str
    honcho_session_id: str
    user_peer_id: str
    assistant_peer_id: str


class MemoryEventSink(Protocol):
    """Persistence sink for ingest events."""

    def persist_event(
        self,
        mapping: SessionMapping,
        role: str,
        content: str,
        event: MemoryIngestEvent,
    ) -> None:
        """Persist a memory event."""


class HonchoMemorySink:
    """Persist replicated events into Honcho sessions."""

    def __init__(
        self,
        workspace_id: str | None = None,
        environment: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_cached_sessions: int = 512,
        max_cached_peers: int = 1024,
    ):
        self.workspace_id = workspace_id or os.environ.get("HONCHO_WORKSPACE_ID", "hermes")
        self.environment = environment or os.environ.get("HONCHO_ENVIRONMENT", "production")
        self.base_url = base_url if base_url is not None else os.environ.get("HONCHO_BASE_URL", "").strip()
        self.api_key = api_key if api_key is not None else os.environ.get("HONCHO_API_KEY")
        self.max_cached_sessions = max(1, max_cached_sessions)
        self.max_cached_peers = max(1, max_cached_peers)
        self._lock = threading.RLock()
        self._client: Any | None = None
        self._sessions: OrderedDict[str, Any] = OrderedDict()
        self._peers: OrderedDict[str, Any] = OrderedDict()
        self._configured_sessions: set[str] = set()

    @staticmethod
    def _cache_get(cache: OrderedDict[str, Any], key: str) -> Any | None:
        value = cache.get(key)
        if value is not None:
            cache.move_to_end(key)
        return value

    @staticmethod
    def _cache_set(cache: OrderedDict[str, Any], key: str, value: Any, max_items: int) -> None:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_items:
            cache.popitem(last=False)

    def _is_local_base_url(self) -> bool:
        if not self.base_url:
            return False
        return any(host in self.base_url for host in ("localhost", "127.0.0.1", "::1"))

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is not None:
                return self._client

            try:
                from honcho import Honcho
            except ImportError as exc:
                raise TransientIngestError(
                    "honcho-ai is not installed in mission-control-api runtime"
                ) from exc

            effective_api_key = self.api_key or ("local" if self._is_local_base_url() else None)
            if not effective_api_key:
                raise TransientIngestError("HONCHO_API_KEY is not configured")

            kwargs: dict[str, Any] = {
                "workspace_id": self.workspace_id,
                "api_key": effective_api_key,
                "environment": self.environment,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url

            self._client = Honcho(**kwargs)
            return self._client

    def _get_peer(self, peer_id: str) -> Any:
        peer = self._cache_get(self._peers, peer_id)
        if peer is not None:
            return peer
        client = self._get_client()
        peer = client.peer(peer_id)
        self._cache_set(self._peers, peer_id, peer, self.max_cached_peers)
        return peer

    def _get_session(self, mapping: SessionMapping) -> Any:
        session = self._cache_get(self._sessions, mapping.honcho_session_id)
        if session is not None:
            return session
        client = self._get_client()
        session = client.session(mapping.honcho_session_id)
        self._cache_set(
            self._sessions,
            mapping.honcho_session_id,
            session,
            self.max_cached_sessions,
        )
        return session

    def _ensure_session_peers(self, mapping: SessionMapping) -> None:
        if mapping.honcho_session_id in self._configured_sessions:
            return
        try:
            from honcho.session import SessionPeerConfig
        except ImportError as exc:
            raise TransientIngestError("honcho-ai SessionPeerConfig import failed") from exc

        session = self._get_session(mapping)
        user_peer = self._get_peer(mapping.user_peer_id)
        assistant_peer = self._get_peer(mapping.assistant_peer_id)
        session.add_peers(
            [
                (user_peer, SessionPeerConfig(observe_me=True, observe_others=True)),
                (assistant_peer, SessionPeerConfig(observe_me=True, observe_others=True)),
            ]
        )
        self._configured_sessions.add(mapping.honcho_session_id)

    def persist_event(
        self,
        mapping: SessionMapping,
        role: str,
        content: str,
        event: MemoryIngestEvent,
    ) -> None:
        del event  # metadata is already recorded in SQLite audit tables
        try:
            with self._lock:
                self._ensure_session_peers(mapping)
                session = self._get_session(mapping)
                peer_id = mapping.user_peer_id if role == "user" else mapping.assistant_peer_id
                peer = self._get_peer(peer_id)
                session.add_messages([peer.message(content)])
        except PermanentIngestError:
            raise
        except Exception as exc:
            raise TransientIngestError(str(exc)) from exc

    def health(self) -> dict[str, Any]:
        try:
            self._get_client()
            return {
                "backend": "honcho",
                "ok": True,
                "workspace_id": self.workspace_id,
                "base_url": self.base_url or "",
            }
        except Exception as exc:
            return {
                "backend": "honcho",
                "ok": False,
                "workspace_id": self.workspace_id,
                "base_url": self.base_url or "",
                "error": str(exc),
            }


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


class HindsightMemorySink:
    """Persist replicated events into Hindsight memory banks."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        bank_id: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = _resolve_hindsight_base_url(base_url)
        self.api_key = api_key if api_key is not None else os.environ.get("HINDSIGHT_API_KEY")
        self.bank_id = (bank_id or os.environ.get("HINDSIGHT_BANK") or os.environ.get("HINDSIGHT_BANK_ID") or "hermes").strip() or "hermes"
        self.timeout = timeout
        self.workspace_id = self.bank_id
        self._lock = threading.RLock()
        self._client: Any | None = None
        self._bank_initialized = False

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                from hindsight_client import Hindsight
            except ImportError as exc:
                raise TransientIngestError(
                    "hindsight-client is not installed in mission-control-api runtime"
                ) from exc

            try:
                self._client = Hindsight(
                    base_url=self.base_url,
                    api_key=self.api_key or None,
                    timeout=self.timeout,
                )
            except TypeError:
                self._client = Hindsight(self.base_url, self.api_key or None, self.timeout)
            return self._client

    def _ensure_bank(self) -> None:
        if self._bank_initialized:
            return
        client = self._get_client()
        try:
            client.create_bank(bank_id=self.bank_id, name=self.bank_id)
            self._bank_initialized = True
            return
        except Exception as exc:
            # Existing bank is fine; other failures should be surfaced/retried.
            message = str(exc).lower()
            if any(token in message for token in ("already exists", "already-exists", "conflict", "409")):
                self._bank_initialized = True
                return
            raise TransientIngestError(
                f"failed to verify/create hindsight bank '{self.bank_id}': {exc}"
            ) from exc

    @staticmethod
    def _event_content(event: MemoryIngestEvent, content: str) -> str:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if isinstance(payload, dict):
            raw = payload.get("content")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
            user = payload.get("user")
            assistant = payload.get("assistant")
            if isinstance(user, str) or isinstance(assistant, str):
                return f"User: {str(user or '')}\nAssistant: {str(assistant or '')}".strip()
        return content

    @staticmethod
    def _event_context(event: MemoryIngestEvent) -> str:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if isinstance(payload, dict):
            raw = payload.get("context")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()[:200]
        return event.type[:200]

    def persist_event(
        self,
        mapping: SessionMapping,
        role: str,
        content: str,
        event: MemoryIngestEvent,
    ) -> None:
        del mapping, role
        try:
            with self._lock:
                self._ensure_bank()
                final_content = self._event_content(event, content)
                context = self._event_context(event)
                self._get_client().retain(
                    bank_id=self.bank_id,
                    content=final_content,
                    context=context,
                )
        except PermanentIngestError:
            raise
        except Exception as exc:
            raise TransientIngestError(str(exc)) from exc

    def health(self) -> dict[str, Any]:
        try:
            with self._lock:
                self._ensure_bank()
            return {
                "backend": "hindsight",
                "ok": True,
                "bank_id": self.bank_id,
                "base_url": self.base_url,
            }
        except Exception as exc:
            return {
                "backend": "hindsight",
                "ok": False,
                "bank_id": self.bank_id,
                "base_url": self.base_url,
                "error": str(exc),
            }


class MemoryIngestService:
    """Idempotent ingestion pipeline with monotonic ACK checkpoints."""

    def __init__(
        self,
        db_path: Path | None = None,
        sink: MemoryEventSink | None = None,
    ):
        self.settings = get_settings()
        self.db_path = db_path or self.settings.memory_ingest_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._sink_backend: Literal["honcho", "hindsight"] = "honcho"
        self._sink = sink or self._build_default_sink()
        self._default_workspace = getattr(self._sink, "workspace_id", "hermes")
        self._allowed_sources = set(self.settings.memory_ingest_allowed_sources)
        self._clock_skew_s = max(1, self.settings.memory_ingest_max_clock_skew_seconds)
        self._nonce_ttl_s = max(self._clock_skew_s, self.settings.memory_ingest_nonce_ttl_seconds)
        self._hmac_secrets = [
            secret
            for secret in (
                self.settings.memory_ingest_hmac_secret,
                self.settings.memory_ingest_hmac_next_secret,
            )
            if secret
        ]
        self._init_db()

    def _build_default_sink(self) -> MemoryEventSink:
        backend = str(getattr(self.settings, "memory_ingest_backend", "honcho") or "honcho").strip().lower()
        if backend == "hindsight":
            self._sink_backend = "hindsight"
            return HindsightMemorySink(
                base_url=getattr(self.settings, "memory_ingest_hindsight_base_url", None),
                api_key=getattr(self.settings, "memory_ingest_hindsight_api_key", None),
                bank_id=getattr(self.settings, "memory_ingest_hindsight_bank", None),
            )
        self._sink_backend = "honcho"
        return HonchoMemorySink()

    @property
    def sink_backend(self) -> str:
        return self._sink_backend

    def health(self) -> dict[str, Any]:
        raw_health = {}
        try:
            if hasattr(self._sink, "health"):
                raw_health = self._sink.health()  # type: ignore[assignment]
        except Exception as exc:
            raw_health = {"ok": False, "error": str(exc)}

        if not isinstance(raw_health, dict):
            raw_health = {}
        raw_health.setdefault("backend", self._sink_backend)
        raw_health.setdefault("ok", True)
        raw_health["db_path"] = str(self.db_path)
        return raw_health

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _sanitize_component(raw: str, fallback: str) -> str:
        cleaned = _ID_PATTERN.sub("-", raw).strip("-")
        return cleaned or fallback

    def _stable_id(self, prefix: str, *parts: str, max_len: int = 120) -> str:
        joined = "-".join(self._sanitize_component(str(p), "x") for p in parts if p)
        base = self._sanitize_component(f"{prefix}-{joined}", prefix)
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
        trimmed = base[: max_len - 9] if len(base) > (max_len - 9) else base
        return f"{trimmed}-{digest}"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingest_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_peer TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    ts TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    applied_at TEXT,
                    UNIQUE(source_peer, event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_ingest_events_source_seq
                    ON ingest_events(source_peer, seq);
                CREATE INDEX IF NOT EXISTS idx_ingest_events_source_status
                    ON ingest_events(source_peer, status);

                CREATE TABLE IF NOT EXISTS ingest_checkpoints (
                    source_peer TEXT PRIMARY KEY,
                    highest_contiguous_seq INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ingest_dead_letters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_peer TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    details TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ingest_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_peer TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ingest_session_mappings (
                    source_peer TEXT NOT NULL,
                    external_session_key TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    honcho_session_id TEXT NOT NULL,
                    user_peer_id TEXT NOT NULL,
                    assistant_peer_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(source_peer, external_session_key)
                );

                CREATE TABLE IF NOT EXISTS ingest_nonces (
                    nonce TEXT PRIMARY KEY,
                    source_ip TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _normalize_signature(signature: str | None) -> str:
        if not signature:
            return ""
        value = signature.strip()
        if value.lower().startswith("sha256="):
            value = value.split("=", 1)[1].strip()
        return value

    @staticmethod
    def _signed_message(raw_body: bytes, timestamp: str, nonce: str) -> bytes:
        return f"{timestamp}.{nonce}.".encode("utf-8") + raw_body

    def _is_valid_signature(
        self,
        *,
        raw_body: bytes,
        timestamp: str,
        nonce: str,
        signature: str,
    ) -> bool:
        if not self._hmac_secrets:
            raise IngestAuthError(
                "memory ingest HMAC is not configured on server",
                status_code=503,
            )
        msg = self._signed_message(raw_body, timestamp, nonce)
        provided = self._normalize_signature(signature)
        if not provided:
            return False
        for secret in self._hmac_secrets:
            expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
            if hmac.compare_digest(provided, expected):
                return True
        return False

    def authenticate_request(
        self,
        *,
        source_ip: str | None,
        raw_body: bytes,
        timestamp: str | None,
        nonce: str | None,
        signature: str | None,
    ) -> None:
        """Authenticate + anti-replay checks for memory ingest requests."""
        if not source_ip:
            raise IngestAuthError("unable to determine client IP", status_code=403)
        if source_ip not in self._allowed_sources:
            raise IngestAuthError("source IP is not allowed", status_code=403)
        if not timestamp:
            raise IngestAuthError("missing X-Hermes-Timestamp header")
        if not nonce:
            raise IngestAuthError("missing X-Hermes-Nonce header")
        if not signature:
            raise IngestAuthError("missing X-Hermes-Signature header")

        try:
            ts = int(timestamp)
        except ValueError as exc:
            raise IngestAuthError("invalid X-Hermes-Timestamp header") from exc

        now_s = int(self._now().timestamp())
        if abs(now_s - ts) > self._clock_skew_s:
            raise IngestAuthError("request timestamp outside allowed skew window")

        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", nonce):
            raise IngestAuthError("invalid X-Hermes-Nonce header")

        if not self._is_valid_signature(
            raw_body=raw_body,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
        ):
            raise IngestAuthError("invalid request signature")

        cutoff_iso = datetime.fromtimestamp(now_s - self._nonce_ttl_s, tz=timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM ingest_nonces WHERE created_at < ?",
                    (cutoff_iso,),
                )
                try:
                    conn.execute(
                        """
                        INSERT INTO ingest_nonces (nonce, source_ip, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (nonce, source_ip, self._now().isoformat()),
                    )
                except sqlite3.IntegrityError as exc:
                    raise IngestAuthError("replayed nonce", status_code=409) from exc

    @staticmethod
    def _canonical_payload_json(payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _payload_hash(self, payload: Any) -> str:
        return hashlib.sha256(self._canonical_payload_json(payload).encode("utf-8")).hexdigest()

    def _derive_external_session_key(self, event: MemoryIngestEvent) -> str:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if isinstance(payload, dict):
            for key in ("session_key", "session_id", "conversation_id", "thread_id"):
                value = payload.get(key)
                if value:
                    return self._sanitize_component(str(value), f"{event.source_peer}-default")
            platform = payload.get("platform")
            chat_id = payload.get("chat_id")
            if platform and chat_id:
                return self._sanitize_component(f"{platform}-{chat_id}", f"{event.source_peer}-default")

            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                for key in ("session_key", "session_id", "conversation_id", "thread_id"):
                    value = metadata.get(key)
                    if value:
                        return self._sanitize_component(str(value), f"{event.source_peer}-default")

        return f"{event.source_peer}-default"

    def _derive_workspace_id(self, event: MemoryIngestEvent) -> str:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if isinstance(payload, dict):
            workspace = payload.get("workspace_id") or payload.get("workspace")
            if workspace:
                return self._sanitize_component(str(workspace), self._default_workspace)
            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                workspace = metadata.get("workspace_id") or metadata.get("workspace")
                if workspace:
                    return self._sanitize_component(str(workspace), self._default_workspace)
        return self._default_workspace

    def _resolve_session_mapping(
        self, conn: sqlite3.Connection, event: MemoryIngestEvent
    ) -> SessionMapping:
        external_session_key = self._derive_external_session_key(event)
        row = conn.execute(
            """
            SELECT source_peer, external_session_key, workspace_id,
                   honcho_session_id, user_peer_id, assistant_peer_id
            FROM ingest_session_mappings
            WHERE source_peer = ? AND external_session_key = ?
            """,
            (event.source_peer, external_session_key),
        ).fetchone()
        if row:
            return SessionMapping(
                source_peer=row["source_peer"],
                external_session_key=row["external_session_key"],
                workspace_id=row["workspace_id"],
                honcho_session_id=row["honcho_session_id"],
                user_peer_id=row["user_peer_id"],
                assistant_peer_id=row["assistant_peer_id"],
            )

        workspace_id = self._derive_workspace_id(event)
        honcho_session_id = self._stable_id("sync", workspace_id, event.source_peer, external_session_key)
        user_peer_id = self._stable_id("user", event.source_peer, external_session_key)
        assistant_peer_id = self._stable_id("assistant", event.source_peer, external_session_key)
        now_iso = self._now().isoformat()
        conn.execute(
            """
            INSERT INTO ingest_session_mappings (
                source_peer,
                external_session_key,
                workspace_id,
                honcho_session_id,
                user_peer_id,
                assistant_peer_id,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.source_peer,
                external_session_key,
                workspace_id,
                honcho_session_id,
                user_peer_id,
                assistant_peer_id,
                now_iso,
                now_iso,
            ),
        )
        return SessionMapping(
            source_peer=event.source_peer,
            external_session_key=external_session_key,
            workspace_id=workspace_id,
            honcho_session_id=honcho_session_id,
            user_peer_id=user_peer_id,
            assistant_peer_id=assistant_peer_id,
        )

    def _build_honcho_message(self, event: MemoryIngestEvent) -> tuple[str, str]:
        payload = event.payload if isinstance(event.payload, dict) else {}

        role = ""
        content = ""
        if isinstance(payload, dict):
            role = str(payload.get("role", "")).strip().lower()
            raw_content = payload.get("content")
            if isinstance(raw_content, str):
                content = raw_content.strip()

        if role not in {"user", "assistant"}:
            role = "user" if event.type.startswith("user") else "assistant"

        if content:
            return role, content

        fallback = {
            "event_id": event.event_id,
            "source_peer": event.source_peer,
            "seq": event.seq,
            "ts": event.ts.isoformat(),
            "type": event.type,
            "payload": event.payload,
        }
        return role, self._canonical_payload_json(fallback)

    def _insert_dead_letter(
        self,
        conn: sqlite3.Connection,
        event: MemoryIngestEvent,
        reason: str,
        details: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO ingest_dead_letters (
                source_peer,
                event_id,
                seq,
                reason,
                details,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.source_peer,
                event.event_id,
                event.seq,
                reason,
                details,
                self._canonical_payload_json(event.payload),
                self._now().isoformat(),
            ),
        )

    def _insert_ingest_event(
        self,
        conn: sqlite3.Connection,
        event: MemoryIngestEvent,
        session_key: str,
        workspace_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO ingest_events (
                source_peer,
                event_id,
                seq,
                ts,
                event_type,
                payload_json,
                payload_hash,
                session_key,
                workspace_id,
                status,
                error,
                created_at,
                applied_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.source_peer,
                event.event_id,
                event.seq,
                event.ts.isoformat(),
                event.type,
                self._canonical_payload_json(event.payload),
                event.payload_hash,
                session_key,
                workspace_id,
                status,
                error,
                self._now().isoformat(),
                self._now().isoformat() if status == "applied" else None,
            ),
        )

    def _record_attempt(
        self,
        conn: sqlite3.Connection,
        event: MemoryIngestEvent,
        status: str,
        reason: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO ingest_attempts (
                source_peer,
                event_id,
                seq,
                status,
                reason,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.source_peer,
                event.event_id,
                event.seq,
                status,
                reason,
                self._now().isoformat(),
            ),
        )

    def _log_structured(self, action: str, **fields: Any) -> None:
        payload = {"component": "memory_ingest", "action": action, **fields}
        logger.info(json.dumps(payload, default=str, sort_keys=True))

    def _ingest_event(
        self, conn: sqlite3.Connection, event: MemoryIngestEvent
    ) -> MemoryIngestEventResult:
        existing_by_id = conn.execute(
            """
            SELECT payload_hash
            FROM ingest_events
            WHERE source_peer = ? AND event_id = ?
            """,
            (event.source_peer, event.event_id),
        ).fetchone()
        if existing_by_id:
            if existing_by_id["payload_hash"] != event.payload_hash:
                return MemoryIngestEventResult(
                    event_id=event.event_id,
                    source_peer=event.source_peer,
                    seq=event.seq,
                    status="duplicate",
                    reason="payload_hash_mismatch_on_duplicate",
                )
            return MemoryIngestEventResult(
                event_id=event.event_id,
                source_peer=event.source_peer,
                seq=event.seq,
                status="duplicate",
                reason="already_processed",
            )

        expected_hash = self._payload_hash(event.payload)
        if expected_hash != event.payload_hash:
            reason = "payload_hash_mismatch"
            details = f"expected={expected_hash} got={event.payload_hash}"
            mapping = self._resolve_session_mapping(conn, event)
            self._insert_ingest_event(
                conn,
                event,
                session_key=mapping.external_session_key,
                workspace_id=mapping.workspace_id,
                status="dead_letter",
                error=details,
            )
            self._insert_dead_letter(conn, event, reason=reason, details=details)
            return MemoryIngestEventResult(
                event_id=event.event_id,
                source_peer=event.source_peer,
                seq=event.seq,
                status="dead_letter",
                reason=reason,
            )

        conflicting_seq = conn.execute(
            """
            SELECT event_id
            FROM ingest_events
            WHERE source_peer = ? AND seq = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (event.source_peer, event.seq),
        ).fetchone()

        mapping = self._resolve_session_mapping(conn, event)
        if conflicting_seq and conflicting_seq["event_id"] != event.event_id:
            reason = "seq_conflict"
            details = f"seq already assigned to event_id={conflicting_seq['event_id']}"
            self._insert_ingest_event(
                conn,
                event,
                session_key=mapping.external_session_key,
                workspace_id=mapping.workspace_id,
                status="dead_letter",
                error=details,
            )
            self._insert_dead_letter(conn, event, reason=reason, details=details)
            return MemoryIngestEventResult(
                event_id=event.event_id,
                source_peer=event.source_peer,
                seq=event.seq,
                status="dead_letter",
                reason=reason,
            )

        role, content = self._build_honcho_message(event)
        try:
            self._sink.persist_event(mapping, role=role, content=content, event=event)
        except PermanentIngestError as exc:
            reason = "permanent_sink_failure"
            details = str(exc)
            self._insert_ingest_event(
                conn,
                event,
                session_key=mapping.external_session_key,
                workspace_id=mapping.workspace_id,
                status="dead_letter",
                error=details,
            )
            self._insert_dead_letter(conn, event, reason=reason, details=details)
            return MemoryIngestEventResult(
                event_id=event.event_id,
                source_peer=event.source_peer,
                seq=event.seq,
                status="dead_letter",
                reason=reason,
            )
        except TransientIngestError:
            raise
        except Exception as exc:
            raise TransientIngestError(str(exc)) from exc

        self._insert_ingest_event(
            conn,
            event,
            session_key=mapping.external_session_key,
            workspace_id=mapping.workspace_id,
            status="applied",
        )
        return MemoryIngestEventResult(
            event_id=event.event_id,
            source_peer=event.source_peer,
            seq=event.seq,
            status="applied",
        )

    def _get_checkpoint(self, conn: sqlite3.Connection, source_peer: str) -> MemoryIngestCheckpoint:
        row = conn.execute(
            """
            SELECT source_peer, highest_contiguous_seq, updated_at
            FROM ingest_checkpoints
            WHERE source_peer = ?
            """,
            (source_peer,),
        ).fetchone()
        if not row:
            return MemoryIngestCheckpoint(source_peer=source_peer, highest_contiguous_seq=0, updated_at=None)
        updated_at = datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
        return MemoryIngestCheckpoint(
            source_peer=row["source_peer"],
            highest_contiguous_seq=row["highest_contiguous_seq"],
            updated_at=updated_at,
        )

    def _advance_checkpoint(self, conn: sqlite3.Connection, source_peer: str) -> MemoryIngestCheckpoint:
        checkpoint = self._get_checkpoint(conn, source_peer)
        current = checkpoint.highest_contiguous_seq
        next_seq = current + 1
        while True:
            row = conn.execute(
                """
                SELECT 1
                FROM ingest_events
                WHERE source_peer = ? AND seq = ? AND status IN ('applied', 'dead_letter')
                LIMIT 1
                """,
                (source_peer, next_seq),
            ).fetchone()
            if row is None:
                break
            current = next_seq
            next_seq = current + 1

        now_iso = self._now().isoformat()
        if checkpoint.updated_at is None:
            conn.execute(
                """
                INSERT OR IGNORE INTO ingest_checkpoints (
                    source_peer, highest_contiguous_seq, updated_at
                ) VALUES (?, ?, ?)
                """,
                (source_peer, current, now_iso),
            )
        elif current != checkpoint.highest_contiguous_seq:
            conn.execute(
                """
                UPDATE ingest_checkpoints
                SET highest_contiguous_seq = ?, updated_at = ?
                WHERE source_peer = ?
                """,
                (current, now_iso, source_peer),
            )
        else:
            conn.execute(
                """
                UPDATE ingest_checkpoints
                SET updated_at = ?
                WHERE source_peer = ?
                """,
                (now_iso, source_peer),
            )

        return self._get_checkpoint(conn, source_peer)

    def ingest(self, events: list[MemoryIngestEvent]) -> MemoryIngestResponse:
        """Ingest a batch of memory events and return source checkpoints."""
        accepted = 0
        duplicates = 0
        dead_lettered = 0
        transient_failures = 0
        results: list[MemoryIngestEventResult] = []
        touched_sources: set[str] = set()

        ordered = sorted(events, key=lambda e: (e.source_peer, e.seq, e.event_id))
        with self._lock:
            with self._connect() as conn:
                for event in ordered:
                    touched_sources.add(event.source_peer)
                    try:
                        result = self._ingest_event(conn, event)
                    except TransientIngestError as exc:
                        result = MemoryIngestEventResult(
                            event_id=event.event_id,
                            source_peer=event.source_peer,
                            seq=event.seq,
                            status="transient_error",
                            reason=str(exc),
                        )

                    self._record_attempt(conn, event, status=result.status, reason=result.reason)
                    results.append(result)

                    if result.status == "applied":
                        accepted += 1
                    elif result.status == "duplicate":
                        duplicates += 1
                    elif result.status == "dead_letter":
                        dead_lettered += 1
                    elif result.status == "transient_error":
                        transient_failures += 1

                    self._log_structured(
                        "event_processed",
                        source_peer=event.source_peer,
                        event_id=event.event_id,
                        seq=event.seq,
                        status=result.status,
                        reason=result.reason,
                    )

                checkpoints = [
                    self._advance_checkpoint(conn, source_peer)
                    for source_peer in sorted(touched_sources)
                ]
                conn.commit()

        for checkpoint in checkpoints:
            self._log_structured(
                "checkpoint_updated",
                source_peer=checkpoint.source_peer,
                highest_contiguous_seq=checkpoint.highest_contiguous_seq,
            )

        return MemoryIngestResponse(
            accepted=accepted,
            duplicates=duplicates,
            dead_lettered=dead_lettered,
            transient_failures=transient_failures,
            checkpoints=checkpoints,
            results=results,
        )

    def get_metrics(self) -> MemoryIngestMetricsResponse:
        """Return ingest metrics for monitoring and troubleshooting."""
        with self._lock:
            with self._connect() as conn:
                checkpoints_rows = conn.execute(
                    """
                    SELECT source_peer, highest_contiguous_seq, updated_at
                    FROM ingest_checkpoints
                    ORDER BY source_peer
                    """
                ).fetchall()
                checkpoints = [
                    MemoryIngestCheckpoint(
                        source_peer=row["source_peer"],
                        highest_contiguous_seq=row["highest_contiguous_seq"],
                        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
                    )
                    for row in checkpoints_rows
                ]

                totals_rows = conn.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM ingest_attempts
                    GROUP BY status
                    """
                ).fetchall()
                totals = {row["status"]: int(row["count"]) for row in totals_rows}

                lag_rows = conn.execute(
                    """
                    SELECT e.source_peer, MAX(e.seq) AS max_seq
                    FROM ingest_events e
                    GROUP BY e.source_peer
                    """
                ).fetchall()
                max_by_source = {row["source_peer"]: int(row["max_seq"] or 0) for row in lag_rows}
                lag_by_source = {}
                for checkpoint in checkpoints:
                    max_seen = max_by_source.get(checkpoint.source_peer, checkpoint.highest_contiguous_seq)
                    lag_by_source[checkpoint.source_peer] = max(0, max_seen - checkpoint.highest_contiguous_seq)

                dead_letter_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM ingest_dead_letters"
                ).fetchone()
                dead_letters = int(dead_letter_count["count"]) if dead_letter_count else 0

                last_dead = conn.execute(
                    """
                    SELECT created_at
                    FROM ingest_dead_letters
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
                last_dead_letter_at = (
                    datetime.fromisoformat(last_dead["created_at"]) if last_dead and last_dead["created_at"] else None
                )

        return MemoryIngestMetricsResponse(
            checkpoints=checkpoints,
            totals=totals,
            lag_by_source=lag_by_source,
            dead_letters=dead_letters,
            last_dead_letter_at=last_dead_letter_at,
        )

    def get_dead_letters(self, limit: int = 50) -> DeadLetterResponse:
        """Return dead-letter events for debugging malformed/permanent failures."""
        safe_limit = max(1, min(limit, 500))
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, source_peer, event_id, seq, reason, details, payload_json, created_at
                    FROM ingest_dead_letters
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()

        entries: list[DeadLetterEntry] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                payload = row["payload_json"]
            entries.append(
                DeadLetterEntry(
                    id=row["id"],
                    source_peer=row["source_peer"],
                    event_id=row["event_id"],
                    seq=row["seq"],
                    reason=row["reason"],
                    details=row["details"],
                    payload=payload,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return DeadLetterResponse(entries=entries)


_memory_ingest_service: MemoryIngestService | None = None
_service_lock = threading.Lock()


def get_memory_ingest_service() -> MemoryIngestService:
    """Lazily create the process-global ingest service.

    Import-time initialization can race under pytest-xdist collection,
    producing SQLite lock errors. Deferring construction avoids that.
    """
    global _memory_ingest_service
    if _memory_ingest_service is None:
        with _service_lock:
            if _memory_ingest_service is None:
                _memory_ingest_service = MemoryIngestService()
    return _memory_ingest_service
