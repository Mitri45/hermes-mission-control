"""Provider visibility service for Hermes Web View (DIM-235)."""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from app.core.config import get_settings
from app.models.schemas import (
    ProviderFlowUsage,
    ProviderStatusItem,
    ProviderStatusResponse,
    ProviderStatusSummary,
)

_INSTANCE_FILTER = Literal["all", "pc", "pi"]
_logger = logging.getLogger(__name__)

# Credential cooldown windows mirror Hermes credential-pool defaults.
_EXHAUSTED_TTL_429_SECONDS = 60 * 60
_EXHAUSTED_TTL_DEFAULT_SECONDS = 24 * 60 * 60

_PROVIDER_ALIASES = {
    "glm": "zai",
    "z.ai": "zai",
    "z-ai": "zai",
    "z_ai": "zai",
    "moonshot": "kimi-coding",
    "kimi": "kimi-coding",
    "claude": "anthropic",
    "claude-code": "anthropic",
    "codex": "openai-codex",
    "openaicodex": "openai-codex",
    "openai_codex": "openai-codex",
    "open-router": "openrouter",
}


@dataclass(frozen=True)
class _ProviderMeta:
    name: str
    default_base_url: str | None
    env_keys: tuple[str, ...]
    base_url_env: str | None = None


_PROVIDER_REGISTRY: dict[str, _ProviderMeta] = {
    "openrouter": _ProviderMeta(
        name="OpenRouter",
        default_base_url="https://openrouter.ai/api/v1",
        env_keys=("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
        base_url_env="OPENROUTER_BASE_URL",
    ),
    "openai-codex": _ProviderMeta(
        name="OpenAI Codex",
        default_base_url="https://chatgpt.com/backend-api/codex",
        env_keys=("OPENAI_API_KEY", "OPENAI_CODEX_API_KEY"),
        base_url_env=None,
    ),
    "anthropic": _ProviderMeta(
        name="Anthropic",
        default_base_url="https://api.anthropic.com",
        env_keys=("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    ),
    "zai": _ProviderMeta(
        name="Z.AI / GLM",
        default_base_url="https://api.z.ai/api/paas/v4",
        env_keys=("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
        base_url_env="GLM_BASE_URL",
    ),
    "kimi-coding": _ProviderMeta(
        name="Kimi / Moonshot",
        default_base_url="https://api.moonshot.ai/v1",
        env_keys=("KIMI_API_KEY",),
        base_url_env="KIMI_BASE_URL",
    ),
    "minimax": _ProviderMeta(
        name="MiniMax",
        default_base_url="https://api.minimax.io/anthropic",
        env_keys=("MINIMAX_API_KEY",),
        base_url_env="MINIMAX_BASE_URL",
    ),
    "minimax-cn": _ProviderMeta(
        name="MiniMax (China)",
        default_base_url="https://api.minimaxi.com/anthropic",
        env_keys=("MINIMAX_CN_API_KEY",),
        base_url_env="MINIMAX_CN_BASE_URL",
    ),
    "copilot": _ProviderMeta(
        name="GitHub Copilot",
        default_base_url="https://api.githubcopilot.com",
        env_keys=("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
    ),
}


@dataclass(frozen=True)
class _FlowConfig:
    flow: str
    instance: Literal["pc", "pi"]
    provider: str
    model: str | None
    base_url: str | None
    source: str | None = None


@dataclass(frozen=True)
class _OffLimitsMarker:
    until: datetime
    reason: str | None = None


def _safe_read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        _logger.warning("Failed to read YAML config from %s: %s", path, exc)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _safe_read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    result: dict[str, str] = {}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key:
                result[key] = value
    except (OSError, UnicodeDecodeError) as exc:
        _logger.warning("Failed to read env file from %s: %s", path, exc)
        return {}

    return result


def _hindsight_profile_env_path() -> Path:
    explicit = (os.environ.get("HINDSIGHT_PROFILE_ENV") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".hindsight" / "profiles" / "hermes.env"


def _first_non_empty(values: list[str | None]) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    if text.isdigit():
        try:
            value = int(text)
            if value > 10_000_000_000:
                value = value // 1000
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _humanize_seconds(seconds: int) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, _ = divmod(rem, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{total}s"


def _normalize_provider(raw: str | None, *, base_url: str | None = None, model: str | None = None) -> str | None:
    cleaned = (raw or "").strip().lower()
    cleaned = _PROVIDER_ALIASES.get(cleaned, cleaned)

    if cleaned == "auto":
        cleaned = ""
    if cleaned in _PROVIDER_REGISTRY or cleaned.startswith("custom:"):
        return cleaned

    url = (base_url or "").strip().lower()
    if "openrouter.ai" in url:
        return "openrouter"
    if "anthropic.com" in url:
        return "anthropic"
    if "moonshot.ai" in url or "api.kimi.com" in url:
        return "kimi-coding"
    if "api.minimax.io" in url or "api.minimaxi.com" in url:
        return "minimax-cn" if "minimaxi.com" in url else "minimax"
    if "api.z.ai" in url or "open.bigmodel.cn" in url:
        return "zai"
    if "chatgpt.com/backend-api/codex" in url:
        return "openai-codex"
    if "api.githubcopilot.com" in url:
        return "copilot"
    if url and cleaned in {"custom", "local"}:
        return "custom:local"

    model_l = (model or "").strip().lower()
    if model_l.startswith("claude"):
        return "anthropic"
    if model_l.startswith("gpt-") or model_l.startswith("o1") or model_l.startswith("o3") or model_l.startswith("o4"):
        return "openai-codex"
    if model_l.startswith("glm"):
        return "zai"
    if model_l.startswith("kimi"):
        return "kimi-coding"
    if model_l.startswith("minimax"):
        return "minimax"

    return cleaned or None


def _read_auth_store(hermes_home: Path) -> dict[str, Any]:
    auth_file = hermes_home / "auth.json"
    if not auth_file.exists():
        return {}
    try:
        payload = json.loads(auth_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _logger.warning("Failed to parse auth store from %s: %s", auth_file, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _exhausted_ttl(error_code: int | None) -> int:
    if error_code == 429:
        return _EXHAUSTED_TTL_429_SECONDS
    return _EXHAUSTED_TTL_DEFAULT_SECONDS


def _coerce_entry(pool_entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(pool_entry)
    entry.setdefault("source", "unknown")
    entry.setdefault("access_token", "")
    entry.setdefault("base_url", "")
    return entry


def _mask_key_source(raw_source: str | None) -> str | None:
    """Avoid leaking credential variable names in API responses."""
    source = (raw_source or "").strip()
    if not source:
        return None
    if source.startswith("env:"):
        return "env"
    if source in {"device_code", "oauth", "token", "unknown"}:
        return source
    return "config"


class ProviderStatusService:
    """Aggregates provider health/configuration data for dashboard visibility."""

    def __init__(self):
        self._settings = None

    @property
    def settings(self):
        """Lazily resolve runtime settings to avoid import-time config coupling."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _discover_flows(self) -> tuple[list[_FlowConfig], dict[str, str]]:
        flows: list[_FlowConfig] = []
        merged_env: dict[str, str] = {}

        hermes_home = Path(self.settings.hermes_home)
        config_path = hermes_home / "config.yaml"
        hermes_env_path = hermes_home / ".env"
        honcho_env_path = Path(os.environ.get("HONCHO_ENV_FILE", str(Path.home() / "honcho" / ".env")))
        hindsight_env_path = _hindsight_profile_env_path()

        config = _safe_read_yaml(config_path)
        hermes_env = _safe_read_env(hermes_env_path)
        honcho_env = _safe_read_env(honcho_env_path)
        hindsight_env = _safe_read_env(hindsight_env_path)

        merged_env.update(hermes_env)
        merged_env.update(honcho_env)
        merged_env.update(hindsight_env)
        merged_env.update({k: v for k, v in os.environ.items() if isinstance(v, str)})

        model_cfg = config.get("model")
        cfg_provider = ""
        cfg_model = ""
        cfg_base_url = ""
        if isinstance(model_cfg, str):
            cfg_model = model_cfg.strip()
        elif isinstance(model_cfg, dict):
            cfg_provider = str(model_cfg.get("provider", "") or "").strip()
            cfg_model = str(model_cfg.get("default") or model_cfg.get("model") or model_cfg.get("name") or "").strip()
            cfg_base_url = str(model_cfg.get("base_url", "") or "").strip()

        main_provider = _normalize_provider(
            _first_non_empty([cfg_provider, hermes_env.get("HERMES_PROVIDER"), os.getenv("HERMES_PROVIDER")]),
            base_url=_first_non_empty([cfg_base_url, hermes_env.get("HERMES_BASE_URL"), os.getenv("HERMES_BASE_URL")]),
            model=_first_non_empty([cfg_model, hermes_env.get("HERMES_MODEL"), os.getenv("HERMES_MODEL")]),
        )
        main_model = _first_non_empty([cfg_model, hermes_env.get("HERMES_MODEL"), os.getenv("HERMES_MODEL")])
        main_base_url = _first_non_empty([cfg_base_url, hermes_env.get("HERMES_BASE_URL"), os.getenv("HERMES_BASE_URL")])

        if main_provider:
            flows.append(
                _FlowConfig(
                    flow="Hermes Main",
                    instance="pc",
                    provider=main_provider,
                    model=main_model,
                    base_url=main_base_url,
                    source=str(config_path if config_path.exists() else hermes_env_path),
                )
            )

        fallback_chain = config.get("fallback_providers")
        if isinstance(fallback_chain, dict):
            fallback_chain = [fallback_chain]
        if not isinstance(fallback_chain, list):
            legacy = config.get("fallback_model")
            if isinstance(legacy, dict):
                fallback_chain = [legacy]
            elif isinstance(legacy, list):
                fallback_chain = legacy
            else:
                fallback_chain = []

        for idx, candidate in enumerate(fallback_chain):
            if not isinstance(candidate, dict):
                continue
            provider = _normalize_provider(
                str(candidate.get("provider", "") or "").strip(),
                base_url=str(candidate.get("base_url", "") or "").strip(),
                model=str(candidate.get("model", "") or "").strip(),
            )
            if not provider:
                continue
            flows.append(
                _FlowConfig(
                    flow=f"Hermes Fallback #{idx + 1}",
                    instance="pc",
                    provider=provider,
                    model=str(candidate.get("model", "") or "").strip() or None,
                    base_url=str(candidate.get("base_url", "") or "").strip() or None,
                    source=str(config_path),
                )
            )

        linear_backend = str(
            config.get("linear_backend")
            or hermes_env.get("HERMES_LINEAR_DEFAULT_BACKEND")
            or os.getenv("HERMES_LINEAR_DEFAULT_BACKEND")
            or self.settings.linear_default_backend
        ).strip().lower()
        if linear_backend == "codex":
            flows.append(
                _FlowConfig(
                    flow="Linear Agents",
                    instance="pc",
                    provider="openai-codex",
                    model=_first_non_empty([os.getenv("HERMES_CODEX_MODEL"), hermes_env.get("HERMES_CODEX_MODEL"), "gpt-4o"]),
                    base_url=None,
                    source=str(config_path),
                )
            )
        elif main_provider:
            flows.append(
                _FlowConfig(
                    flow="Linear Agents",
                    instance="pc",
                    provider=main_provider,
                    model=main_model,
                    base_url=main_base_url,
                    source=str(config_path),
                )
            )

        honcho_provider = _normalize_provider(
            _first_non_empty(
                [
                    honcho_env.get("DIALECTIC_PROVIDER"),
                    honcho_env.get("HONCHO_PROVIDER"),
                    honcho_env.get("HONCHO_LLM_PROVIDER"),
                    honcho_env.get("HERMES_PROVIDER"),
                ]
            ),
            base_url=_first_non_empty(
                [
                    honcho_env.get("DIALECTIC_BASE_URL"),
                    honcho_env.get("HONCHO_BASE_URL"),
                    honcho_env.get("HONCHO_LLM_BASE_URL"),
                    honcho_env.get("HERMES_BASE_URL"),
                ]
            ),
            model=_first_non_empty(
                [
                    honcho_env.get("DIALECTIC_MODEL"),
                    honcho_env.get("HONCHO_MODEL"),
                    honcho_env.get("HONCHO_LLM_MODEL"),
                    honcho_env.get("HERMES_MODEL"),
                ]
            ),
        )
        if honcho_provider:
            flows.append(
                _FlowConfig(
                    flow="Honcho Dialectic",
                    instance="pi",
                    provider=honcho_provider,
                    model=_first_non_empty(
                        [
                            honcho_env.get("DIALECTIC_MODEL"),
                            honcho_env.get("HONCHO_MODEL"),
                            honcho_env.get("HONCHO_LLM_MODEL"),
                            honcho_env.get("HERMES_MODEL"),
                        ]
                    ),
                    base_url=_first_non_empty(
                        [
                            honcho_env.get("DIALECTIC_BASE_URL"),
                            honcho_env.get("HONCHO_BASE_URL"),
                            honcho_env.get("HONCHO_LLM_BASE_URL"),
                            honcho_env.get("HERMES_BASE_URL"),
                        ]
                    ),
                    source=str(honcho_env_path),
                )
            )

        hindsight_provider = _normalize_provider(
            hindsight_env.get("HINDSIGHT_API_LLM_PROVIDER"),
            base_url=hindsight_env.get("HINDSIGHT_API_LLM_BASE_URL"),
            model=hindsight_env.get("HINDSIGHT_API_LLM_MODEL"),
        )
        if hindsight_provider:
            flows.append(
                _FlowConfig(
                    flow="Hindsight Memory",
                    instance="pc",
                    provider=hindsight_provider,
                    model=_first_non_empty([hindsight_env.get("HINDSIGHT_API_LLM_MODEL")]),
                    base_url=_first_non_empty([hindsight_env.get("HINDSIGHT_API_LLM_BASE_URL")]),
                    source=str(hindsight_env_path),
                )
            )

        return flows, merged_env

    def _provider_name(self, provider_id: str) -> str:
        if provider_id.startswith("custom:"):
            return f"Custom ({provider_id.split(':', 1)[1]})"
        meta = _PROVIDER_REGISTRY.get(provider_id)
        if meta:
            return meta.name
        return provider_id

    def _provider_prefixes(self, provider_id: str) -> list[str]:
        if provider_id == "kimi-coding":
            return ["KIMI", "MOONSHOT"]
        if provider_id == "zai":
            return ["GLM", "ZAI", "Z_AI"]
        if provider_id == "openai-codex":
            return ["OPENAI_CODEX", "CODEX"]
        if provider_id == "openrouter":
            return ["OPENROUTER"]
        return [provider_id.replace("-", "_").upper()]

    def _find_off_limits_marker(self, provider_id: str, env_values: dict[str, str]) -> _OffLimitsMarker | None:
        for prefix in self._provider_prefixes(provider_id):
            until = _first_non_empty(
                [
                    env_values.get(f"{prefix}_OFF_LIMITS_UNTIL"),
                    env_values.get(f"{prefix}_QUOTA_RESET_AT"),
                    env_values.get(f"{prefix}_RESET_AT"),
                ]
            )
            parsed = _parse_timestamp(until)
            if parsed is None:
                continue
            reason = _first_non_empty(
                [
                    env_values.get(f"{prefix}_OFF_LIMITS_REASON"),
                    env_values.get(f"{prefix}_LAST_ERROR"),
                    env_values.get(f"{prefix}_QUOTA_REASON"),
                ]
            )
            return _OffLimitsMarker(until=parsed, reason=reason)
        return None

    def _credential_entries_for_provider(
        self,
        provider_id: str,
        auth_store: dict[str, Any],
        env_values: dict[str, str],
    ) -> list[dict[str, Any]]:
        pool = auth_store.get("credential_pool")
        persisted = pool.get(provider_id) if isinstance(pool, dict) else None
        entries: list[dict[str, Any]] = []

        if isinstance(persisted, list):
            for entry in persisted:
                if isinstance(entry, dict):
                    entries.append(_coerce_entry(entry))

        meta = _PROVIDER_REGISTRY.get(provider_id)
        if meta:
            base_url = _first_non_empty(
                [
                    env_values.get(meta.base_url_env) if meta.base_url_env else None,
                    meta.default_base_url,
                ]
            )
            for env_key in meta.env_keys:
                token = (env_values.get(env_key) or "").strip()
                if not token:
                    continue
                if any((entry.get("source") or "") == f"env:{env_key}" for entry in entries):
                    continue
                entries.append(
                    {
                        "source": f"env:{env_key}",
                        "access_token": token,
                        "base_url": base_url or "",
                    }
                )

        hindsight_provider = _normalize_provider(
            env_values.get("HINDSIGHT_API_LLM_PROVIDER"),
            base_url=env_values.get("HINDSIGHT_API_LLM_BASE_URL"),
            model=env_values.get("HINDSIGHT_API_LLM_MODEL"),
        )
        if hindsight_provider == provider_id:
            token = str(env_values.get("HINDSIGHT_API_LLM_API_KEY") or "").strip()
            if token and not any((entry.get("source") or "") == "config:hindsight-runtime" for entry in entries):
                entries.append(
                    {
                        "source": "config:hindsight-runtime",
                        "access_token": token,
                        "base_url": str(env_values.get("HINDSIGHT_API_LLM_BASE_URL") or "").strip(),
                    }
                )

        if provider_id == "openai-codex":
            providers = auth_store.get("providers")
            codex_state = providers.get("openai-codex") if isinstance(providers, dict) else None
            tokens = codex_state.get("tokens") if isinstance(codex_state, dict) else None
            if isinstance(tokens, dict) and isinstance(tokens.get("access_token"), str) and tokens.get("access_token"):
                if not any((entry.get("source") or "") == "device_code" for entry in entries):
                    entries.append(
                        {
                            "source": "device_code",
                            "access_token": tokens.get("access_token"),
                            "base_url": "https://chatgpt.com/backend-api/codex",
                        }
                    )

        return entries

    def _entry_cooldown_remaining(self, entry: dict[str, Any], now_ts: float) -> int | None:
        if entry.get("last_status") != "exhausted":
            return None
        last_status_at = entry.get("last_status_at")
        if not isinstance(last_status_at, (int, float)):
            return None
        error_code = entry.get("last_error_code")
        ttl = _exhausted_ttl(int(error_code) if isinstance(error_code, int) else None)
        remaining = int(math.ceil((float(last_status_at) + float(ttl)) - now_ts))
        return max(0, remaining)

    def _build_provider_item(
        self,
        provider_id: str,
        flows: list[_FlowConfig],
        entries: list[dict[str, Any]],
        env_values: dict[str, str],
    ) -> ProviderStatusItem:
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()

        flow_base_url = _first_non_empty([flow.base_url for flow in flows])
        flow_model = _first_non_empty([flow.model for flow in flows])
        has_flows = bool(flows)

        cooldown_entries: list[tuple[dict[str, Any], int]] = []
        available_entries: list[dict[str, Any]] = []
        configured_entries: list[dict[str, Any]] = []
        for entry in entries:
            token = str(entry.get("access_token") or "").strip()
            if token:
                configured_entries.append(entry)
            remaining = self._entry_cooldown_remaining(entry, now_ts)
            if remaining is not None and remaining > 0:
                cooldown_entries.append((entry, remaining))
                continue
            if token:
                available_entries.append(entry)

        has_credentials = bool(configured_entries)
        has_available = bool(available_entries)

        status: Literal["active", "off-limits", "exhausted", "misconfigured", "unknown"] = "unknown"
        status_reason: str | None = None
        recovery_eta_seconds: int | None = None
        recovery_eta: datetime | None = None
        last_error: str | None = None

        if has_flows and not has_credentials:
            status = "misconfigured"
            status_reason = "Configured in one or more flows but no usable credentials were found."
        elif cooldown_entries and not has_available:
            codes = {item[0].get("last_error_code") for item in cooldown_entries}
            if 402 in codes:
                status = "exhausted"
                status_reason = "All credentials are exhausted (billing/quota cooldown active)."
            else:
                status = "off-limits"
                status_reason = "All credentials are temporarily blocked by cooldown."
            recovery_eta_seconds = min(remaining for _, remaining in cooldown_entries)
            recovery_eta = now + timedelta(seconds=recovery_eta_seconds)
            status_reason = f"{status_reason} Retry in ~{_humanize_seconds(recovery_eta_seconds)}."
            latest = max(
                cooldown_entries,
                key=lambda item: float(item[0].get("last_status_at") or 0.0),
            )[0]
            err_code = latest.get("last_error_code")
            last_error = f"HTTP {err_code} cooldown active" if err_code else "Credential cooldown active"
        elif has_available or has_credentials:
            status = "active"
            status_reason = "At least one credential is currently available."
        elif has_flows:
            status = "misconfigured"
            status_reason = "Flow is configured but no provider credentials are available."

        marker = self._find_off_limits_marker(provider_id, env_values)
        if marker and marker.until > now:
            status = "off-limits"
            recovery_eta = marker.until
            recovery_eta_seconds = int((marker.until - now).total_seconds())
            marker_reason = marker.reason or f"Provider manually marked off-limits until {marker.until.isoformat()}."
            status_reason = f"{marker_reason} (~{_humanize_seconds(recovery_eta_seconds)} remaining)"
            if last_error is None:
                last_error = marker.reason or "Manual off-limits marker"

        if status == "unknown" and has_flows:
            status = "misconfigured"
            status_reason = status_reason or "Provider appears in flow config but has no runtime status."

        base_url = flow_base_url
        if not base_url:
            for entry in entries:
                candidate = str(entry.get("base_url") or "").strip()
                if candidate:
                    base_url = candidate
                    break

        key_source = None
        for entry in entries:
            source = str(entry.get("source") or "").strip()
            if source:
                key_source = _mask_key_source(source)
                break

        seen_flows: set[tuple[str, str, str | None]] = set()
        flow_payload: list[ProviderFlowUsage] = []
        for flow in flows:
            signature = (flow.flow, flow.instance, flow.model)
            if signature in seen_flows:
                continue
            seen_flows.add(signature)
            flow_payload.append(
                ProviderFlowUsage(
                    flow=flow.flow,
                    instance=flow.instance,
                    model=flow.model,
                )
            )

        return ProviderStatusItem(
            provider=provider_id,
            name=self._provider_name(provider_id),
            base_url=base_url,
            current_model=flow_model,
            status=status,
            status_reason=status_reason,
            recovery_eta_seconds=recovery_eta_seconds,
            recovery_eta=recovery_eta,
            primary_flows=flow_payload,
            last_error=last_error,
            key_source=key_source,
        )

    def get_provider_status(self, instance: _INSTANCE_FILTER = "all") -> ProviderStatusResponse:
        if instance not in {"all", "pc", "pi"}:
            raise ValueError(f"Invalid instance filter: {instance}")

        flows, env_values = self._discover_flows()
        auth_store = _read_auth_store(Path(self.settings.hermes_home))

        providers_from_flows = {flow.provider for flow in flows if flow.provider}
        providers_from_pool: set[str] = set()
        pool = auth_store.get("credential_pool")
        if isinstance(pool, dict):
            providers_from_pool = {key for key, value in pool.items() if isinstance(key, str) and isinstance(value, list)}

        providers_from_env: set[str] = set()
        for provider_id, meta in _PROVIDER_REGISTRY.items():
            if any((env_values.get(key) or "").strip() for key in meta.env_keys):
                providers_from_env.add(provider_id)

        provider_ids = providers_from_flows | providers_from_pool | providers_from_env
        if not provider_ids:
            return ProviderStatusResponse(instance=instance)

        providers: list[ProviderStatusItem] = []
        for provider_id in sorted(provider_ids):
            provider_flows = [
                flow
                for flow in flows
                if flow.provider == provider_id and (instance == "all" or flow.instance == instance)
            ]
            if instance != "all" and not provider_flows:
                continue

            entries = self._credential_entries_for_provider(provider_id, auth_store, env_values)
            item = self._build_provider_item(provider_id, provider_flows, entries, env_values)
            if instance == "all" and not provider_flows and item.status == "unknown":
                continue
            providers.append(item)

        summary = ProviderStatusSummary(total=len(providers))
        for provider in providers:
            if provider.status == "active":
                summary.active += 1
            elif provider.status == "off-limits":
                summary.off_limits += 1
            elif provider.status == "exhausted":
                summary.exhausted += 1
            elif provider.status == "misconfigured":
                summary.misconfigured += 1
            else:
                summary.unknown += 1

        return ProviderStatusResponse(
            instance=instance,
            providers=providers,
            summary=summary,
        )


# Singleton instance
provider_status_service = ProviderStatusService()
