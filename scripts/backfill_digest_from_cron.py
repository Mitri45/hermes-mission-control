#!/usr/bin/env python3
"""Backfill Daily Digest entries from saved cron output markdown files."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cron.digest_journal import append_digest_for_job_run
from cron.jobs import load_jobs, OUTPUT_DIR

_RESPONSE_SPLIT_RE = re.compile(r"^## Response\s*$", re.MULTILINE)


def _extract_response(markdown: str) -> str:
    """Return the response section from a saved cron markdown output."""
    parts = _RESPONSE_SPLIT_RE.split(markdown, maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _is_failed_output(markdown: str) -> bool:
    """Detect failed cron output documents."""
    header = markdown.splitlines()[0] if markdown.splitlines() else ""
    return "(FAILED)" in header


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill digest entries from saved cron outputs")
    parser.add_argument("--days", type=int, default=14, help="Only import outputs from the last N days")
    parser.add_argument("--instance", default="pi", choices=["pc", "pi"], help="source_instance to stamp onto created digest entries")
    args = parser.parse_args()

    jobs = {str(job.get("id")): job for job in load_jobs()}
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, args.days))
    created = 0
    scanned = 0

    for output_file in sorted(OUTPUT_DIR.glob("*/*.md")):
        scanned += 1
        job_id = output_file.parent.name
        job = jobs.get(job_id)
        if not job:
            continue

        try:
            timestamp = datetime.strptime(output_file.stem, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if timestamp < cutoff:
            continue

        markdown = output_file.read_text(encoding="utf-8")
        if _is_failed_output(markdown):
            continue

        response = _extract_response(markdown)
        if not response or response == "(No response generated)":
            continue

        if append_digest_for_job_run(
            job,
            response,
            run_at=timestamp,
            source_instance=args.instance,
            output_file=str(output_file),
        ):
            created += 1

    print(f"Scanned {scanned} cron output files")
    print(f"Created {created} digest entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
