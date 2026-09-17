#!/usr/bin/env python3
"""Provider registry for isolated Claude Code profiles."""

from __future__ import annotations

import argparse
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".claude-or"
STATE_FILE = STATE_DIR / "state.json"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    catalog_url: str
    signup: str
    key_service: str
    key_account: str
    key_file_name: str
    key_prefixes: tuple[str, ...]
    probe: str
    quota: str
    pin_first: tuple[str, ...]
    sonnet_prefs: tuple[str, ...]
    opus_prefs: tuple[str, ...]
    fable_prefs: tuple[str, ...]
    haiku_prefs: tuple[str, ...]

    def config_dir(self) -> Path:
        if self.id == "openrouter":
            override = os.environ.get("CLAUDE_OR_HOME") or os.environ.get("CLAUDE_OPENROUTER_HOME")
            if override:
                return Path(override).expanduser()
            return Path.home() / ".claude-openrouter"
        return Path.home() / f".claude-or-{self.id}"

    def key_file(self) -> Path:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        return root / "claude-or" / self.key_file_name


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api",
        catalog_url="https://openrouter.ai/api/v1/models",
        signup="https://openrouter.ai/settings/keys",
        key_service="openrouter",
        key_account="api-key",
        key_file_name="api-key",
        key_prefixes=("sk-or-",),
        probe="openrouter-endpoints",
        quota="openrouter-key",
        pin_first=(
            "openrouter/free",
            "stealth/union-alpha",
            "nex-agi/nex-n2.5-pro:free",
            "poolside/laguna-s-2.1:free",
            "cohere/north-mini-code:free",
        ),
        sonnet_prefs=(
            "nex-agi/nex-n2.5-pro:free",
            "poolside/laguna-s-2.1:free",
            "stealth/union-alpha",
            "cohere/north-mini-code:free",
            "openrouter/free",
        ),
        opus_prefs=(
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "thinkingmachines/inkling:free",
            "nex-agi/nex-n2.5-pro:free",
            "openrouter/free",
        ),
        fable_prefs=(
            "thinkingmachines/inkling:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nex-agi/nex-n2.5-pro:free",
        ),
        haiku_prefs=(
            "nvidia/nemotron-3.5-lightning:free",
            "poolside/laguna-xs-2.1:free",
            "nex-agi/nex-n2.5-mini:free",
            "liquid/lfm-2.5-2.6b:free",
        ),
    ),
    "aihubmix": Provider(
        id="aihubmix",
        name="AIHubMix",
        base_url="https://aihubmix.com",
        catalog_url="https://aihubmix.com/api/v1/models",
        signup="https://aihubmix.com",
        key_service="aihubmix",
        key_account="api-key",
        key_file_name="aihubmix-api-key",
        key_prefixes=("sk-",),
        probe="none",
        quota="none",
        pin_first=(
            "coding-glm-5.3-free",
            "coding-glm-5.1-free",
            "kimi-for-coding-free",
            "coding-minimax-m3-free",
            "coding-kimi-k3-free",
            "gpt-5.5-free",
            "union-alpha-free",
        ),
        sonnet_prefs=(
            "coding-glm-5.3-free",
            "coding-glm-5.1-free",
            "kimi-for-coding-free",
            "coding-minimax-m3-free",
            "gpt-5.5-free",
        ),
        opus_prefs=(
            "coding-glm-5.3-free",
            "gpt-5.5-free",
            "kimi-for-coding-free",
        ),
        fable_prefs=(
            "coding-glm-5.3-free",
            "gpt-5.5-free",
        ),
        haiku_prefs=(
            "gemini-3.8-flash-free",
            "gemini-3.7-flash-free",
            "ling-3.0-flash-free",
            "kimi-for-coding-free",
        ),
    ),
    "zenmux": Provider(
        id="zenmux",
        name="ZenMux",
        base_url="https://zenmux.ai/api/anthropic",
        catalog_url="https://zenmux.ai/api/anthropic/v1/models",
        signup="https://zenmux.ai",
        key_service="zenmux",
        key_account="api-key",
        key_file_name="zenmux-api-key",
        key_prefixes=("sk-ss-v1-", "sk-ai-v1-", "sk-"),
        probe="none",
        quota="none",
        pin_first=(
            "z-ai/glm-4.7-flash-free",
            "dots-studio/dots3-note-prev",
            "inclusionai/ling-3.0-flash-vl",
            "sapiens-ai/agnes-2.5-flash",
        ),
        sonnet_prefs=(
            "z-ai/glm-4.7-flash-free",
            "dots-studio/dots3-note-prev",
            "inclusionai/ling-3.0-flash-vl",
        ),
        opus_prefs=(
            "sapiens-ai/agnes-2.5-flash",
            "z-ai/glm-4.7-flash-free",
        ),
        fable_prefs=(
            "sapiens-ai/agnes-2.5-flash",
            "inclusionai/ling-3.0-flash-vl",
        ),
        haiku_prefs=(
            "inclusionai/ling-3.0-tiny",
            "z-ai/glm-4.6v-flash-free",
            "z-ai/glm-4.7-flash-free",
        ),
    ),
}


def provider_ids() -> list[str]:
    return list(PROVIDERS)


def get_provider(provider_id: str | None) -> Provider:
    name = (provider_id or "openrouter").strip().lower()
    if name not in PROVIDERS:
        known = ", ".join(provider_ids())
        raise SystemExit(f"unknown provider {name!r}. choose: {known}")
    return PROVIDERS[name]


def load_active_id() -> str:
    env = os.environ.get("CLAUDE_OR_PROVIDER")
    if env:
        return get_provider(env).id
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return get_provider(str(data.get("provider") or "openrouter")).id
        except (OSError, json.JSONDecodeError, SystemExit):
            return "openrouter"
    return "openrouter"


