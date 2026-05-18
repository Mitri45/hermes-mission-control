#!/usr/bin/env python3
"""Install Mission Control's Hermes dashboard plugin into a Hermes checkout.

Default plugin target is ~/.hermes/hermes-agent/plugins/mission-control.
Default theme target is ~/.hermes/dashboard-themes/dima-readable.yaml.
Override with --hermes-repo /path/to/hermes-agent.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "plugins" / "mission-control"
    if not source.is_dir():
        raise SystemExit(f"Missing plugin source: {source}")
    theme_source = repo_root / "themes" / "dima-readable.yaml"
    if not theme_source.is_file():
        raise SystemExit(f"Missing dashboard theme source: {theme_source}")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hermes-repo",
        default=str(Path.home() / ".hermes" / "hermes-agent"),
        help="Hermes checkout path; default: ~/.hermes/hermes-agent",
    )
    parser.add_argument(
        "--theme-dir",
        default=str(Path.home() / ".hermes" / "dashboard-themes"),
        help="Hermes dashboard theme directory; default: ~/.hermes/dashboard-themes",
    )
    parser.add_argument(
        "--skip-theme",
        action="store_true",
        help="Only install the plugin; do not copy the bundled readable theme.",
    )
    parser.add_argument(
        "--skip-theme-activation",
        action="store_true",
        help="Copy the bundled readable theme but do not run `hermes config set dashboard.theme dima-readable`.",
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

    if not args.skip_theme:
        theme_dir = Path(args.theme_dir).expanduser().resolve()
        theme_dir.mkdir(parents=True, exist_ok=True)
        theme_target = theme_dir / theme_source.name
        shutil.copy2(theme_source, theme_target)
        print(f"Installed readable dashboard theme: {theme_target}")

        if not args.skip_theme_activation:
            hermes_bin = shutil.which("hermes")
            if hermes_bin is None:
                print(
                    "Theme copied, but `hermes` was not found on PATH; "
                    "activate manually with: hermes config set dashboard.theme dima-readable"
                )
            else:
                subprocess.run(
                    [hermes_bin, "config", "set", "dashboard.theme", "dima-readable"],
                    check=True,
                )
                print("Activated dashboard theme: dima-readable")

    print("Verify with: hermes dashboard --no-open --port 9119")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
