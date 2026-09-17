#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import sync_models  # noqa: E402


def catalog() -> list[dict]:
    payload = json.loads((Path(__file__).parent / "fixtures" / "catalog.json").read_text())
    return payload["data"]


class FreeCatalogTests(unittest.TestCase):
    def test_includes_stealth_without_free_suffix(self) -> None:
        usable, skipped = sync_models.usable_free_chat_models(catalog())
        ids = [item["id"] for item in usable]
        self.assertIn("stealth/union-alpha", ids)
        stealth = next(item for item in usable if item["id"] == "stealth/union-alpha")
        self.assertTrue(stealth["stealth"])

    def test_pins_stealth_after_free_router(self) -> None:
        usable, _ = sync_models.usable_free_chat_models(catalog())
        ids = [item["id"] for item in usable]
        self.assertEqual(ids[0], "openrouter/free")
        self.assertEqual(ids[1], "stealth/union-alpha")

    def test_skips_no_tools_and_paid(self) -> None:
        usable, skipped = sync_models.usable_free_chat_models(catalog())
        ids = {item["id"] for item in usable}
        skipped_ids = {item["id"] for item in skipped}
        self.assertNotIn("anthropic/claude-sonnet-4.6", ids)
        self.assertNotIn("anthropic/claude-sonnet-4.6", skipped_ids)
        self.assertIn("z-ai/glm-5.2:free", skipped_ids)
        self.assertIn("google/lyria-3-pro-preview", skipped_ids)
        self.assertTrue(ids <= {"openrouter/free", "stealth/union-alpha", "nex-agi/nex-n2.5-pro:free"})

    def test_writes_isolated_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = sync_models.write_profile(Path(tmp), catalog())
            settings = json.loads((Path(tmp) / "settings.json").read_text())
            self.assertEqual(snapshot["defaults"]["sonnet"], "nex-agi/nex-n2.5-pro:free")
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "https://openrouter.ai/api")
            self.assertEqual(settings["env"]["ANTHROPIC_API_KEY"], "")
            labels = [row["label"] for row in settings["modelPicker"]["options"]]
            self.assertTrue(any("Union Alpha" in label for label in labels))
            self.assertTrue(settings["modelPicker"]["replaceBuiltInOptions"])
            self.assertEqual(settings["fallbackModel"], ["openrouter/free", "stealth/union-alpha"])
            self.assertNotIn(settings["model"], settings["fallbackModel"])

    def test_user_defaults_survive_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            sync_models.write_profile(config_dir, catalog())
            snapshot = sync_models.apply_user_defaults(config_dir, {"model": "stealth/union-alpha"})
            self.assertEqual(snapshot["defaults"]["model"], "stealth/union-alpha")
            again = sync_models.write_profile(config_dir, catalog())
            self.assertEqual(again["defaults"]["model"], "stealth/union-alpha")
            settings = json.loads((config_dir / "settings.json").read_text())
            self.assertEqual(settings["model"], "stealth/union-alpha")
            self.assertEqual(settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], again["defaults"]["sonnet"])
            self.assertEqual(settings["fallbackModel"], ["openrouter/free", "nex-agi/nex-n2.5-pro:free"])
            self.assertNotIn("stealth/union-alpha", settings["fallbackModel"])

    def test_rejects_unknown_user_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sync_models.write_profile(Path(tmp), catalog())
            with self.assertRaises(ValueError):
                sync_models.apply_user_defaults(Path(tmp), {"model": "paid/not-free"})


class FallbackChainTests(unittest.TestCase):
    def test_writes_array_not_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sync_models.write_profile(Path(tmp), catalog())
            settings = json.loads((Path(tmp) / "settings.json").read_text())
            self.assertIsInstance(settings["fallbackModel"], list)
            self.assertLessEqual(len(settings["fallbackModel"]), 3)

    def test_prefers_free_router_and_excludes_primary(self) -> None:
        usable = [
            {"id": "nex-agi/nex-n2.5-pro:free", "health": "up"},
            {"id": "stealth/union-alpha", "health": "up"},
            {"id": "openrouter/free", "health": "up"},
            {"id": "poolside/laguna-s-2.1:free", "health": "up"},
            {"id": "cohere/north-mini-code:free", "health": "up"},
        ]
        chain = sync_models.pick_fallback_chain(usable, "nex-agi/nex-n2.5-pro:free")
        self.assertEqual(chain[0], "openrouter/free")
        self.assertNotIn("nex-agi/nex-n2.5-pro:free", chain)
        self.assertEqual(len(chain), 3)

    def test_does_not_lead_with_down_router(self) -> None:
        usable = [
            {"id": "nex-agi/nex-n2.5-pro:free", "health": "up"},
            {"id": "stealth/union-alpha", "health": "up"},
            {"id": "openrouter/free", "health": "down"},
        ]
        chain = sync_models.pick_fallback_chain(usable, "nex-agi/nex-n2.5-pro:free")
        self.assertEqual(chain, ["stealth/union-alpha", "openrouter/free"])

    def test_omits_fallback_when_catalog_has_one_model(self) -> None:
        settings: dict = {"fallbackModel": "openrouter/free"}
        chain = sync_models.set_fallback_model(settings, [{"id": "only/one"}], "only/one")
        self.assertEqual(chain, [])
        self.assertNotIn("fallbackModel", settings)

    def test_rebuilds_chain_when_primary_becomes_router(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            sync_models.write_profile(config_dir, catalog())
            sync_models.apply_user_defaults(config_dir, {"model": "openrouter/free"})
            settings = json.loads((config_dir / "settings.json").read_text())
            self.assertEqual(settings["model"], "openrouter/free")
            self.assertIsInstance(settings["fallbackModel"], list)
            self.assertNotIn("openrouter/free", settings["fallbackModel"])


if __name__ == "__main__":
    unittest.main()
