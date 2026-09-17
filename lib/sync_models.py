#!/usr/bin/env python3
"""Refresh Claude Code /model picker from OpenRouter's live free catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from providers import Provider, get_provider, load_active_id, usable_aihubmix, usable_zenmux

CATALOG_URL = "https://openrouter.ai/api/v1/models"
KEY_URL = "https://openrouter.ai/api/v1/key"
DEFAULT_CONFIG_DIR = Path.home() / ".claude-openrouter"
STALE_AFTER = timedelta(hours=24)
PROBE_WORKERS = 8

# Hints only. Missing ids are skipped so a stale list cannot break sync.
SONNET_PREFS = [
    "nex-agi/nex-n2.5-pro:free",
    "poolside/laguna-s-2.1:free",
    "stealth/union-alpha",
    "cohere/north-mini-code:free",
    "openrouter/free",
]
OPUS_PREFS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "thinkingmachines/inkling:free",
    "nex-agi/nex-n2.5-pro:free",
    "openrouter/free",
]
FABLE_PREFS = [
    "thinkingmachines/inkling:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nex-agi/nex-n2.5-pro:free",
]
HAIKU_PREFS = [
    "nvidia/nemotron-3.5-lightning:free",
    "poolside/laguna-xs-2.1:free",
    "nex-agi/nex-n2.5-mini:free",
    "liquid/lfm-2.5-2.6b:free",
]
SUBAGENT_PREFS = [
    "poolside/laguna-xs-2.1:free",
    "nex-agi/nex-n2.5-mini:free",
    "liquid/lfm-2.5-2.6b:free",
    "openrouter/free",
]
PIN_FIRST = [
    "openrouter/free",
    "stealth/union-alpha",
    "nex-agi/nex-n2.5-pro:free",
    "nex-agi/nex-n2.5-mini:free",
    "poolside/laguna-s-2.1:free",
    "poolside/laguna-xs-2.1:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
]
FREE_ROUTER = "openrouter/free"
FALLBACK_CHAIN_LIMIT = 3


def package_version() -> str:
    path = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        return path.read_text().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def user_agent() -> str:
    return f"claude-or/{package_version()}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_zero(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return str(value) in {"0", "0.0", "0.00"}


def is_free_model(model_id: str, pricing: dict[str, Any]) -> bool:
    return (
        model_id.endswith(":free")
        or model_id == "openrouter/free"
        or (is_zero(pricing.get("prompt")) and is_zero(pricing.get("completion")))
    )


def is_stealth(model_id: str, name: str, description: str = "") -> bool:
    blob = f"{model_id} {name} {description}".lower()
    return model_id.startswith("stealth/") or "stealth model" in blob or "anonymous" in blob


def ui_lang() -> str:
    raw = os.environ.get("CLAUDE_OR_LANG") or os.environ.get("LANG") or ""
    return "zh" if raw.lower().startswith("zh") else "en"


def stealth_prefix() -> str:
    return "匿名 · " if ui_lang() == "zh" else "Stealth · "


def down_prefix() -> str:
    return "挂了 · " if ui_lang() == "zh" else "Down · "


def picker_label(item: dict[str, Any]) -> str:
    name = str(item.get("name") or item["id"])
    if item.get("stealth"):
        name = f"{stealth_prefix()}{name}"
    if item.get("health") == "down":
        return f"{down_prefix()}{name}"
    return name


def ctx_label(tokens: int) -> str:
    if tokens >= 1_000_000:
        return "1M ctx"
    if tokens >= 1000:
        thousands = tokens / 1000
        if thousands >= 100:
            return f"{int(round(thousands))}k ctx"
        return f"{thousands:.0f}k ctx" if thousands.is_integer() else f"{thousands:.1f}k ctx"
    return f"{tokens} ctx"


def picker_description(item: dict[str, Any]) -> str:
    bits = [item["id"], ctx_label(int(item.get("context_length") or 0))]
    if item.get("stealth"):
        bits.append("stealth / no :free suffix")
    health = item.get("health")
    if health and health != "unknown":
        bits.append(health)
    reason = item.get("probe_reason")
    if reason and health == "down":
        bits.append(str(reason))
    return " · ".join(bits)


def skip_reason(model: dict[str, Any]) -> str | None:
    architecture = model.get("architecture") or {}
    outputs = architecture.get("output_modalities") or []
    inputs = architecture.get("input_modalities") or []
    params = model.get("supported_parameters") or []
    if "audio" in outputs:
        return "audio output"
    if "text" not in outputs:
        return f"non-text output ({','.join(outputs) or 'unknown'})"
    if "text" not in inputs:
        return "no text input"
    if "tools" not in params:
        return "no tool calling"
    return None


def usable_free_chat_models(
    catalog: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    usable: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for model in catalog:
        model_id = str(model.get("id") or "")
        pricing = model.get("pricing") or {}
        if not model_id or not is_free_model(model_id, pricing):
            continue
        reason = skip_reason(model)
        display_name = str(model.get("name") or model_id)
        if reason:
            skipped.append({"id": model_id, "reason": reason, "name": display_name})
            continue
        architecture = model.get("architecture") or {}
        usable.append(
            {
                "id": model_id,
                "name": display_name,
                "stealth": is_stealth(model_id, display_name, str(model.get("description") or "")),
                "context_length": model.get("context_length") or 0,
                "modality": architecture.get("modality"),
                "inputs": architecture.get("input_modalities") or [],
                "outputs": architecture.get("output_modalities") or [],
                "tools": True,
            }
        )

    by_id = {item["id"]: item for item in usable}
    ordered: list[dict[str, Any]] = []
    for pin in PIN_FIRST:
        if pin in by_id:
            ordered.append(by_id.pop(pin))
    stealth_rest = sorted(
        (item for item in by_id.values() if item.get("stealth")),
        key=lambda item: (-int(item["context_length"] or 0), item["id"]),
    )
    for item in stealth_rest:
        ordered.append(item)
        by_id.pop(item["id"], None)
    ordered.extend(sorted(by_id.values(), key=lambda item: (-int(item["context_length"] or 0), item["id"])))
    return ordered, skipped


def usable_for_provider(provider: Provider, catalog: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if provider.id == "aihubmix":
        return usable_aihubmix(catalog)
    if provider.id == "zenmux":
        return usable_zenmux(catalog)
    return usable_free_chat_models(catalog)


def pick(prefs: list[str], available: set[str], fallback: str) -> str:
    for model_id in prefs:
        if model_id in available:
            return model_id
    return fallback


def annotate_health(usable: list[dict[str, Any]], probe_results: dict[str, dict[str, str]] | None) -> list[dict[str, Any]]:
    for item in usable:
        info = (probe_results or {}).get(item["id"]) or {}
        item["health"] = info.get("health") or "unknown"
        item["probe_reason"] = info.get("reason") or ""
    return usable


def order_by_health(usable: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {"up": [], "unknown": [], "down": []}
    for item in usable:
        health = item.get("health") or "unknown"
        groups.setdefault(health if health in groups else "unknown", []).append(item)
    return groups["up"] + groups["unknown"] + groups["down"]


def pick_healthy(prefs: list[str], usable: list[dict[str, Any]], fallback: str) -> str:
    buckets: dict[str, set[str]] = {"up": set(), "unknown": set(), "down": set()}
    for item in usable:
        buckets.setdefault(item.get("health") or "unknown", set()).add(item["id"])
    for health in ("up", "unknown", "down"):
        available = buckets.get(health) or set()
        if available:
            return pick(prefs, available, next((item["id"] for item in usable if item["id"] in available), fallback))
    return fallback


def pick_fallback_chain(
    usable: list[dict[str, Any]],
    primary: str,
    *,
    limit: int = FALLBACK_CHAIN_LIMIT,
) -> list[str]:
    """Claude Code `fallbackModel` is an ordered array of at most three IDs, never the primary."""
    ids: list[str] = []
    seen: set[str] = set()
    for item in usable:
        model_id = str(item.get("id") or "")
        if not model_id or model_id == primary or model_id in seen:
            continue
        seen.add(model_id)
        ids.append(model_id)
    router = next((item for item in usable if item.get("id") == FREE_ROUTER), None)
    if (
        router
        and router["id"] != primary
        and router.get("health") != "down"
        and FREE_ROUTER in ids
    ):
        ids.remove(FREE_ROUTER)
        ids.insert(0, FREE_ROUTER)
    return ids[:limit]


def set_fallback_model(settings: dict[str, Any], usable: list[dict[str, Any]], primary: str) -> list[str]:
    chain = pick_fallback_chain(usable, primary)
    if chain:
        settings["fallbackModel"] = chain
    else:
        settings.pop("fallbackModel", None)
    return chain


def endpoints_url(model_id: str) -> str:
    return f"https://openrouter.ai/api/v1/models/{urllib.parse.quote(model_id, safe='/')}/endpoints"


def classify_endpoints(model_id: str, payload: Any, error: str | None = None) -> dict[str, str]:
    if model_id == "openrouter/free":
        data = payload.get("data") if isinstance(payload, dict) else payload
        endpoints = data.get("endpoints") if isinstance(data, dict) else None
        if not endpoints:
            return {"health": "up", "reason": "free router"}
    if error and payload is None:
        return {"health": "unknown", "reason": error}
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, dict):
        return {"health": "unknown", "reason": error or "invalid endpoints payload"}
    endpoints = data.get("endpoints") or []
    if not endpoints:
        return {"health": "down", "reason": "no endpoints"}
    healthy = [item for item in endpoints if int(item.get("status") or 0) == 0]
    if healthy:
        return {"health": "up", "reason": "status 0"}
    statuses = sorted({int(item.get("status") or 0) for item in endpoints})
    return {"health": "down", "reason": f"endpoint status {statuses}"}


def http_json(url: str, *, timeout: float = 15, headers: dict[str, str] | None = None) -> tuple[Any, str | None]:
    request_headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — network errors become probe/quota unknown
        return None, str(exc)


def _auth_headers(api_key: str | None) -> dict[str, str] | None:
    if not api_key:
        return None
    return {"Authorization": f"Bearer {api_key}"}


def fetch_catalog(url: str = CATALOG_URL, api_key: str | None = None) -> list[dict[str, Any]]:
    payload, error = http_json(url, timeout=30, headers=_auth_headers(api_key))
    if error or payload is None:
        raise RuntimeError(f"catalog {url} failed: {error or 'empty body'}")
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        raise RuntimeError(f"{url} did not return a model list")
    return data


def default_fetch_endpoints(model_id: str) -> tuple[Any, str | None]:
    return http_json(endpoints_url(model_id), timeout=12)


def probe_models(
    model_ids: list[str],
    fetch: Callable[[str], tuple[Any, str | None]] | None = None,
    workers: int = PROBE_WORKERS,
) -> dict[str, dict[str, str]]:
    fetch = fetch or default_fetch_endpoints
    results: dict[str, dict[str, str]] = {}
    if not model_ids:
        return results
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(model_ids)))) as pool:
        futures = {pool.submit(fetch, model_id): model_id for model_id in model_ids}
        for future in as_completed(futures):
            model_id = futures[future]
            try:
                payload, error = future.result()
            except Exception as exc:  # noqa: BLE001
                payload, error = None, str(exc)
            results[model_id] = classify_endpoints(model_id, payload, error=error)
    return results


def parse_key_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    daily = data.get("free_model_daily_requests") or {}
    remaining = daily.get("remaining")
    limit = daily.get("limit")
    used = daily.get("used")
    return {
        "is_free_tier": bool(data.get("is_free_tier")),
        "limit": int(limit) if limit is not None else None,
        "remaining": int(remaining) if remaining is not None else None,
        "used": int(used) if used is not None else None,
        "credits_remaining": data.get("limit_remaining"),
        "usage": data.get("usage"),
        "fetched_at": utcnow().isoformat(),
    }


def fetch_quota(api_key: str) -> dict[str, Any] | None:
    payload, error = http_json(KEY_URL, timeout=15, headers={"Authorization": f"Bearer {api_key}"})
    if error or payload is None:
        return None
    parsed = parse_key_payload(payload)
    parsed["error"] = None
    return parsed


def format_quota_line(
    quota: dict[str, Any] | None,
    *,
    provider: Provider | None = None,
    has_key: bool = False,
) -> str:
    if provider is not None and provider.quota != "openrouter-key":
        return f"quota:        {provider.name} does not expose a free-request counter"
    if not quota:
        if not has_key:
            return "quota:        unknown (no API key)"
        return "quota:        unknown (GET /api/v1/key failed)"
    remaining = quota.get("remaining")
    limit = quota.get("limit")
    used = quota.get("used")
    if remaining is None or limit is None:
        return "quota:        unknown (key endpoint missing free_model_daily_requests)"
    line = f"quota:        {remaining}/{limit} free req left today (UTC)"
    if used is not None:
        line += f", used {used}"
    if remaining <= 0:
        line += " — exhausted"
    elif remaining <= 10:
        line += " — low"
    return line


def quota_is_exhausted(quota: dict[str, Any] | None) -> bool:
    if not quota:
        return False
    remaining = quota.get("remaining")
    return remaining is not None and int(remaining) <= 0


def quota_exit_code(provider: Provider, api_key: str, quota: dict[str, Any] | None) -> int:
    if provider.quota != "openrouter-key":
        return 0
    if not api_key or quota is None:
        return 1
    if quota_is_exhausted(quota):
        return 2
    return 0


def is_stale(fetched_at: str | None, *, max_age: timedelta = STALE_AFTER) -> bool:
    if not fetched_at:
        return True
    try:
        timestamp = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return utcnow() - timestamp > max_age


ROLE_KEYS = ("model", "fable", "opus", "sonnet", "haiku", "subagent")
USER_DEFAULTS_NAME = "user-defaults.json"
ROLE_ENV = {
    "fable": "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "subagent": "CLAUDE_CODE_SUBAGENT_MODEL",
}


def load_settings(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def load_snapshot(config_dir: Path) -> dict[str, Any] | None:
    path = config_dir / "free-models.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def load_user_defaults(config_dir: Path) -> dict[str, str]:
    path = config_dir / USER_DEFAULTS_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: str(data[key]) for key in ROLE_KEYS if data.get(key)}


def save_user_defaults(config_dir: Path, chosen: dict[str, str]) -> dict[str, str]:
    merged = load_user_defaults(config_dir)
    for key, value in chosen.items():
        if key in ROLE_KEYS and value:
            merged[key] = str(value)
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / USER_DEFAULTS_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return merged


def merge_defaults(auto: dict[str, str], user: dict[str, str], available: set[str]) -> dict[str, str]:
    merged = dict(auto)
    for key, value in user.items():
        if key in auto and value in available:
            merged[key] = value
    return merged


def apply_defaults_to_settings(settings: dict[str, Any], defaults: dict[str, str]) -> dict[str, Any]:
    env = dict(settings.get("env") or {})
    if defaults.get("model"):
        settings["model"] = defaults["model"]
    for role, env_key in ROLE_ENV.items():
        if defaults.get(role):
            env[env_key] = defaults[role]
    if defaults.get("haiku"):
        env["ANTHROPIC_SMALL_FAST_MODEL"] = defaults["haiku"]
    settings["env"] = env
    return settings


def apply_user_defaults(config_dir: Path, chosen: dict[str, str]) -> dict[str, Any]:
    snapshot = load_snapshot(config_dir)
    if not snapshot:
        raise ValueError("no catalog — run sync first")
    ids = {str(item.get("id")) for item in snapshot.get("usable") or [] if item.get("id")}
    if not ids:
        raise ValueError("catalog has no usable models")
    unknown = [value for value in chosen.values() if value not in ids]
    if unknown:
        raise ValueError(f"not in this provider's free catalog: {unknown[0]}")
    user_defaults = save_user_defaults(config_dir, chosen)
    auto = {key: str((snapshot.get("defaults") or {}).get(key) or "") for key in ROLE_KEYS}
    defaults = merge_defaults(auto, user_defaults, ids)
    snapshot["defaults"] = defaults
    snapshot["user_defaults"] = user_defaults
    settings_path = config_dir / "settings.json"
    settings = load_settings(settings_path)
    apply_defaults_to_settings(settings, defaults)
    set_fallback_model(settings, snapshot.get("usable") or [], defaults["model"])
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    snapshot_path = config_dir / "free-models.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    return snapshot


def write_profile(
    config_dir: Path,
    catalog: list[dict[str, Any]],
    *,
    probe_results: dict[str, dict[str, str]] | None = None,
    quota: dict[str, Any] | None = None,
    provider: Provider | None = None,
) -> dict[str, Any]:
    provider = provider or get_provider("openrouter")
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_path = config_dir / "settings.json"
    snapshot_path = config_dir / "free-models.json"

    usable, skipped = usable_for_provider(provider, catalog)
    if not usable:
        raise RuntimeError(f"No usable free chat models found on {provider.name}.")

    annotate_health(usable, probe_results)
    usable = order_by_health(usable)
    ids = [item["id"] for item in usable]
    default_model = pick_healthy(list(provider.sonnet_prefs), usable, ids[0])
    auto = {
        "model": default_model,
        "fable": pick_healthy(list(provider.fable_prefs), usable, default_model),
        "opus": pick_healthy(list(provider.opus_prefs), usable, default_model),
        "sonnet": pick_healthy(list(provider.sonnet_prefs), usable, default_model),
        "haiku": pick_healthy(list(provider.haiku_prefs), usable, default_model),
        "subagent": pick_healthy(list(provider.haiku_prefs), usable, default_model),
    }
    user_defaults = load_user_defaults(config_dir)
    defaults = merge_defaults(auto, user_defaults, set(ids))
    snapshot = {
        "fetched_at": utcnow().isoformat(),
        "provider": provider.id,
        "usable": usable,
        "skipped": skipped,
        "defaults": defaults,
        "user_defaults": user_defaults,
        "probe": {
            "fetched_at": utcnow().isoformat() if probe_results is not None else None,
            "up": sum(1 for item in usable if item.get("health") == "up"),
            "down": sum(1 for item in usable if item.get("health") == "down"),
            "unknown": sum(1 for item in usable if item.get("health") not in {"up", "down"}),
            "results": probe_results or {},
        },
        "quota": quota,
    }
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")

    settings = load_settings(settings_path)
    env = dict(settings.get("env") or {})
    env.update(
        {
            "ANTHROPIC_BASE_URL": provider.base_url,
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
        }
    )
    settings["env"] = env
    apply_defaults_to_settings(settings, defaults)
    if ui_lang() == "zh" and "language" not in settings:
        settings["language"] = "chinese"
    set_fallback_model(settings, usable, defaults["model"])
    settings["enforceAvailableModels"] = True
    settings["availableModels"] = ids
    settings["modelPicker"] = {
        "replaceBuiltInOptions": True,
        "options": [
            {
                "model": item["id"],
                "label": picker_label(item),
                "description": picker_description(item),
            }
            for item in usable
        ],
    }
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return snapshot


def print_sync_report(snapshot: dict[str, Any], config_dir: Path) -> None:
    defaults = snapshot["defaults"]
    probe = snapshot.get("probe") or {}
    print(f"Wrote {len(snapshot['usable'])} free models to {config_dir / 'settings.json'}")
    print(f"Default: {defaults['model']}")
    print(
        "Roles: "
        f"fable={defaults['fable']} "
        f"opus={defaults['opus']} "
        f"sonnet={defaults['sonnet']} "
        f"haiku={defaults['haiku']}"
    )
    if probe.get("fetched_at"):
        print(f"Probe: {probe.get('up', 0)} up, {probe.get('down', 0)} down, {probe.get('unknown', 0)} unknown")
        down = [item for item in snapshot["usable"] if item.get("health") == "down"]
        for item in down:
            print(f"  down {item['id']} ({item.get('probe_reason') or 'unhealthy'})")
    skipped = snapshot.get("skipped") or []
    if skipped:
        print(f"Skipped {len(skipped)} free models that cannot drive Claude Code (no tools / non-text):")
        for item in skipped:
            print(f"  - {item['id']} ({item['reason']})")
    quota = snapshot.get("quota")
    if quota:
        print(format_quota_line(quota))


def print_status(
    config_dir: Path,
    quota: dict[str, Any] | None,
    provider: Provider | None = None,
    *,
    has_key: bool = False,
) -> None:
    settings_path = config_dir / "settings.json"
    snapshot = load_snapshot(config_dir)
    if provider:
        print("provider:   ", provider.id, f"({provider.name})")
        print("base url:   ", provider.base_url)
        print("keychain:   ", f"{provider.key_service}/{provider.key_account}")
    print("config dir: ", config_dir)
    print("settings:   ", settings_path)
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        env = settings.get("env") or {}
        print("default:    ", settings.get("model"))
        fallback = settings.get("fallbackModel")
        if isinstance(fallback, list):
            print("fallback:   ", ", ".join(str(item) for item in fallback) if fallback else "(none)")
        else:
            print("fallback:   ", fallback)
        print("picker:     ", len((settings.get("modelPicker") or {}).get("options") or []), "models")
        print("fable:      ", env.get("ANTHROPIC_DEFAULT_FABLE_MODEL"))
        print("opus:       ", env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"))
        print("sonnet:     ", env.get("ANTHROPIC_DEFAULT_SONNET_MODEL"))
        print("haiku:      ", env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"))
    else:
        print("settings.json missing — run: claude-or sync")
    if snapshot:
        probe = snapshot.get("probe") or {}
        if probe.get("fetched_at"):
            print(
                "probe:      ",
                f"{probe.get('up', 0)} up / {probe.get('down', 0)} down / {probe.get('unknown', 0)} unknown",
            )
        print("catalog:    ", "stale" if is_stale(snapshot.get("fetched_at")) else "fresh", snapshot.get("fetched_at"))
        quota = quota or snapshot.get("quota")
    print(format_quota_line(quota, provider=provider, has_key=has_key or bool(quota)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync OpenRouter free models into a Claude Code profile")
    parser.add_argument("--provider", help="openrouter | aihubmix | zenmux")
    parser.add_argument(
        "--config-dir",
        default=None,
    )
    parser.add_argument("--no-probe", action="store_true", help="Skip endpoint liveness checks")
    parser.add_argument("--print-status", action="store_true")
    parser.add_argument("--print-quota", action="store_true")
    parser.add_argument("--check-stale", action="store_true")
    args = parser.parse_args(argv)
    provider = get_provider(args.provider or load_active_id())
    config_dir = Path(args.config_dir or provider.config_dir()).expanduser()
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("CLAUDE_OR_API_KEY") or ""

    if args.check_stale:
        snapshot = load_snapshot(config_dir)
        fetched = snapshot.get("fetched_at") if snapshot else None
        print("stale" if is_stale(fetched) else "fresh")
        return 0

    quota = fetch_quota(api_key) if api_key and provider.quota == "openrouter-key" else None
    if args.print_quota:
        print(format_quota_line(quota, provider=provider, has_key=bool(api_key)))
        return quota_exit_code(provider, api_key, quota)
    if args.print_status:
        print_status(config_dir, quota, provider, has_key=bool(api_key))
        return quota_exit_code(provider, api_key, quota)

    catalog = fetch_catalog(provider.catalog_url, api_key=api_key or None)
    usable, _skipped = usable_for_provider(provider, catalog)
    probe_results = None
    if not args.no_probe and provider.probe == "openrouter-endpoints":
        probe_results = probe_models([item["id"] for item in usable])
    snapshot = write_profile(
        config_dir,
        catalog,
        probe_results=probe_results,
        quota=quota,
        provider=provider,
    )
    print_sync_report(snapshot, config_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
