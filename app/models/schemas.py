"""Pydantic models for request/response validation."""

from datetime import datetime, timezone
from typing import Any, Literal

from croniter import croniter
from pydantic import BaseModel, Field
from pydantic import field_validator


# ==================== System Health ====================

class ServiceInfo(BaseModel):
    """Service information."""

    name: str
    status: str
    port: int | None = None
    pid: int | None = None


class TailscaleInfo(BaseModel):
    """Tailscale connection info."""

    funnel: bool = False
    hostname: str = ""
    ip: str | None = None


class SystemStatus(BaseModel):
    """System health status response."""

    requested_instance: Literal["all", "pc", "pi"] = "all"
    resolved_instance: Literal["pc", "pi"] = "pc"
    source_label: str = ""
    cpu_temp: float | None = None
    cpu_usage: float
    memory_used: int
    memory_total: int
    disk_used: int
    disk_total: int
    services: list[ServiceInfo]
    tailscale: TailscaleInfo
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ==================== Linear Harness ====================

class WebhookStatus(BaseModel):
    """Webhook health status."""

    url: str
    status: str
    last_event_at: datetime | None = None
    events_24h: int = 0
    errors_24h: int = 0


class HarnessConfig(BaseModel):
    """Harness configuration."""

    default_backend: str
    worktree_root: str


class HarnessStatus(BaseModel):
    """Linear harness status response."""

    webhook: WebhookStatus
    config: HarnessConfig


# ==================== Agent Sessions ====================

class AgentSession(BaseModel):
    """Active agent session."""

    id: str
    issue_id: str
    issue_title: str
    backend: str
    status: str
    started_at: datetime
    worktree: str
    platform: str | None = None
    base_url: str | None = None
    message_count: int | None = None
    last_updated_at: datetime | None = None
    source: str = "live"
    summary: str | None = None
    prompt: str | None = None


class SessionsResponse(BaseModel):
    """Active sessions response."""

    sessions: list[AgentSession]


# ==================== Workers ====================

class WorkerInfo(BaseModel):
    """Worker process information."""

    session_id: str
    pid: int
    backend: str
    issue_id: str
    runtime_seconds: int
    log_file: str


class WorkersResponse(BaseModel):
    """Workers response."""

    workers: list[WorkerInfo]


# ==================== Token Consumption ====================

class TokenUsage(BaseModel):
    """Token usage stats."""

    input: int
    output: int
    cost_usd: float


class TokensResponse(BaseModel):
    """Token consumption response."""

    current_session: TokenUsage
    today: TokenUsage
    this_month: TokenUsage
    by_model: dict[str, dict[str, float]] = Field(default_factory=dict)


# ==================== Operations Stream ====================

class OperationEvent(BaseModel):
    """Operation event for WebSocket stream."""

    type: str  # tool_call, thought, file_op, completion, error
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool: str | None = None
    args: str | None = None
    content: str | None = None
    action: str | None = None
    path: str | None = None
    status: str | None = None
    session_id: str | None = None


# ==================== Configuration ====================

class AgentConfig(BaseModel):
    """Agent configuration."""

    model: str
    provider: str
    base_url: str
    personality: str
    max_turns: int
    linear_backend: str


class AgentConfigUpdate(BaseModel):
    """Agent configuration update."""

    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    personality: str | None = None
    max_turns: int | None = None
    linear_backend: str | None = None


# ==================== Provider Visibility ====================

ProviderPanelStatus = Literal["active", "off-limits", "exhausted", "misconfigured", "unknown"]


class ProviderFlowUsage(BaseModel):
    """One flow currently configured to use a provider."""

    flow: str
    instance: Literal["pc", "pi"]
    model: str | None = None


class ProviderStatusItem(BaseModel):
    """Provider visibility row for Mission Control."""

    provider: str
    name: str
    base_url: str | None = None
    current_model: str | None = None
    status: ProviderPanelStatus
    status_reason: str | None = None
    recovery_eta_seconds: int | None = None
    recovery_eta: datetime | None = None
    primary_flows: list[ProviderFlowUsage] = Field(default_factory=list)
    last_error: str | None = None
    key_source: str | None = None


class ProviderStatusSummary(BaseModel):
    """Aggregate counts for provider statuses."""

    total: int = 0
    active: int = 0
    off_limits: int = 0
    exhausted: int = 0
    misconfigured: int = 0
    unknown: int = 0


