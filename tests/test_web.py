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
import web  # noqa: E402


def catalog() -> list[dict]:
    payload = json.loads((Path(__file__).parent / "fixtures" / "catalog.json").read_text())
    return payload["data"]


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.dash = web.Dashboard(root=ROOT, host="127.0.0.1", port=8787, home=self.home)
        self.dash.live_quota = lambda provider, api_key: {"remaining": 38, "limit": 50, "used": 12}
        self.dash.peek_key = lambda provider: ""
        self.dash.launch_in_terminal = lambda provider: f"exec claude-or ({provider.id})"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _json(self, method: str, path: str, body: dict | None = None, origin: str = "http://127.0.0.1:8787"):
        raw = json.dumps(body).encode() if body is not None else b""
        headers = {"origin": origin} if origin else {}
        status, payload, content_type = self.dash.dispatch(method, path, raw, headers)
        data = json.loads(payload.decode()) if "json" in content_type else payload.decode()
        return status, data

    def test_state_lists_providers_without_keys(self) -> None:
        status, data = self._json("GET", "/api/state", origin="")
        self.assertEqual(status, 200)
        self.assertEqual(data["active"], "openrouter")
        ids = [item["id"] for item in data["providers"]]
        self.assertEqual(ids, ["openrouter", "aihubmix", "zenmux"])
        self.assertFalse(any(item["has_key"] for item in data["providers"]))

    def test_does_not_leak_api_key(self) -> None:
        secret = "sk-or-secret-value-9999"
        self.dash.peek_key = lambda provider: secret if provider.id == "openrouter" else ""
        status, data = self._json("GET", "/api/state", origin="")
        self.assertEqual(status, 200)
        blob = json.dumps(data)
        self.assertNotIn(secret, blob)
        self.assertNotIn("sk-or-secret", blob)
        openrouter = next(item for item in data["providers"] if item["id"] == "openrouter")
        self.assertTrue(openrouter["has_key"])
        self.assertEqual(openrouter["key_hint"], "••••9999")
        self.assertEqual(openrouter["quota"]["remaining"], 38)

    def test_switch_provider_writes_isolated_state(self) -> None:
        status, data = self._json("POST", "/api/provider", {"id": "zenmux"})
        self.assertEqual(status, 200)
        self.assertEqual(data["active"], "zenmux")
        saved = json.loads((self.home / ".claude-or" / "state.json").read_text())
        self.assertEqual(saved["provider"], "zenmux")
        self.assertNotEqual(self.home.resolve(), Path.home().resolve())

    def test_rejects_cross_origin_post(self) -> None:
        status, data = self._json("POST", "/api/provider", {"id": "aihubmix"}, origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertIn("origin", data["error"])

    def test_set_defaults_and_survive_sync(self) -> None:
        config_dir = self.dash.config_dir(providers.get_provider("openrouter"))
        sync_models.write_profile(config_dir, catalog())
        status, data = self._json("POST", "/api/defaults", {"provider": "openrouter", "model": "stealth/union-alpha"})
        self.assertEqual(status, 200)
        openrouter = next(item for item in data["providers"] if item["id"] == "openrouter")
        self.assertEqual(openrouter["defaults"]["model"], "stealth/union-alpha")
        settings = json.loads((config_dir / "settings.json").read_text())
        self.assertEqual(settings["model"], "stealth/union-alpha")
        again = sync_models.write_profile(config_dir, catalog())
        self.assertEqual(again["defaults"]["model"], "stealth/union-alpha")

    def test_store_key_to_file_backend(self) -> None:
        status, data = self._json(
            "POST",
            "/api/key",
            {"provider": "openrouter", "key": "sk-or-test-key-abcd"},
        )
        self.assertEqual(status, 200)
        path = self.dash.key_file(providers.get_provider("openrouter"))
        self.assertEqual(path.read_text().strip(), "sk-or-test-key-abcd")
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertNotIn("sk-or-test-key-abcd", json.dumps(data))

    def test_sync_uses_injected_catalog(self) -> None:
        self.dash.run_sync = lambda provider, *, probe: sync_models.write_profile(
            self.dash.config_dir(provider),
            catalog(),
            provider=provider,
        )
        status, data = self._json("POST", "/api/sync", {"provider": "openrouter", "probe": False})
        self.assertEqual(status, 200)
        openrouter = next(item for item in data["providers"] if item["id"] == "openrouter")
        self.assertGreater(len(openrouter["models"]), 0)
        ids = [item["id"] for item in openrouter["models"]]
        self.assertIn("stealth/union-alpha", ids)

    def test_launch_returns_command(self) -> None:
        status, data = self._json("POST", "/api/launch", {"provider": "openrouter"})
        self.assertEqual(status, 200)
        self.assertIn("claude-or", data["command"])

    def test_refuses_lan_bind(self) -> None:
        with self.assertRaises(SystemExit):
            web.bind_host("0.0.0.0")
        with self.assertRaises(SystemExit):
            web.bind_host("192.168.1.2")
        self.assertEqual(web.bind_host("127.0.0.1"), "127.0.0.1")

    def test_mask_key(self) -> None:
        self.assertEqual(web.mask_key("sk-or-abcdefgh"), "••••efgh")
        self.assertEqual(web.mask_key("short"), "••••")

    def test_static_index(self) -> None:
        status, payload, content_type = self.dash.dispatch("GET", "/", b"", {})
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"claude-or", payload)
        self.assertIn(b"claude-or-theme", payload)
        self.assertIn(b'id="theme"', payload)

    def test_favicon_is_empty_ok(self) -> None:
        status, payload, _content_type = self.dash.dispatch("GET", "/favicon.ico", b"", {})
        self.assertEqual(status, 204)
        self.assertEqual(payload, b"")

    def test_unknown_provider(self) -> None:
        status, data = self._json("POST", "/api/provider", {"id": "openai"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
