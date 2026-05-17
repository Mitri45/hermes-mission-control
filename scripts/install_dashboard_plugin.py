#!/usr/bin/env python3
"""Install Mission Control's Hermes dashboard plugin into a Hermes checkout.

Default target is ~/.hermes/hermes-agent/plugins/mission-control.
Override with --hermes-repo /path/to/hermes-agent.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "plugins" / "mission-control"
    if not source.is_dir():
        raise SystemExit(f"Missing plugin source: {source}")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hermes-repo",
        default=str(Path.home() / ".hermes" / "hermes-agent"),
        help="Hermes checkout path; default: ~/.hermes/hermes-agent",
    )
    args = parser.parse_args()

    hermes_repo = Path(args.hermes_repo).expanduser().resolve()
    if not (hermes_repo / "hermes_cli").is_dir():
        raise SystemExit(f"Not a Hermes checkout: {hermes_repo}")

    target = hermes_repo / "plugins" / "mission-control"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("node_modules", "__pycache__", "*.pyc"),
    )
    print(f"Installed Mission Control dashboard plugin: {target}")
    print("Verify with: hermes dashboard --no-open --port 9119")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