class ProviderStatusResponse(BaseModel):
    """Provider visibility response payload."""

    instance: Literal["all", "pc", "pi"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    providers: list[ProviderStatusItem] = Field(default_factory=list)
    summary: ProviderStatusSummary = Field(default_factory=ProviderStatusSummary)


# ==================== Memory ====================

class MemoryEntry(BaseModel):
    """Memory entry."""

    key: str
    value: str
    updated_at: datetime


class PersonalityInfo(BaseModel):
    """Personality configuration."""

    current: str
    available: list[str]


class MemoryResponse(BaseModel):
    """Memory response."""

    entries: list[MemoryEntry]
    personality: PersonalityInfo


# ==================== Hindsight Bank ====================

class HindsightFact(BaseModel):
    """Normalized memory fact exposed by Mission Control APIs."""

    id: str
    content: str
    context: str = "uncategorized"
    timestamp: datetime | None = None
    source_peer: Literal["pc", "pi", "unknown"] = "unknown"
    entities: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    document_id: str | None = None
    fact_type: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    stale_reasons: list[str] = Field(default_factory=list)
    soft_deleted: bool = False


class HindsightFactsResponse(BaseModel):
    """Paginated fact list."""

    items: list[HindsightFact] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    has_more: bool = False


class HindsightFactDetailResponse(BaseModel):
    """Single fact payload."""

    fact: HindsightFact
    audit_log: list[dict[str, Any]] = Field(default_factory=list)


class HindsightFactUpdateRequest(BaseModel):
    """Editable fields for fact management UI."""

    content: str = Field(min_length=1, max_length=20000)
    context: str | None = Field(default=None, max_length=200)


class HindsightBulkDeleteRequest(BaseModel):
    """Bulk delete payload."""

    fact_ids: list[str] = Field(min_length=1)
    soft_delete: bool = True


class HindsightMutationResponse(BaseModel):
    """Mutation result payload."""

    success: bool = True
    message: str
    affected_ids: list[str] = Field(default_factory=list)
    audit_id: str | None = None


class HindsightBankStatsResponse(BaseModel):
    """Bank-level statistics for dashboard widgets."""

    total_facts: int = 0
    facts_per_context: dict[str, int] = Field(default_factory=dict)
    facts_per_source: dict[str, int] = Field(default_factory=dict)
    storage_estimate_bytes: int = 0
    last_sync_timestamp: datetime | None = None
    stale_candidates: int = 0


class HindsightHealthResponse(BaseModel):
    """Direct Hindsight API reachability and bank readiness."""

    backend: str = "hindsight"
    ok: bool = False
    bank_id: str = "hermes"
    base_url: str | None = None
    error: str | None = None


class HindsightStaleFactsResponse(BaseModel):
    """List of stale candidate facts."""

    items: list[HindsightFact] = Field(default_factory=list)
    total: int = 0


# ==================== Memory Ingest ====================

class MemoryIngestEvent(BaseModel):
    """Incoming replicated memory event."""

    event_id: str
    source_peer: str
    seq: int = Field(ge=1)
    ts: datetime
    type: str
    payload: Any
    payload_hash: str


class MemoryIngestEventResult(BaseModel):
    """Outcome for one ingest event."""

    event_id: str
    source_peer: str
    seq: int
    status: Literal["applied", "duplicate", "dead_letter", "transient_error"]
    reason: str | None = None


class MemoryIngestCheckpoint(BaseModel):
    """Monotonic checkpoint per source peer."""

    source_peer: str
    highest_contiguous_seq: int = 0
    updated_at: datetime | None = None


class MemoryIngestResponse(BaseModel):
    """Batch ingest response with counters, checkpoints, and per-event outcomes."""

    accepted: int = 0
    duplicates: int = 0
    dead_lettered: int = 0
    transient_failures: int = 0
    checkpoints: list[MemoryIngestCheckpoint] = Field(default_factory=list)
    results: list[MemoryIngestEventResult] = Field(default_factory=list)


class MemoryIngestMetricsResponse(BaseModel):
    """Operational metrics for ingest pipeline health."""

    checkpoints: list[MemoryIngestCheckpoint] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)
    lag_by_source: dict[str, int] = Field(default_factory=dict)
    dead_letters: int = 0
    last_dead_letter_at: datetime | None = None


class DeadLetterEntry(BaseModel):
    """Dead-lettered event metadata for troubleshooting."""

    id: int
    source_peer: str
    event_id: str
    seq: int
    reason: str
    details: str | None = None
    payload: Any
    created_at: datetime


class DeadLetterResponse(BaseModel):
    """Dead letter list response."""

    entries: list[DeadLetterEntry] = Field(default_factory=list)


# ==================== Cron Jobs ====================

class CronJob(BaseModel):
    """Cron job information."""

    id: str
    name: str
    schedule: str
    next_run: datetime | None = None
    last_run: datetime | None = None
    status: Literal["active", "paused", "running", "error", "scheduled"]
    enabled: bool = True
    target: str
    instance: Literal["pc", "pi", "both"] = "pc"
    last_result: Literal["success", "failed", "triggered"] | None = None
    runtime_seconds: int | None = None
    failure_reason: str | None = None
    failure_count: int = 0


class CronJobsResponse(BaseModel):
    """Cron jobs response."""

    jobs: list[CronJob]


class CronJobUpdate(BaseModel):
    """Cron job update request."""

    name: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    target: str | None = None
    instance: Literal["pc", "pi", "both"] | None = None

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, value: str | None) -> str | None:
        """Reject invalid cron expressions at request-validation time."""
        if value is None:
            return None
        schedule = value.strip()
        if not schedule:
            raise ValueError("schedule cannot be empty")
        try:
            croniter(schedule, datetime.utcnow())
        except Exception as exc:
            raise ValueError(f"invalid cron schedule: {schedule}") from exc
        return schedule


# ==================== Harness Control ====================

class HarnessControlResponse(BaseModel):
    """Harness control response."""

    success: bool
    message: str
    session_id: str


class SessionLogsResponse(BaseModel):
    """Session logs response."""

    session_id: str
    logs: list[str]


# ==================== Chat ====================

class ChatRequest(BaseModel):
    """Chat request."""

    message: str
    stream: bool = True
    session_id: str | None = None


class ChatResponse(BaseModel):
    """Chat response."""

    response: str
    type: str = "text"
    session_id: str
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    message_count: int = 0


class ChatMessage(BaseModel):
    """One persisted Mission Control chat message."""

    role: str
    content: str | None = None
    timestamp: datetime | None = None
    tool_name: str | None = None


class ChatSessionResponse(BaseModel):
    """Mission Control chat session transcript."""

    session_id: str
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    message_count: int = 0
    messages: list[ChatMessage] = Field(default_factory=list)


# ==================== Generic ====================

class ApiResponse(BaseModel):
    """Generic API response."""

    success: bool
    message: str | None = None
    data: dict[str, Any] | None = None
