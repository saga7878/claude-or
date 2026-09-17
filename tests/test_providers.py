#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import providers  # noqa: E402
import sync_models  # noqa: E402


def load_fixture(name: str) -> list[dict]:
    payload = json.loads((Path(__file__).parent / "fixtures" / name).read_text())
    return payload["data"]


class ProviderRegistryTests(unittest.TestCase):
    def test_known_providers(self) -> None:
        self.assertEqual(set(providers.provider_ids()), {"openrouter", "aihubmix", "zenmux"})
        self.assertEqual(providers.get_provider("aihubmix").base_url, "https://aihubmix.com")
        self.assertEqual(providers.get_provider("zenmux").base_url, "https://zenmux.ai/api/anthropic")

    def test_key_prefixes(self) -> None:
        aihubmix = providers.get_provider("aihubmix")
        self.assertTrue(providers.key_looks_valid(aihubmix, "sk-abc"))
        self.assertFalse(providers.key_looks_valid(aihubmix, "sk-or-v1-abc"))
        zenmux = providers.get_provider("zenmux")
        self.assertTrue(providers.key_looks_valid(zenmux, "sk-ss-v1-abc"))
        self.assertTrue(providers.key_looks_valid(zenmux, "sk-ai-v1-abc"))


class AihubmixCatalogTests(unittest.TestCase):
    def test_keeps_coding_free_and_drops_image(self) -> None:
        usable, skipped = providers.usable_aihubmix(load_fixture("aihubmix.json"))
        ids = [item["id"] for item in usable]
        skipped_ids = {item["id"] for item in skipped}
        self.assertIn("coding-glm-5.3-free", ids)
        self.assertIn("kimi-for-coding-free", ids)
        self.assertNotIn("gpt-4o", ids)
        self.assertNotIn("xiaomi-mimo-v2.5-pro-free", ids)
        self.assertIn("gpt-image-2-free", skipped_ids)
        self.assertIn("hy3-free", skipped_ids)
        self.assertIn("xiaomi-mimo-v2.5-pro-free", skipped_ids)
        self.assertEqual(ids[0], "coding-glm-5.3-free")
        self.assertEqual(usable[0]["context_length"], 1048576)

    def test_writes_aihubmix_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = sync_models.write_profile(
                Path(tmp),
                load_fixture("aihubmix.json"),
                provider=providers.get_provider("aihubmix"),
            )
            settings = json.loads((Path(tmp) / "settings.json").read_text())
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "https://aihubmix.com")
            self.assertEqual(snapshot["defaults"]["sonnet"], "coding-glm-5.3-free")
            self.assertEqual(snapshot["provider"], "aihubmix")
            self.assertIsInstance(settings["fallbackModel"], list)
            self.assertLessEqual(len(settings["fallbackModel"]), 3)
            self.assertNotIn(settings["model"], settings["fallbackModel"])


class ZenmuxCatalogTests(unittest.TestCase):
    def test_keeps_zero_price_and_drops_paid(self) -> None:
        usable, skipped = providers.usable_zenmux(load_fixture("zenmux.json"))
        ids = [item["id"] for item in usable]
        self.assertIn("z-ai/glm-4.7-flash-free", ids)
        self.assertIn("sapiens-ai/agnes-2.5-flash", ids)
        self.assertNotIn("anthropic/claude-sonnet-4.6", ids)
        self.assertFalse(skipped)

    def test_writes_zenmux_anthropic_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = sync_models.write_profile(
                Path(tmp),
                load_fixture("zenmux.json"),
                provider=providers.get_provider("zenmux"),
            )
            settings = json.loads((Path(tmp) / "settings.json").read_text())
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "https://zenmux.ai/api/anthropic")
            self.assertEqual(snapshot["defaults"]["sonnet"], "z-ai/glm-4.7-flash-free")
            self.assertIsInstance(settings["fallbackModel"], list)
            self.assertNotIn(settings["model"], settings["fallbackModel"])


if __name__ == "__main__":
    unittest.main()
