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


class EndpointHealthTests(unittest.TestCase):
    def test_encodes_free_suffix_in_endpoints_url(self) -> None:
        url = sync_models.endpoints_url("nex-agi/nex-n2.5-pro:free")
        self.assertIn("/models/nex-agi/nex-n2.5-pro%3Afree/endpoints", url)
        self.assertNotIn("nex-n2.5-pro:free/endpoints", url)

    def test_status_zero_is_up(self) -> None:
        result = sync_models.classify_endpoints(
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            {"data": {"endpoints": [{"status": 0, "uptime_last_5m": 99.9}]}},
        )
        self.assertEqual(result["health"], "up")

    def test_no_endpoints_is_down(self) -> None:
        result = sync_models.classify_endpoints("poolside/laguna-s-2.1:free", {"data": {"endpoints": []}})
        self.assertEqual(result["health"], "down")

    def test_nonzero_status_is_down(self) -> None:
        result = sync_models.classify_endpoints(
            "google/gemma-4-31b-it:free",
            {"data": {"endpoints": [{"status": -1, "uptime_last_5m": 0}]}},
        )
        self.assertEqual(result["health"], "down")

    def test_fetch_error_is_unknown(self) -> None:
        result = sync_models.classify_endpoints("x/y:free", None, error="timeout")
        self.assertEqual(result["health"], "unknown")

    def test_free_router_stays_up_without_endpoints(self) -> None:
        result = sync_models.classify_endpoints("openrouter/free", {"data": {"endpoints": []}})
        self.assertEqual(result["health"], "up")
        self.assertEqual(sync_models.classify_endpoints("openrouter/free", None, error="HTTP 404")["health"], "up")


class ProbeProfileTests(unittest.TestCase):
    def test_skips_down_models_for_defaults_and_pins_them_last(self) -> None:
        probe = {
            "nex-agi/nex-n2.5-pro:free": {"health": "down", "reason": "endpoint status -1"},
            "stealth/union-alpha": {"health": "up", "reason": "status 0"},
            "openrouter/free": {"health": "up", "reason": "status 0"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = sync_models.write_profile(Path(tmp), catalog(), probe_results=probe)
            self.assertEqual(snapshot["defaults"]["sonnet"], "stealth/union-alpha")
            settings = json.loads((Path(tmp) / "settings.json").read_text())
            labels = [row["label"] for row in settings["modelPicker"]["options"]]
            self.assertTrue(any("Union Alpha" in label for label in labels))
            down_row = settings["modelPicker"]["options"][-1]
            self.assertEqual(down_row["model"], "nex-agi/nex-n2.5-pro:free")
            self.assertTrue(down_row["label"].startswith("Down") or down_row["label"].startswith("挂了"))


class QuotaTests(unittest.TestCase):
    def test_quota_exit_codes_distinguish_fetch_failure(self) -> None:
        openrouter = sync_models.get_provider("openrouter")
        aihubmix = sync_models.get_provider("aihubmix")
        self.assertEqual(sync_models.quota_exit_code(aihubmix, "", None), 0)
        self.assertEqual(sync_models.quota_exit_code(openrouter, "", None), 1)
        self.assertEqual(sync_models.quota_exit_code(openrouter, "sk-or-x", None), 1)
        self.assertEqual(sync_models.quota_exit_code(openrouter, "sk-or-x", {"remaining": 0, "limit": 50}), 2)
        self.assertEqual(sync_models.quota_exit_code(openrouter, "sk-or-x", {"remaining": 3, "limit": 50}), 0)
        self.assertIn("no API key", sync_models.format_quota_line(None, has_key=False))
        self.assertIn("GET /api/v1/key failed", sync_models.format_quota_line(None, has_key=True))
        self.assertIn("does not expose", sync_models.format_quota_line(None, provider=aihubmix))

    def test_parses_free_model_daily_requests(self) -> None:
        payload = json.loads((Path(__file__).parent / "fixtures" / "key.json").read_text())
        quota = sync_models.parse_key_payload(payload)
        self.assertEqual(quota["limit"], 50)
        self.assertEqual(quota["remaining"], 38)
        self.assertEqual(quota["used"], 12)
        self.assertTrue(quota["is_free_tier"])

    def test_formats_remaining_and_warns_when_empty(self) -> None:
        ok = sync_models.format_quota_line({"limit": 50, "remaining": 38, "used": 12, "is_free_tier": True})
        self.assertIn("38/50", ok)
        empty = sync_models.format_quota_line({"limit": 50, "remaining": 0, "used": 50, "is_free_tier": True})
        self.assertIn("0/50", empty)
        self.assertTrue(sync_models.quota_is_exhausted({"remaining": 0, "limit": 50}))
        self.assertFalse(sync_models.quota_is_exhausted({"remaining": 1, "limit": 50}))

    def test_catalog_stale_after_24h(self) -> None:
        self.assertTrue(sync_models.is_stale("2020-01-01T00:00:00+00:00"))
        self.assertTrue(sync_models.is_stale(None))
        self.assertFalse(sync_models.is_stale(sync_models.utcnow().isoformat()))


if __name__ == "__main__":
    unittest.main()
