"""Digest entry models and storage."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class DigestEntry(BaseModel):
    """A single digest entry from any source."""

    id: str
    title: str
    summary: str
    content: str | None = None
    source: Literal["arxiv", "web", "custom", "telegram"]
    source_url: str | None = None
    source_instance: Literal["pc", "pi"]
    tags: list[str] = Field(default_factory=list)
    ingested_at: datetime
    updated_at: datetime
    replicated_at: datetime | None = None
    replication_seq: int | None = None
    metadata: dict = Field(default_factory=dict)


class DigestDayGroup(BaseModel):
    """Digest entries grouped by day."""

    date: str  # ISO date string YYYY-MM-DD
    entries: list[DigestEntry]
    count: int


class DigestListResponse(BaseModel):
    """Paginated digest list response."""

    entries: list[DigestEntry]
    groups: list[DigestDayGroup]
    total: int
    page: int
    page_size: int
    has_more: bool


class DigestDetailResponse(BaseModel):
    """Single digest entry detail."""

    entry: DigestEntry


class DigestCreateRequest(BaseModel):
    """Request to create a new digest entry."""

    title: str
    summary: str
    content: str | None = None
    source: Literal["arxiv", "web", "custom", "telegram"]
    source_url: str | None = None
    source_instance: Literal["pc", "pi"]
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class DigestStatsResponse(BaseModel):
    """Digest statistics per source and instance."""

    total_entries: int
    by_source: dict[str, int]
    by_instance: dict[str, int]
    last_24h: int
    last_7d: int
    replication_lag_seconds: float | None = None
