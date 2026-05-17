"""Mission Control dashboard plugin — backend API routes.

Mounted by the Hermes dashboard at /api/plugins/mission-control/.

Only ops-specific Mission Control surfaces belong here. Generic Hermes admin
features stay in the upstream dashboard.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter

try:  # Hermes depends on psutil, but keep imports defensive for bare tests.
    import psutil  # type: ignore
except Exception:  # pragma: no cover - exercised only in stripped envs
    psutil = None  # type: ignore

PLUGIN_NAME = "mission-control"
PLUGIN_VERSION = "0.6.0"

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _setting(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name].strip()
    # During migration the old standalone Mission Control .env may still hold
    # PI_STATUS_URL / bearer-token config. Read it as a compatibility fallback.
    legacy_env = Path.home() / "hermes-mission-control" / ".env"
    return _read_env_file(legacy_env).get(name, default).strip()


def _cpu_temp() -> float | None:
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            temp_str = result.stdout.strip().replace("temp=", "").replace("'C", "")
            return float(temp_str)
    except Exception:
        pass

    try:
        temps: list[float] = []
        for zone in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            try:
                temps.append(int(zone.read_text().strip()) / 1000.0)
            except Exception:
                continue
        return round(sum(temps) / len(temps), 1) if temps else None
    except Exception:
        return None


def _process_cmdline(proc: Any) -> str:
    try:
        return " ".join(proc.info.get("cmdline") or [])
    except Exception:
        return ""


def _process_name(proc: Any) -> str:
    try:
        return str(proc.info.get("name") or "")
    except Exception:
        return ""


def _find_process(predicate: Any) -> int | None:
    if psutil is None:
        return None
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if predicate(proc):
                    return int(proc.info["pid"])
            except Exception:
                continue
    except Exception:
        return None
    return None


def _port_listener(port: int) -> int | None:
    if psutil is None:
        return None
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and getattr(conn.laddr, "port", None) == port:
                return conn.pid
    except Exception:
        return None
    return None


def _service(name: str, port: int | None = None, pid: int | None = None) -> dict[str, Any]:
    if pid is None and port is not None:
        pid = _port_listener(port)
    status = "running" if pid else "stopped"
    return {"name": name, "status": status, "port": port, "pid": pid}


def _tailscale() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            self_info = data.get("Self", {})
            caps = str(self_info.get("Capabilities", []))
            return {
                "funnel": "funnel" in caps,
                "hostname": self_info.get("HostName", ""),
                "ip": (self_info.get("TailAddrs") or [None])[0],
            }
    except Exception:
        pass

    pid = _find_process(lambda proc: _process_name(proc) == "tailscaled")
    return {"funnel": False, "hostname": "", "ip": None, "running": bool(pid)}


def _local_status(requested_instance: str = "pc") -> dict[str, Any]:
    if psutil is None:
        raise RuntimeError("psutil is not available in the Hermes dashboard environment")

    cpu_usage = psutil.cpu_percent(interval=0.2)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    services = [
        _service("hermes-dashboard", 9119),
        _service("mission-control-legacy", 8767),
        _service("hermes-gateway", 8766, _find_process(lambda p: "gateway" in _process_cmdline(p) and "python" in _process_cmdline(p))),
        _service("matrixbridge", 8765),
        _service("cloudflared", None, _find_process(lambda p: "cloudflared" in _process_name(p) or "cloudflared" in _process_cmdline(p))),
    ]
    return {
        "requested_instance": requested_instance if requested_instance in {"all", "pc", "pi"} else "pc",
        "resolved_instance": "pc",
        "source_label": "PC local host",
        "cpu_temp": _cpu_temp(),
        "cpu_usage": cpu_usage,
        "memory_used": memory.used,
        "memory_total": memory.total,
        "disk_used": disk.used,
        "disk_total": disk.total,
        "services": services,
        "tailscale": _tailscale(),
        "timestamp": _utc_now(),
    }


def _pi_status_url() -> str:
    explicit = _setting("PI_STATUS_URL")
    if explicit:
        return explicit.rstrip("/")
    webhook_url = _setting("LINEAR_WEBHOOK_URL")
    if not webhook_url:
        return ""
    parsed = urlparse(webhook_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/api/status"


def _remote_pi_status() -> dict[str, Any]:
    url = _pi_status_url()
    if not url:
        raise RuntimeError("PI_STATUS_URL is not configured")

    token = _setting("PI_BEARER_TOKEN") or _setting("BEARER_TOKEN")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"PI telemetry HTTP {exc.code}: {detail or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"PI telemetry request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("PI telemetry response was not valid JSON") from exc

    payload["requested_instance"] = "pi"
    payload["resolved_instance"] = "pi"
    payload["source_label"] = payload.get("source_label") or "PI remote host"
    return payload


def _safe_status(instance: str) -> dict[str, Any]:
    try:
        if instance == "pi":
            return {"ok": True, "status": _remote_pi_status(), "error": None}
        return {"ok": True, "status": _local_status(instance), "error": None}
    except Exception as exc:
        return {"ok": False, "status": None, "error": str(exc)}


@router.get("/health")
async def health() -> dict[str, str]:
    """Readiness endpoint for the Mission Control dashboard plugin."""
    return {
        "status": "ok",
        "plugin": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
    }


@router.get("/summary")
async def summary() -> dict[str, object]:
    """Landing summary for migrated and pending Mission Control panels."""
    return {
        "plugin": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "status": "migrating",
        "sections": [
            {"id": "fleet-health", "label": "Fleet Health", "status": "ready"},
            {"id": "hindsight", "label": "Hindsight Bank", "status": "ready"},
            {"id": "memory-ingest", "label": "Memory Ingest", "status": "ready"},
            {"id": "linear-harness", "label": "Linear Harness", "status": "ready"},
            {"id": "digest", "label": "Digest", "status": "ready"},
            {"id": "provider-status", "label": "Provider Status", "status": "ready"},
            {"id": "operations", "label": "Operations Stream", "status": "ready"},
        ],
    }


@router.get("/fleet/status")
async def fleet_status() -> dict[str, object]:
    """Return PC/Pi fleet health for the Mission Control landing panel."""
    pc = _safe_status("pc")
    pi = _safe_status("pi")
    return {
        "generated_at": _utc_now(),
        "instances": {
            "pc": pc,
            "pi": pi,
        },
    }


# -----------------------------
# Hindsight Bank
# -----------------------------

def _hindsight_base_url() -> str:
    return (_setting("HINDSIGHT_API_URL") or _setting("HINDSIGHT_BASE_URL") or "http://127.0.0.1:9177").rstrip("/")


def _hindsight_bank_id() -> str:
    return (_setting("HINDSIGHT_BANK") or _setting("HINDSIGHT_BANK_ID") or "hermes").strip() or "hermes"


def _hindsight_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = _setting("HINDSIGHT_API_KEY")
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    return headers


def _hindsight_get_json(path: str, query: dict[str, Any] | None = None, timeout: int = 20) -> Any:
    url = f"{_hindsight_base_url()}{path}"
    if query:
        params = {key: value for key, value in query.items() if value is not None}
        if params:
            url = f"{url}?{urlencode(params)}"
    request = Request(url, headers=_hindsight_headers(), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"Hindsight HTTP {exc.code}: {detail or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Hindsight request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Hindsight response was not valid JSON") from exc


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _date_to_utc_start(value: date | None) -> datetime | None:
    return datetime.combine(value, time.min, tzinfo=timezone.utc) if value else None


def _date_to_utc_end(value: date | None) -> datetime | None:
    return datetime.combine(value, time.max, tzinfo=timezone.utc) if value else None


def _safe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _safe_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if v is not None}


def _source_peer(metadata: dict[str, str], tags: list[str], content: str) -> str:
    for key in ("source_peer", "source", "instance", "peer", "node"):
        raw = metadata.get(key, "").strip().lower()
        if raw in {"pc", "desktop", "main"}:
            return "pc"
        if raw in {"pi", "raspberrypi", "raspberry-pi"}:
            return "pi"
    tag_set = {tag.lower() for tag in tags}
    if tag_set & {"pc", "desktop"}:
        return "pc"
    if tag_set & {"pi", "raspberrypi", "raspberry-pi"}:
        return "pi"
    text = content.lower()
    if "raspberry pi" in text or "source_peer=pi" in text:
        return "pi"
    return "unknown"


def _normalize_fact(raw: dict[str, Any]) -> dict[str, Any]:
    metadata = _safe_dict(raw.get("metadata"))
    tags = [str(tag) for tag in _safe_list(raw.get("tags"))]
    entities = [str(entity) for entity in _safe_list(raw.get("entities"))]
    content = str(raw.get("content") or raw.get("text") or raw.get("fact") or "").strip()
    context = str(raw.get("context") or metadata.get("context") or "uncategorized").strip() or "uncategorized"
    fact_id = str(raw.get("id") or raw.get("memory_id") or raw.get("memoryId") or "").strip()
    if not fact_id:
        fact_id = f"synthetic:{abs(hash((context, content, str(raw.get('date')))))}"
    timestamp = _coerce_datetime(raw.get("timestamp") or raw.get("date") or raw.get("mentioned_at") or raw.get("created_at") or raw.get("updated_at"))
    created_at = _coerce_datetime(raw.get("created_at") or raw.get("timestamp") or raw.get("date"))
    updated_at = _coerce_datetime(raw.get("updated_at") or raw.get("mentioned_at") or raw.get("timestamp") or raw.get("date"))
    return {
        "id": fact_id,
        "content": content,
        "context": context,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "source_peer": _source_peer(metadata, tags, content),
        "entities": entities,
        "metadata": metadata,
        "tags": tags,
        "document_id": str(raw.get("document_id")) if raw.get("document_id") else None,
        "fact_type": str(raw.get("fact_type") or raw.get("type")) if (raw.get("fact_type") or raw.get("type")) else None,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "stale_reasons": [],
        "soft_deleted": False,
    }


def _list_raw_hindsight(search_query: str | None = None, max_items: int = 1000) -> tuple[list[dict[str, Any]], int | None]:
    bank = quote(_hindsight_bank_id(), safe="")
    items: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    while len(items) < max_items:
        limit = min(200, max_items - len(items))
        payload = _hindsight_get_json(
            f"/v1/default/banks/{bank}/memories/list",
            {"q": search_query or None, "limit": limit, "offset": offset},
        )
        batch = payload.get("items") if isinstance(payload, dict) else []
        if isinstance(payload, dict) and isinstance(payload.get("total"), int):
            total = int(payload["total"])
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            if isinstance(row, dict):
                items.append(row)
        if len(batch) < limit:
            break
        offset += len(batch)
    return items, total


def _detect_stale(facts: list[dict[str, Any]]) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = defaultdict(list)
    active = [fact for fact in facts if not fact.get("soft_deleted")]
    for idx, left in enumerate(active):
        left_text = str(left.get("content") or "").lower().strip()
        if len(left_text) < 16:
            continue
        for right in active[idx + 1:]:
            if str(left.get("context") or "").lower() != str(right.get("context") or "").lower():
                continue
            ratio = SequenceMatcher(None, left_text, str(right.get("content") or "").lower().strip()).ratio()
            if ratio >= 0.9:
                reasons[str(left["id"])].append("Potential duplicate in same context")
                reasons[str(right["id"])].append("Potential duplicate in same context")
    migration_terms = ("honcho", "honcho-buffered", "dim-237", "migration")
    for fact in active:
        text = str(fact.get("content") or "").lower()
        if any(token in text for token in migration_terms):
            reasons[str(fact["id"])].append("References migration-era system details (review for obsolescence)")
        if any("honcho" in str(entity).lower() for entity in fact.get("entities") or []):
            reasons[str(fact["id"])].append("Entity references removed/legacy Honcho component")
    return {key: list(dict.fromkeys(value)) for key, value in reasons.items()}


def _filtered_hindsight_facts(
    *,
    q: str | None = None,
    context: str | None = None,
    source: str = "all",
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    stale_only: bool = False,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    raw_items, upstream_total = _list_raw_hindsight(search_query=q, max_items=max(1000, offset + limit + 250))
    facts = [_normalize_fact(row) for row in raw_items]
    stale = _detect_stale(facts)
    for fact in facts:
        fact["stale_reasons"] = stale.get(str(fact["id"]), [])
    filtered = [fact for fact in facts if not fact.get("soft_deleted")]
    if source in {"pc", "pi"}:
        filtered = [fact for fact in filtered if fact.get("source_peer") == source]
    if context:
        needle = context.strip().lower()
        filtered = [fact for fact in filtered if str(fact.get("context") or "").lower() == needle]
    if from_ts:
        filtered = [fact for fact in filtered if (dt := _coerce_datetime(fact.get("timestamp"))) and dt >= from_ts]
    if to_ts:
        filtered = [fact for fact in filtered if (dt := _coerce_datetime(fact.get("timestamp"))) and dt <= to_ts]
    if stale_only:
        filtered = [fact for fact in filtered if fact.get("stale_reasons")]
    filtered.sort(key=lambda fact: _coerce_datetime(fact.get("timestamp")) or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=sort != "oldest")
    total = len(filtered)
    page = filtered[offset: offset + limit]
    return {"items": page, "total": total, "upstream_total": upstream_total, "limit": limit, "offset": offset, "has_more": offset + len(page) < total}


@router.get("/hindsight/health")
async def hindsight_health() -> dict[str, Any]:
    payload = {"backend": "hindsight", "ok": False, "bank_id": _hindsight_bank_id(), "base_url": _hindsight_base_url(), "error": None}
    try:
        _hindsight_get_json("/health", timeout=5)
        payload["ok"] = True
    except Exception as exc:
        payload["error"] = str(exc)
    return payload


@router.get("/hindsight/stats")
async def hindsight_stats(source: str = "all") -> dict[str, Any]:
    try:
        data = _filtered_hindsight_facts(source=source, limit=1000, offset=0)
    except Exception as exc:
        return {
            "total_facts": 0,
            "upstream_total": None,
            "facts_per_context": {},
            "facts_per_source": {},
            "storage_estimate_bytes": 0,
            "last_sync_timestamp": None,
            "stale_candidates": 0,
            "error": str(exc),
        }
    per_context: dict[str, int] = defaultdict(int)
    per_source: dict[str, int] = defaultdict(int)
    storage = 0
    stale_count = 0
    last_pi_sync: datetime | None = None
    for fact in data["items"]:
        per_context[str(fact.get("context") or "uncategorized")] += 1
        per_source[str(fact.get("source_peer") or "unknown")] += 1
        storage += len(str(fact.get("content") or "").encode("utf-8"))
        stale_count += 1 if fact.get("stale_reasons") else 0
        if fact.get("source_peer") == "pi":
            dt = _coerce_datetime(fact.get("timestamp"))
            if dt and (last_pi_sync is None or dt > last_pi_sync):
                last_pi_sync = dt
    return {
        "total_facts": data["total"],
        "upstream_total": data.get("upstream_total"),
        "facts_per_context": dict(sorted(per_context.items())),
        "facts_per_source": dict(sorted(per_source.items())),
        "storage_estimate_bytes": storage,
        "last_sync_timestamp": last_pi_sync.isoformat() if last_pi_sync else None,
        "stale_candidates": stale_count,
    }


@router.get("/hindsight/facts")
async def hindsight_facts(
    q: str | None = None,
    context: str | None = None,
    source: str = "all",
    from_date: date | None = None,
    to_date: date | None = None,
    stale_only: bool = False,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(250, limit))
    offset = max(0, offset)
    try:
        return _filtered_hindsight_facts(
            q=q,
            context=context,
            source=source,
            from_ts=_date_to_utc_start(from_date),
            to_ts=_date_to_utc_end(to_date),
            stale_only=stale_only,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        return {"items": [], "total": 0, "upstream_total": None, "limit": limit, "offset": offset, "has_more": False, "error": str(exc)}


@router.get("/hindsight/search")
async def hindsight_search(
    q: str,
    source: str = "all",
    context: str | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    return await hindsight_facts(q=q, source=source, context=context, sort=sort, limit=limit, offset=offset)


@router.get("/hindsight/stale")
async def hindsight_stale(source: str = "all") -> dict[str, Any]:
    try:
        data = _filtered_hindsight_facts(source=source, stale_only=True, sort="newest", limit=100, offset=0)
        return {"items": data["items"], "total": data["total"]}
    except Exception as exc:
        return {"items": [], "total": 0, "error": str(exc)}


@router.get("/hindsight/facts/{fact_id}")
async def hindsight_fact_detail(fact_id: str) -> dict[str, Any]:
    # Hindsight's direct get route is not guaranteed across deployed versions, so
    # walk list results and match normalized IDs. Slow, but safe for an ops panel.
    raw_items, _ = _list_raw_hindsight(max_items=5000)
    for raw in raw_items:
        fact = _normalize_fact(raw)
        if fact["id"] == fact_id:
            fact["stale_reasons"] = _detect_stale([fact]).get(fact_id, [])
            return {"fact": fact, "audit_log": []}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' was not found")


# -----------------------------
# Provider Status
# -----------------------------

_PROVIDER_META: dict[str, dict[str, Any]] = {
    "openrouter": {"name": "OpenRouter", "env": ("OPENROUTER_API_KEY", "OPENAI_API_KEY"), "base_url": "https://openrouter.ai/api/v1"},
    "openai-codex": {"name": "OpenAI Codex", "env": ("OPENAI_API_KEY", "OPENAI_CODEX_API_KEY"), "base_url": "https://chatgpt.com/backend-api/codex"},
    "anthropic": {"name": "Anthropic", "env": ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"), "base_url": "https://api.anthropic.com"},
    "minimax": {"name": "MiniMax", "env": ("MINIMAX_API_KEY",), "base_url": "https://api.minimax.io/anthropic"},
    "minimax-cn": {"name": "MiniMax (China)", "env": ("MINIMAX_CN_API_KEY",), "base_url": "https://api.minimaxi.com/anthropic"},
    "kimi-coding": {"name": "Kimi / Moonshot", "env": ("KIMI_API_KEY",), "base_url": "https://api.moonshot.ai/v1"},
    "zai": {"name": "Z.AI / GLM", "env": ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"), "base_url": "https://api.z.ai/api/paas/v4"},
    "copilot": {"name": "GitHub Copilot", "env": ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"), "base_url": "https://api.githubcopilot.com"},
}

_PROVIDER_ALIASES = {
    "codex": "openai-codex",
    "openai_codex": "openai-codex",
    "openaicodex": "openai-codex",
    "kimi": "kimi-coding",
    "moonshot": "kimi-coding",
    "glm": "zai",
    "z.ai": "zai",
    "z-ai": "zai",
    "claude": "anthropic",
    "open-router": "openrouter",
}


def _safe_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merged_provider_env() -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in [Path.home() / ".hermes" / ".env", Path.home() / ".hindsight" / "profiles" / "hermes.env", Path.home() / "honcho" / ".env"]:
        merged.update(_read_env_file(path))
    merged.update({k: v for k, v in os.environ.items() if isinstance(v, str)})
    return merged


def _normalize_provider_id(provider: str | None, *, base_url: str | None = None, model: str | None = None) -> str | None:
    cleaned = (provider or "").strip().lower()
    if cleaned == "auto":
        cleaned = ""
    cleaned = _PROVIDER_ALIASES.get(cleaned, cleaned)
    if cleaned in _PROVIDER_META or cleaned.startswith("custom:"):
        return cleaned
    url = (base_url or "").lower()
    if "openrouter.ai" in url:
        return "openrouter"
    if "chatgpt.com/backend-api/codex" in url:
        return "openai-codex"
    if "anthropic.com" in url:
        return "anthropic"
    if "minimax" in url:
        return "minimax-cn" if "minimaxi" in url else "minimax"
    if "moonshot" in url or "kimi" in url:
        return "kimi-coding"
    if "z.ai" in url or "bigmodel" in url:
        return "zai"
    model_l = (model or "").lower()
    if model_l.startswith("gpt-") or model_l.startswith("o3") or model_l.startswith("o4"):
        return "openai-codex"
    if model_l.startswith("claude"):
        return "anthropic"
    if model_l.startswith("minimax"):
        return "minimax"
    return cleaned or None


def _read_auth_providers() -> dict[str, Any]:
    path = Path.home() / ".hermes" / "auth.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _discover_provider_flows() -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    env = _merged_provider_env()
    config = _safe_yaml(Path.home() / ".hermes" / "config.yaml")
    flows: list[dict[str, Any]] = []
    model_cfg = config.get("model")
    provider = model = base_url = None
    if isinstance(model_cfg, dict):
        provider = str(model_cfg.get("provider") or "")
        model = str(model_cfg.get("default") or model_cfg.get("model") or model_cfg.get("name") or "")
        base_url = str(model_cfg.get("base_url") or "")
    elif isinstance(model_cfg, str):
        model = model_cfg
    provider_id = _normalize_provider_id(provider or env.get("HERMES_PROVIDER"), base_url=base_url or env.get("HERMES_BASE_URL"), model=model or env.get("HERMES_MODEL"))
    if provider_id:
        flows.append({"flow": "Hermes Main", "instance": "pc", "provider": provider_id, "model": model or env.get("HERMES_MODEL") or None})
    h_provider = _normalize_provider_id(env.get("HINDSIGHT_API_LLM_PROVIDER"), base_url=env.get("HINDSIGHT_API_LLM_BASE_URL"), model=env.get("HINDSIGHT_API_LLM_MODEL"))
    if h_provider:
        flows.append({"flow": "Hindsight Memory", "instance": "pc", "provider": h_provider, "model": env.get("HINDSIGHT_API_LLM_MODEL") or None})
    linear_backend = str(config.get("linear_backend") or env.get("HERMES_LINEAR_DEFAULT_BACKEND") or "").lower()
    if linear_backend == "codex":
        flows.append({"flow": "Linear Agents", "instance": "pc", "provider": "openai-codex", "model": env.get("HERMES_CODEX_MODEL") or "gpt-5.5"})
    elif provider_id:
        flows.append({"flow": "Linear Agents", "instance": "pc", "provider": provider_id, "model": model or None})
    return flows, env, _read_auth_providers()


def _provider_has_auth(provider_id: str, env: dict[str, str], auth: dict[str, Any]) -> tuple[bool, str | None]:
    meta = _PROVIDER_META.get(provider_id, {})
    for key in meta.get("env", ()):
        if (env.get(key) or "").strip():
            return True, "env"
    pool = auth.get("credential_pool")
    if isinstance(pool, dict) and isinstance(pool.get(provider_id), list) and pool.get(provider_id):
        return True, "credential_pool"
    providers = auth.get("providers")
    if isinstance(providers, dict) and isinstance(providers.get(provider_id), dict):
        state = providers.get(provider_id) or {}
        if state.get("tokens") or state.get("access_token"):
            return True, "oauth"
    if provider_id == "openai-codex":
        codex = (providers or {}).get("openai-codex") if isinstance(providers, dict) else None
        if isinstance(codex, dict) and codex.get("tokens"):
            return True, "oauth"
    return False, None


@router.get("/providers/status")
async def providers_status(instance: str = "all") -> dict[str, Any]:
    flows, env, auth = _discover_provider_flows()
    provider_ids = {flow["provider"] for flow in flows}
    for provider_id, meta in _PROVIDER_META.items():
        if any((env.get(key) or "").strip() for key in meta.get("env", ())) :
            provider_ids.add(provider_id)
    pool = auth.get("credential_pool")
    if isinstance(pool, dict):
        provider_ids.update(str(key) for key, value in pool.items() if isinstance(value, list) and value)
    providers: list[dict[str, Any]] = []
    for provider_id in sorted(provider_ids):
        provider_flows = [flow for flow in flows if flow["provider"] == provider_id and (instance == "all" or flow["instance"] == instance)]
        if instance != "all" and not provider_flows:
            continue
        has_auth, key_source = _provider_has_auth(provider_id, env, auth)
        status = "active" if has_auth else ("misconfigured" if provider_flows else "unknown")
        if status == "unknown":
            continue
        meta = _PROVIDER_META.get(provider_id, {})
        providers.append({
            "provider": provider_id,
            "name": meta.get("name") or (f"Custom ({provider_id.split(':', 1)[1]})" if provider_id.startswith("custom:") else provider_id),
            "base_url": meta.get("base_url"),
            "current_model": next((flow.get("model") for flow in provider_flows if flow.get("model")), None),
            "status": status,
            "status_reason": "At least one credential source is available." if has_auth else "Configured in a flow, but no credentials were found.",
            "recovery_eta_seconds": None,
            "recovery_eta": None,
            "primary_flows": [{"flow": flow["flow"], "instance": flow["instance"], "model": flow.get("model")} for flow in provider_flows],
            "last_error": None,
            "key_source": key_source,
        })
    summary = {"total": len(providers), "active": 0, "off_limits": 0, "exhausted": 0, "misconfigured": 0, "unknown": 0}
    for provider in providers:
        key = "off_limits" if provider["status"] == "off-limits" else provider["status"]
        if key in summary:
            summary[key] += 1
    return {"instance": instance, "generated_at": _utc_now(), "providers": providers, "summary": summary}


# -----------------------------
# Memory Ingest + Digest
# -----------------------------

def _memory_ingest_db_path() -> Path:
    raw = _setting("MEMORY_INGEST_DB") or _setting("HERMES_MEMORY_INGEST_DB")
    return Path(raw).expanduser() if raw else Path.home() / ".hermes" / "memory" / "ingest.db"


def _sqlite_rows(path: Path, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


@router.get("/memory-ingest/health")
async def memory_ingest_health() -> dict[str, Any]:
    db = _memory_ingest_db_path()
    ok = db.exists()
    payload = {"backend": "hindsight", "ok": ok, "db_path": str(db), "error": None if ok else "ingest database not found"}
    if ok:
        try:
            rows = _sqlite_rows(db, "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ingest_%' ORDER BY name")
            payload["tables"] = [row["name"] for row in rows]
        except Exception as exc:
            payload["ok"] = False
            payload["error"] = str(exc)
    return payload


@router.get("/memory-ingest/metrics")
async def memory_ingest_metrics() -> dict[str, Any]:
    db = _memory_ingest_db_path()
    if not db.exists():
        return {"checkpoints": [], "totals": {}, "lag_by_source": {}, "dead_letters": 0, "last_dead_letter_at": None, "db_path": str(db), "error": "ingest database not found"}
    try:
        checkpoints = _sqlite_rows(db, "SELECT source_peer, highest_contiguous_seq, updated_at FROM ingest_checkpoints ORDER BY source_peer")
        totals = {row["status"]: int(row["count"]) for row in _sqlite_rows(db, "SELECT status, COUNT(*) AS count FROM ingest_attempts GROUP BY status")}
        max_rows = _sqlite_rows(db, "SELECT source_peer, MAX(seq) AS max_seq FROM ingest_events GROUP BY source_peer")
        max_by_source = {row["source_peer"]: int(row["max_seq"] or 0) for row in max_rows}
        lag_by_source = {row["source_peer"]: max(0, max_by_source.get(row["source_peer"], row["highest_contiguous_seq"]) - int(row["highest_contiguous_seq"] or 0)) for row in checkpoints}
        dead_count = _sqlite_rows(db, "SELECT COUNT(*) AS count FROM ingest_dead_letters")
        last_dead = _sqlite_rows(db, "SELECT created_at FROM ingest_dead_letters ORDER BY id DESC LIMIT 1")
        recent = _sqlite_rows(db, "SELECT source_peer, event_id, seq, status, reason, created_at FROM ingest_attempts ORDER BY id DESC LIMIT 12")
        return {"checkpoints": checkpoints, "totals": totals, "lag_by_source": lag_by_source, "dead_letters": int(dead_count[0]["count"] if dead_count else 0), "last_dead_letter_at": last_dead[0]["created_at"] if last_dead else None, "recent_attempts": recent, "db_path": str(db)}
    except Exception as exc:
        return {"checkpoints": [], "totals": {}, "lag_by_source": {}, "dead_letters": 0, "last_dead_letter_at": None, "db_path": str(db), "error": str(exc)}


@router.get("/memory-ingest/dead-letter")
async def memory_ingest_dead_letter(limit: int = 50) -> dict[str, Any]:
    db = _memory_ingest_db_path()
    limit = max(1, min(500, limit))
    if not db.exists():
        return {"entries": [], "error": "ingest database not found"}
    try:
        rows = _sqlite_rows(db, "SELECT id, source_peer, event_id, seq, reason, details, payload_json, created_at FROM ingest_dead_letters ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            try:
                row["payload"] = json.loads(row.pop("payload_json") or "null")
            except Exception:
                row["payload"] = row.pop("payload_json", None)
        return {"entries": rows}
    except Exception as exc:
        return {"entries": [], "error": str(exc)}


def _digest_storage_file() -> Path:
    raw = _setting("DIGEST_STORAGE_PATH")
    base = Path(raw).expanduser() if raw else Path.home() / ".hermes" / "mission-control" / "digests"
    return base / "entries.jsonl"


def _parse_digest_dt(value: Any) -> datetime | None:
    return _coerce_datetime(value)


def _digest_entry_from_raw(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        now = _utc_now()
        ingested = _parse_digest_dt(raw.get("ingested_at")) or _parse_digest_dt(raw.get("created_at")) or datetime.now(timezone.utc)
        updated = _parse_digest_dt(raw.get("updated_at")) or ingested
        replicated = _parse_digest_dt(raw.get("replicated_at"))
        return {
            "id": str(raw.get("id") or ""),
            "title": str(raw.get("title") or "Untitled digest"),
            "summary": str(raw.get("summary") or ""),
            "content": raw.get("content"),
            "source": str(raw.get("source") or "custom"),
            "source_url": raw.get("source_url"),
            "source_instance": str(raw.get("source_instance") or "pc"),
            "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else [],
            "ingested_at": ingested.isoformat(),
            "updated_at": updated.isoformat(),
            "replicated_at": replicated.isoformat() if replicated else None,
            "replication_seq": raw.get("replication_seq"),
            "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        }
    except Exception:
        return None


def _load_digest_entries(instance: str = "all", source: str | None = None, days: int | None = None) -> list[dict[str, Any]]:
    path = _digest_storage_file()
    entries: list[dict[str, Any]] = []
    threshold = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            entry = _digest_entry_from_raw(raw)
            if not entry:
                continue
            if instance in {"pc", "pi"} and entry.get("source_instance") != instance:
                continue
            if source and entry.get("source") != source:
                continue
            dt = _parse_digest_dt(entry.get("ingested_at"))
            if threshold and dt and dt < threshold:
                continue
            entries.append(entry)
    entries.sort(key=lambda item: _parse_digest_dt(item.get("ingested_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return entries


def _digest_stats_from(entries: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    by_source: dict[str, int] = defaultdict(int)
    by_instance: dict[str, int] = defaultdict(int)
    lags: list[float] = []
    for entry in entries:
        by_source[str(entry.get("source") or "custom")] += 1
        by_instance[str(entry.get("source_instance") or "pc")] += 1
        ing = _parse_digest_dt(entry.get("ingested_at"))
        rep = _parse_digest_dt(entry.get("replicated_at"))
        if ing and rep:
            lags.append((rep - ing).total_seconds())
    return {"total_entries": len(entries), "by_source": dict(by_source), "by_instance": dict(by_instance), "last_24h": sum(1 for e in entries if (_parse_digest_dt(e.get("ingested_at")) or now) > now - timedelta(hours=24)), "last_7d": sum(1 for e in entries if (_parse_digest_dt(e.get("ingested_at")) or now) > now - timedelta(days=7)), "replication_lag_seconds": (sum(lags) / len(lags)) if lags else None}


@router.get("/digest")
async def digest_list(instance: str = "all", source: str | None = None, page: int = 1, page_size: int = 50, days: int | None = 30) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(250, page_size))
    entries = _load_digest_entries(instance=instance, source=source, days=days)
    start = (page - 1) * page_size
    page_entries = entries[start:start + page_size]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in page_entries:
        dt = _parse_digest_dt(entry.get("ingested_at"))
        grouped[dt.strftime("%Y-%m-%d") if dt else "unknown"].append(entry)
    groups = [{"date": key, "entries": value, "count": len(value)} for key, value in sorted(grouped.items(), reverse=True)]
    return {"entries": page_entries, "groups": groups, "total": len(entries), "page": page, "page_size": page_size, "has_more": start + len(page_entries) < len(entries)}


@router.get("/digest/stats")
async def digest_stats(instance: str = "all") -> dict[str, Any]:
    return _digest_stats_from(_load_digest_entries(instance=instance, days=None))


@router.get("/digest/{entry_id}")
async def digest_detail(entry_id: str) -> dict[str, Any]:
    from fastapi import HTTPException
    for entry in _load_digest_entries(instance="all", days=None):
        if entry.get("id") == entry_id:
            output_file = entry.get("metadata", {}).get("output_file") if isinstance(entry.get("metadata"), dict) else None
            if output_file and not entry.get("content"):
                try:
                    text = Path(str(output_file)).expanduser().read_text(encoding="utf-8", errors="ignore")
                    parts = text.split("## Response", 1)
                    entry["content"] = (parts[1] if len(parts) > 1 else text).strip()
                except Exception:
                    pass
            return {"entry": entry}
    raise HTTPException(status_code=404, detail=f"Digest entry {entry_id} not found")


# -----------------------------
# Linear Harness + Operations
# -----------------------------

def _hermes_home() -> Path:
    return Path(_setting("HERMES_HOME") or str(Path.home() / ".hermes")).expanduser()


def _worktree_root() -> Path:
    return Path(_setting("WORKTREE_ROOT") or "/tmp/hermes-linear-workers").expanduser()


def _gateway_config() -> dict[str, Any]:
    path = Path(_setting("GATEWAY_CONFIG_PATH") or str(_hermes_home() / "gateway-config.yaml")).expanduser()
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _webhook_url() -> str:
    explicit = _setting("LINEAR_WEBHOOK_URL")
    if explicit:
        return explicit
    base = str(_gateway_config().get("base_url") or "").rstrip("/")
    if base:
        return f"{base}/webhooks/linear_agent"
    return ""


def _log_recent_counts() -> tuple[int, int, str | None]:
    log_dir = _hermes_home() / "logs"
    events = 0
    errors = 0
    last: str | None = None
    if not log_dir.exists():
        return events, errors, last
    for log_file in list(log_dir.glob("gateway*.log")) + list(log_dir.glob("linear*.log")) + [log_dir / "webhook.log", log_dir / "linear_webhook.log"]:
        if not log_file.exists():
            continue
        try:
            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()[-1000:]
        except Exception:
            continue
        for line in lines:
            lower = line.lower()
            if "linear" in lower or "webhook" in lower:
                events += 1
                m = re.search(r"(\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+)", line)
                if m:
                    last = m.group(1)
            if "error" in lower or "traceback" in lower:
                errors += 1
    return events, errors, last


def _session_from_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    sid = str(payload.get("session_id") or path.stem.replace("session_", ""))
    platform = str(payload.get("platform") or "cli")
    started = payload.get("session_start") or payload.get("created_at") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    updated = payload.get("last_updated") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    summary = ""
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, dict):
            summary = str(last_msg.get("content") or "")[:240]
    return {"id": sid, "issue_id": platform.upper(), "issue_title": str(payload.get("display_name") or platform), "backend": str(payload.get("model") or payload.get("provider") or "unknown"), "status": "recent", "started_at": started, "last_updated_at": updated, "worktree": str(path), "platform": platform, "message_count": len(messages) if messages else payload.get("message_count"), "source": "archive", "summary": summary}


def _active_sessions(limit: int = 8) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    root = _worktree_root()
    if root.exists():
        for worktree in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
            m = re.match(r"([a-zA-Z]+[_-]?\d+)-(.+)", worktree.name)
            if not m:
                continue
            issue_id = m.group(1).upper()
            metadata: dict[str, Any] = {}
            if (worktree / "metadata.json").exists():
                try:
                    metadata = json.loads((worktree / "metadata.json").read_text(encoding="utf-8"))
                except Exception:
                    metadata = {}
            pid = None
            status = "unknown"
            if (worktree / "agent.pid").exists():
                try:
                    pid = int((worktree / "agent.pid").read_text().strip())
                    status = "running" if _pid_running(pid) else "completed"
                except Exception:
                    pass
            sessions.append({"id": f"{issue_id.lower()}-{m.group(2)}", "issue_id": issue_id, "issue_title": metadata.get("issue_title") or f"Issue {issue_id}", "backend": metadata.get("backend") or _setting("LINEAR_DEFAULT_BACKEND", "codex"), "status": status, "started_at": metadata.get("started_at") or datetime.fromtimestamp(worktree.stat().st_ctime, tz=timezone.utc).isoformat(), "last_updated_at": datetime.fromtimestamp(worktree.stat().st_mtime, tz=timezone.utc).isoformat(), "worktree": str(worktree), "platform": metadata.get("platform") or "linear-harness", "message_count": metadata.get("message_count"), "source": "live", "summary": str(metadata.get("summary") or metadata.get("prompt") or "")[:240], "pid": pid})
            if len(sessions) >= limit:
                return sessions
    sess_dir = _hermes_home() / "sessions"
    if sess_dir.exists():
        for path in sorted(sess_dir.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name.startswith("session_cron_"):
                continue
            item = _session_from_file(path)
            if item:
                sessions.append(item)
            if len(sessions) >= limit:
                break
    return sessions


def _workers() -> list[dict[str, Any]]:
    workers: list[dict[str, Any]] = []
    for session in _active_sessions(limit=50):
        pid = session.get("pid")
        if not isinstance(pid, int) or not _pid_running(pid):
            continue
        workers.append({"session_id": session["id"], "pid": pid, "backend": session.get("backend") or "unknown", "issue_id": session.get("issue_id") or "", "runtime_seconds": None, "log_file": str(Path(session.get("worktree", "")) / "agent.log")})
    return workers


@router.get("/harness/status")
async def harness_status() -> dict[str, Any]:
    events, errors, last = _log_recent_counts()
    webhook_status = "healthy" if events and errors == 0 else ("degraded" if errors else "unknown")
    return {"webhook": {"url": _webhook_url(), "status": webhook_status, "last_event_at": last, "events_24h": events, "errors_24h": errors}, "config": {"default_backend": _setting("LINEAR_DEFAULT_BACKEND", "codex"), "worktree_root": str(_worktree_root())}}


@router.get("/harness/sessions")
async def harness_sessions() -> dict[str, Any]:
    return {"sessions": _active_sessions()}


@router.get("/harness/workers")
async def harness_workers() -> dict[str, Any]:
    return {"workers": _workers()}


@router.get("/operations/recent")
async def operations_recent(limit: int = 40) -> dict[str, Any]:
    limit = max(1, min(200, limit))
    log_dir = _hermes_home() / "logs"
    events: list[dict[str, Any]] = []
    candidates = [log_dir / "agent.log", log_dir / "gateway.log", log_dir / "errors.log", log_dir / "webhook.log", log_dir / "linear_webhook.log"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
        except Exception:
            continue
        for line in lines:
            lower = line.lower()
            if not any(token in lower for token in ("error", "traceback", "tool", "webhook", "linear", "session", "started", "completed")):
                continue
            category = "error" if "error" in lower or "traceback" in lower else ("tool_call" if "tool" in lower else ("completion" if "completed" in lower else "other"))
            m = re.search(r"(\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+)", line)
            events.append({"timestamp": m.group(1) if m else datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(), "type": category, "source": path.name, "content": line[-500:], "session_id": None, "status": None})
    events = events[-limit:]
    return {"events": events, "total": len(events)}
