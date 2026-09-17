#!/usr/bin/env python3
"""Refresh Claude Code /model picker from OpenRouter's live free catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATALOG_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_CONFIG_DIR = Path.home() / ".claude-openrouter"
USER_AGENT = "claude-or/0.1.0"

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


def picker_label(item: dict[str, Any]) -> str:
    name = str(item.get("name") or item["id"])
    if item.get("stealth"):
        return f"{stealth_prefix()}{name}"
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


def pick(prefs: list[str], available: set[str], fallback: str) -> str:
    for model_id in prefs:
        if model_id in available:
            return model_id
    return fallback


def fetch_catalog() -> list[dict[str, Any]]:
    request = urllib.request.Request(
        CATALOG_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        raise RuntimeError("OpenRouter /v1/models did not return a model list")
    return data


def load_settings(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def write_profile(config_dir: Path, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_path = config_dir / "settings.json"
    snapshot_path = config_dir / "free-models.json"

    usable, skipped = usable_free_chat_models(catalog)
    if not usable:
        raise RuntimeError("No usable free chat models found on OpenRouter.")

    ids = [item["id"] for item in usable]
    available = set(ids)
    default_model = pick(SONNET_PREFS, available, ids[0])
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "usable": usable,
        "skipped": skipped,
        "defaults": {
            "model": default_model,
            "fable": pick(FABLE_PREFS, available, default_model),
            "opus": pick(OPUS_PREFS, available, default_model),
            "sonnet": pick(SONNET_PREFS, available, default_model),
            "haiku": pick(HAIKU_PREFS, available, default_model),
            "subagent": pick(SUBAGENT_PREFS, available, default_model),
        },
    }
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")

    settings = load_settings(settings_path)
    env = dict(settings.get("env") or {})
    env.update(
        {
            "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
            "ANTHROPIC_DEFAULT_FABLE_MODEL": snapshot["defaults"]["fable"],
            "ANTHROPIC_DEFAULT_OPUS_MODEL": snapshot["defaults"]["opus"],
            "ANTHROPIC_DEFAULT_SONNET_MODEL": snapshot["defaults"]["sonnet"],
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": snapshot["defaults"]["haiku"],
            "CLAUDE_CODE_SUBAGENT_MODEL": snapshot["defaults"]["subagent"],
            "ANTHROPIC_SMALL_FAST_MODEL": snapshot["defaults"]["haiku"],
        }
    )
    if ui_lang() == "zh" and "language" not in settings:
        settings["language"] = "chinese"
    settings["model"] = default_model
    settings["fallbackModel"] = "openrouter/free" if "openrouter/free" in available else default_model
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
    settings["env"] = env
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync OpenRouter free models into a Claude Code profile")
    parser.add_argument(
        "--config-dir",
        default=os.environ.get("CLAUDE_OR_HOME") or os.environ.get("CLAUDE_OPENROUTER_HOME") or str(DEFAULT_CONFIG_DIR),
    )
    args = parser.parse_args(argv)
    config_dir = Path(args.config_dir).expanduser()
    snapshot = write_profile(config_dir, fetch_catalog())
    defaults = snapshot["defaults"]
    print(f"Wrote {len(snapshot['usable'])} free models to {config_dir / 'settings.json'}")
    print(f"Default: {defaults['model']}")
    print(
        "Roles: "
        f"fable={defaults['fable']} "
        f"opus={defaults['opus']} "
        f"sonnet={defaults['sonnet']} "
        f"haiku={defaults['haiku']}"
    )
    skipped = snapshot.get("skipped") or []
    if skipped:
        print(f"Skipped {len(skipped)} free models that cannot drive Claude Code (no tools / non-text):")
        for item in skipped:
            print(f"  - {item['id']} ({item['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
