from __future__ import annotations

from datetime import datetime, timezone
import json

from app.models.digest import DigestEntry
from app.services.digest_service import DigestService


def _entry(entry_id: str, title: str, summary: str, *, ingested_at: str) -> DigestEntry:
    return DigestEntry(
        id=entry_id,
        title=title,
        summary=summary,
        content=None,
        source="custom",
        source_url=None,
        source_instance="pi",
        tags=["custom"],
        ingested_at=datetime.fromisoformat(ingested_at),
        updated_at=datetime.fromisoformat(ingested_at),
        replicated_at=None,
        replication_seq=None,
        metadata={},
    )


def test_dedupe_entries_filters_low_signal_and_same_day_duplicates(tmp_path):
    service = DigestService(storage_path=tmp_path)
    entries = [
        _entry("a", "Weekly Pi Cleanup", "SILENT", ingested_at="2026-04-12T11:01:00+00:00"),
        _entry("b", "Daily Pi Health Check", "---", ingested_at="2026-04-12T10:01:00+00:00"),
        _entry("f", "Daily Security Scan", "SILENT — Clean scan: no issues", ingested_at="2026-04-12T09:01:00+00:00"),
        _entry("c", "Daily Security Scan", "Meaningful finding", ingested_at="2026-04-13T09:01:00+00:00"),
        _entry("d", "Daily Security Scan", "Meaningful finding", ingested_at="2026-04-13T09:05:00+00:00"),
        _entry("e", "Daily Security Scan", "Different summary", ingested_at="2026-04-13T09:06:00+00:00"),
    ]

    filtered = service._dedupe_entries(entries)

    assert [entry.id for entry in filtered] == ["e", "d"]


def test_build_stats_response_uses_cleaned_entries(tmp_path):
    service = DigestService(storage_path=tmp_path)
    entries = [
        _entry("a", "Weekly Pi Cleanup", "SILENT — Clean scan", ingested_at="2026-04-12T11:01:00+00:00"),
        _entry("b", "Daily Pi Health Check", "---", ingested_at="2026-04-12T10:01:00+00:00"),
        _entry("c", "Daily Security Scan", "Meaningful finding", ingested_at="2026-04-13T09:01:00+00:00"),
        _entry("d", "Daily Security Scan", "Meaningful finding", ingested_at="2026-04-13T09:05:00+00:00"),
    ]

    stats = service._build_stats_response(service._dedupe_entries(entries))

    assert stats.total_entries == 1
    assert stats.by_source == {"custom": 1}
    assert stats.by_instance == {"pi": 1}


def test_get_entry_hydrates_content_from_output_file(tmp_path):
    service = DigestService(storage_path=tmp_path)
    output_file = tmp_path / "cron-output.md"
    output_file.write_text("# Header\n\n## Response\n\nFull report body\n\n- bullet one\n", encoding="utf-8")

    entry = _entry("z", "Daily Security Scan", "Meaningful finding", ingested_at="2026-04-13T09:01:00+00:00")
    payload = entry.model_dump(mode="json")
    payload["metadata"] = {"output_file": str(output_file)}
    (tmp_path / "entries.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")

    hydrated = service.get_entry("z")

    assert hydrated is not None
    assert hydrated.content == "Full report body\n\n- bullet one"
