from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hermes_constants import get_hermes_home
from scripts.sync_hindsight_runtime import resolve_hindsight_backend_env, write_env_file


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def _load_root_sources() -> tuple[Path, dict[str, Any], dict[str, str]]:
    hermes_home = get_hermes_home()
    config_path = hermes_home / "config.yaml"
    env_path = hermes_home / ".env"

    config: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            config = loaded

    env_values = _load_env_file(env_path)
    return hermes_home, config, env_values


def _nonempty(raw: str | None, default: str = "") -> str:
    text = (raw or "").strip()
    return text or default


def build_mission_control_env() -> dict[str, str]:
    hermes_home, config, env_values = _load_root_sources()
    memory_cfg = config.get("memory", {}) if isinstance(config.get("memory"), dict) else {}

    generated = {
        "ENVIRONMENT": _nonempty(env_values.get("ENVIRONMENT"), "production"),
        "AUTH_MODE": _nonempty(env_values.get("AUTH_MODE"), "all"),
        "BEARER_TOKEN": _nonempty(env_values.get("BEARER_TOKEN")),
        "PI_STATUS_URL": _nonempty(env_values.get("PI_STATUS_URL")),
        "PI_BEARER_TOKEN": _nonempty(env_values.get("PI_BEARER_TOKEN")),
        "EXPOSE_DOCS": _nonempty(env_values.get("EXPOSE_DOCS"), "false"),
        "CORS_ORIGINS": _nonempty(env_values.get("CORS_ORIGINS"), "[]"),
        "DASHBOARD_AUTH_MODE": _nonempty(env_values.get("DASHBOARD_AUTH_MODE"), "cloudflare"),
        "DASHBOARD_SHARED_SECRET": _nonempty(env_values.get("DASHBOARD_SHARED_SECRET")),
        "HERMES_HOME": str(hermes_home),
        "MC_HOST": _nonempty(env_values.get("MC_HOST"), "127.0.0.1"),
        "MC_PORT": _nonempty(env_values.get("MC_PORT"), "8767"),
        "MEMORY_INGEST_BACKEND": _nonempty(env_values.get("MEMORY_INGEST_BACKEND"), "hindsight"),
        "MEMORY_INGEST_HMAC_SECRET": _nonempty(env_values.get("MEMORY_INGEST_HMAC_SECRET")),
        "MEMORY_INGEST_HMAC_NEXT_SECRET": _nonempty(env_values.get("MEMORY_INGEST_HMAC_NEXT_SECRET")),
        "MEMORY_INGEST_ALLOWED_SOURCES": _nonempty(
            env_values.get("MEMORY_INGEST_ALLOWED_SOURCES"),
            '["127.0.0.1"]',
        ),
        "MEMORY_INGEST_HINDSIGHT_BASE_URL": _nonempty(
            env_values.get("MEMORY_INGEST_HINDSIGHT_BASE_URL"),
            "http://127.0.0.1:9177",
        ),
        "MEMORY_INGEST_HINDSIGHT_BANK": _nonempty(
            env_values.get("MEMORY_INGEST_HINDSIGHT_BANK"),
            str(memory_cfg.get("bank_id") or "hermes"),
        ),
    }
    # Preserve all root .env values so Mission Control service restarts do not
    # silently drop unrelated runtime configuration.
    return {**env_values, **generated}


def build_lan_proxies_env() -> dict[str, str]:
    _hermes_home, _config, env_values = _load_root_sources()
    return {
        "HERMES_LAN_PROXY_ALLOW_CIDRS": _nonempty(
            env_values.get("HERMES_LAN_PROXY_ALLOW_CIDRS"),
            "192.168.0.0/24",
        ),
        "HERMES_LAN_PROXY_TIMEOUT_SECS": _nonempty(
            env_values.get("HERMES_LAN_PROXY_TIMEOUT_SECS"),
            "60",
        ),
    }


def sync_targets(*, mission_control: bool, lan_proxies: bool, hindsight: bool) -> list[Path]:
    written: list[Path] = []
    if mission_control:
        target = Path.home() / ".config" / "hermes" / "mission-control.env"
        write_env_file(target, build_mission_control_env())
        target.chmod(0o600)
        written.append(target)
    if lan_proxies:
        target = Path.home() / ".config" / "hermes" / "lan-proxies.env"
        write_env_file(target, build_lan_proxies_env())
        target.chmod(0o600)
        written.append(target)
    if hindsight:
        target = Path.home() / ".hindsight" / "profiles" / "hermes.env"
        write_env_file(target, resolve_hindsight_backend_env())
        target.chmod(0o600)
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate service env files from ~/.hermes sources")
    parser.add_argument("--mission-control", action="store_true", help="Write ~/.config/hermes/mission-control.env")
    parser.add_argument("--lan-proxies", action="store_true", help="Write ~/.config/hermes/lan-proxies.env")
    parser.add_argument("--hindsight", action="store_true", help="Write ~/.hindsight/profiles/hermes.env")
    parser.add_argument("--all", action="store_true", help="Write all generated runtime env files")
    args = parser.parse_args()

    if not any((args.mission_control, args.lan_proxies, args.hindsight, args.all)):
        parser.error("Choose at least one target or use --all")

    written = sync_targets(
        mission_control=args.all or args.mission_control,
        lan_proxies=args.all or args.lan_proxies,
        hindsight=args.all or args.hindsight,
    )
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
