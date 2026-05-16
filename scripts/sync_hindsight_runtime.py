from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from hermes_constants import get_hermes_home
from hermes_cli.runtime_provider import resolve_runtime_provider


_SUPPORTED_API_MODES = {"chat_completions", "responses", "anthropic_messages", "codex_responses"}
_UNSUPPORTED_RUNTIME_PROVIDERS = {"kimi-coding", "openai-codex", "copilot-acp"}




def _load_profile_env() -> None:
    env_path = get_hermes_home() / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip()


def _load_config() -> Dict[str, Any]:
    cfg_path = get_hermes_home() / "config.yaml"
    if not cfg_path.exists():
        return {}
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _primary_target(cfg: Dict[str, Any]) -> Optional[Dict[str, str]]:
    model_cfg = cfg.get("model", {})
    if isinstance(model_cfg, str):
        return {"provider": "", "model": model_cfg.strip(), "source": "model.string"} if model_cfg.strip() else None
    if not isinstance(model_cfg, dict):
        return None
    model = str(model_cfg.get("default") or "").strip()
    provider = str(model_cfg.get("provider") or "").strip()
    if not model and not provider:
        return None
    return {
        "provider": provider,
        "model": model,
        "source": "model.default",
    }


def _fallback_targets(cfg: Dict[str, Any]) -> Iterable[Dict[str, str]]:
    for idx, entry in enumerate(cfg.get("fallback_providers") or []):
        if not isinstance(entry, dict):
            continue
        provider = str(entry.get("provider") or "").strip()
        model = str(entry.get("model") or "").strip()
        if not provider or not model:
            continue
        yield {
            "provider": provider,
            "model": model,
            "source": f"fallback_providers[{idx}]",
        }


def _candidate_targets(cfg: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    primary = _primary_target(cfg)
    if primary:
        out.append(primary)
    out.extend(_fallback_targets(cfg))
    return out


def _map_runtime_to_hindsight_env(target: Dict[str, str], runtime: Dict[str, Any]) -> Optional[Dict[str, str]]:
    runtime_provider = str(runtime.get("provider") or "").strip().lower()
    if runtime_provider in _UNSUPPORTED_RUNTIME_PROVIDERS:
        return None

    api_mode = str(runtime.get("api_mode") or "chat_completions").strip().lower()
    if api_mode not in _SUPPORTED_API_MODES:
        return None

    base_url = str(runtime.get("base_url") or "").strip().rstrip("/")
    api_key = str(runtime.get("api_key") or "").strip()
    model = str(target.get("model") or "").strip()
    if not base_url or not api_key or not model:
        return None

    # Hindsight wants provider family, not Hermes provider ids.
    if api_mode == "anthropic_messages":
        provider = "anthropic"
    else:
        provider = "openai"

    return {
        "HINDSIGHT_API_LLM_PROVIDER": provider,
        "HINDSIGHT_API_LLM_API_KEY": api_key,
        "HINDSIGHT_API_LLM_MODEL": model,
        "HINDSIGHT_API_LLM_BASE_URL": base_url,
        "HINDSIGHT_API_LOG_LEVEL": "info",
        "HINDSIGHT_API_SKIP_LLM_VERIFICATION": "true",
    }


def resolve_hindsight_backend_env() -> Dict[str, str]:
    _load_profile_env()
    cfg = _load_config()
    errors: List[str] = []
    for target in _candidate_targets(cfg):
        requested = target.get("provider") or None
        try:
            runtime = resolve_runtime_provider(requested=requested)
        except Exception as exc:
            errors.append(f"{target['source']}: runtime resolution failed for provider={requested or 'auto'}: {exc}")
            continue
        mapped = _map_runtime_to_hindsight_env(target, runtime)
        if mapped:
            return mapped
        errors.append(
            f"{target['source']}: provider={runtime.get('provider')!r} api_mode={runtime.get('api_mode')!r} "
            f"base_url={bool(runtime.get('base_url'))} api_key={bool(runtime.get('api_key'))} model={bool(target.get('model'))}"
        )
    raise RuntimeError("No usable Hermes runtime could be mapped to Hindsight backend env.\n" + "\n".join(errors))


def write_env_file(path: Path, values: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{key}={value}\n" for key, value in values.items())
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Hindsight backend env from current Hermes runtime config")
    parser.add_argument("--write-env", dest="write_env", help="Write dotenv output to this path")
    args = parser.parse_args()

    values = resolve_hindsight_backend_env()
    if args.write_env:
        write_env_file(Path(args.write_env).expanduser(), values)
    else:
        for key, value in values.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