def save_active_id(provider_id: str) -> Provider:
    provider = get_provider(provider_id)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"provider": provider.id}, indent=2) + "\n")
    return provider


def key_looks_valid(provider: Provider, key: str) -> bool:
    if provider.id == "aihubmix":
        return key.startswith("sk-") and not key.startswith("sk-or-")
    if provider.id == "zenmux":
        return key.startswith("sk-ss-v1-") or key.startswith("sk-ai-v1-") or (
            key.startswith("sk-") and not key.startswith("sk-or-")
        )
    return any(key.startswith(prefix) for prefix in provider.key_prefixes)


def dump_active(provider: Provider) -> dict[str, str]:
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "catalog_url": provider.catalog_url,
        "config_dir": str(provider.config_dir()),
        "key_service": provider.key_service,
        "key_account": provider.key_account,
        "key_file": str(provider.key_file()),
        "signup": provider.signup,
        "probe": provider.probe,
        "quota": provider.quota,
    }


def _pricing_values(node: Any) -> list[Any]:
    if node is None:
        return []
    if isinstance(node, list):
        values = []
        for item in node:
            if isinstance(item, dict) and "value" in item:
                values.append(item.get("value"))
            else:
                values.append(item)
        return values
    return [node]


def is_zero_price(node: Any) -> bool:
    values = _pricing_values(node)
    if not values:
        return False
    try:
        return all(float(value) == 0.0 for value in values)
    except (TypeError, ValueError):
        return False


def aihubmix_skip_reason(model_id: str, model: dict[str, Any] | None = None) -> str | None:
    lowered = model_id.lower()
    if "image" in lowered:
        return "image model"
    if lowered in {"hy3-free"}:
        return "non-text / video model"
    if "content-safety" in lowered:
        return "content-safety classifier"
    types = str((model or {}).get("types") or "").lower()
    if types and types != "llm":
        return f"non-llm type ({types})"
    if model is not None and not aihubmix_has_tools(model):
        return "no tool calling"
    return None


def aihubmix_has_tools(model: dict[str, Any]) -> bool:
    if model.get("tool_call") is True:
        return True
    features = {part.strip() for part in str(model.get("features") or "").lower().split(",") if part.strip()}
    return bool(features & {"tools", "tool_calling", "function_calling"})


def usable_aihubmix(catalog: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    usable: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for model in catalog:
        model_id = str(model.get("id") or model.get("model_id") or "")
        if not model_id.endswith("-free"):
            continue
        reason = aihubmix_skip_reason(model_id, model)
        name = str(model.get("name") or model.get("model_name") or model_id)
        if reason:
            skipped.append({"id": model_id, "reason": reason, "name": name})
            continue
        usable.append(
            {
                "id": model_id,
                "name": name,
                "stealth": "union-alpha" in model_id,
                "context_length": int(model.get("context_length") or 0),
                "tools": True,
            }
        )
    return _pin(usable, PROVIDERS["aihubmix"].pin_first), skipped


def usable_zenmux(catalog: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    usable: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for model in catalog:
        model_id = str(model.get("id") or "")
        if not model_id:
            continue
        name = str(model.get("display_name") or model.get("name") or model_id)
        pricings = model.get("pricings") or model.get("pricing") or {}
        priced = bool(pricings.get("prompt") is not None and pricings.get("completion") is not None)
        if priced:
            free = is_zero_price(pricings.get("prompt")) and is_zero_price(pricings.get("completion"))
        else:
            free = model_id.endswith("-free") or model_id.endswith(":free")
        if not free:
            continue
        outputs = model.get("output_modalities") or ["text"]
        inputs = model.get("input_modalities") or ["text"]
        if "audio" in outputs and "text" not in outputs:
            skipped.append({"id": model_id, "reason": "audio output", "name": name})
            continue
        if "text" not in outputs:
            skipped.append({"id": model_id, "reason": "non-text output", "name": name})
            continue
        if "text" not in inputs:
            skipped.append({"id": model_id, "reason": "no text input", "name": name})
            continue
        usable.append(
            {
                "id": model_id,
                "name": name,
                "stealth": model_id.startswith("stealth/") or "stealth" in name.lower(),
                "context_length": int(model.get("context_length") or 0),
                "tools": True,
            }
        )
    return _pin(usable, PROVIDERS["zenmux"].pin_first), skipped


def _pin(usable: list[dict[str, Any]], pin_first: tuple[str, ...]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in usable}
    ordered: list[dict[str, Any]] = []
    for pin in pin_first:
        if pin in by_id:
            ordered.append(by_id.pop(pin))
    ordered.extend(sorted(by_id.values(), key=lambda item: (-int(item.get("context_length") or 0), item["id"])))
    return ordered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="claude-or provider registry")
    parser.add_argument("--provider", help="provider id (default: active)")
    parser.add_argument("--dump-shell", action="store_true")
    parser.add_argument("--dump-json", action="store_true")
    parser.add_argument("--set")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.set:
        provider = save_active_id(args.set)
        print(provider.id)
        return 0
    if args.list:
        active = load_active_id()
        for provider_id, provider in PROVIDERS.items():
            mark = "*" if provider_id == active else " "
            print(
                f"{mark} {provider_id:12} {provider.name:12} {provider.base_url}  {provider.config_dir()}"
            )
        return 0
    provider = get_provider(args.provider or load_active_id())
    data = dump_active(provider)
    if args.dump_json:
        print(json.dumps(data))
        return 0
    if args.dump_shell:
        for key, value in data.items():
            env_key = "PROVIDER_" + key.upper()
            print(f"{env_key}={shlex.quote(str(value))}")
        return 0
    print(provider.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
