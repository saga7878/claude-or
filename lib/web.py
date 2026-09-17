#!/usr/bin/env python3
"""Local dashboard for claude-or. Loopback only. Next-launch control plane."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from providers import PROVIDERS, Provider, get_provider, key_looks_valid, load_active_id
from sync_models import (
    apply_user_defaults,
    fetch_catalog,
    fetch_quota,
    format_quota_line,
    is_stale,
    load_snapshot,
    package_version,
    picker_label,
    probe_models,
    ui_lang,
    usable_for_provider,
    write_profile,
)

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
STATIC_FILES = {"index.html", "app.css", "app.js"}
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MAX_BODY = 32 * 1024
QUOTA_TTL = 30.0
DEFAULT_PORT = 8787


class DashboardError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def mask_key(key: str) -> str:
    if len(key) < 8:
        return "••••"
    return "••••" + key[-4:]


def is_loopback_host(host: str) -> bool:
    name = host.strip().lower().split("%", 1)[0]
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    return name in LOOPBACK


def origin_host(value: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    hostname = (parsed.hostname or "").lower()
    return hostname or None


class Dashboard:
    def __init__(self, *, root: Path, host: str, port: int, home: Path | None = None) -> None:
        self.root = root
        self.host = host
        self.port = port
        self.home = Path(home) if home is not None else Path.home()
        self._quota_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._lock = threading.Lock()

    def origin_allowed(self, headers: dict[str, str]) -> bool:
        origin = headers.get("origin") or ""
        referer = headers.get("referer") or ""
        allowed = {self.host, "127.0.0.1", "localhost", "::1"}
        if origin:
            hostname = origin_host(origin)
            return bool(hostname and hostname in allowed)
        if referer:
            hostname = origin_host(referer)
            return bool(hostname and hostname in allowed)
        return True

    def config_dir(self, provider: Provider) -> Path:
        if self.home != Path.home():
            if provider.id == "openrouter":
                return self.home / ".claude-openrouter"
            return self.home / f".claude-or-{provider.id}"
        return provider.config_dir()

    def key_file(self, provider: Provider) -> Path:
        if self.home != Path.home():
            return self.home / ".config" / "claude-or" / provider.key_file_name
        return provider.key_file()

    def state_file(self) -> Path:
        return self.home / ".claude-or" / "state.json"

    def active_id(self) -> str:
        env = os.environ.get("CLAUDE_OR_PROVIDER")
        if env:
            return get_provider(env).id
        path = self.state_file()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return get_provider(str(data.get("provider") or "openrouter")).id
            except (OSError, json.JSONDecodeError, SystemExit):
                return "openrouter"
        if self.home == Path.home():
            return load_active_id()
        return "openrouter"

    def set_provider(self, provider_id: str) -> Provider:
        provider = get_provider(provider_id)
        directory = self.state_file().parent
        directory.mkdir(parents=True, exist_ok=True)
        self.state_file().write_text(json.dumps({"provider": provider.id}, indent=2) + "\n")
        return provider

    def peek_key(self, provider: Provider) -> str:
        env = os.environ.get("CLAUDE_OR_API_KEY") or ""
        if not env and provider.id == "openrouter":
            env = os.environ.get("OPENROUTER_API_KEY") or ""
        if env:
            return env.strip()
        use_file = os.environ.get("CLAUDE_OR_KEY_BACKEND") == "file" or self.home != Path.home()
        if not use_file and sys.platform == "darwin" and shutil.which("security"):
            try:
                result = subprocess.run(
                    [
                        "security",
                        "find-generic-password",
                        "-s",
                        provider.key_service,
                        "-a",
                        provider.key_account,
                        "-w",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
        path = self.key_file(provider)
        if path.exists():
            return path.read_text().strip().replace("\r", "")
        return ""

    def store_key(self, provider: Provider, key: str) -> str:
        key = key.strip()
        if not key:
            raise DashboardError(400, "API key is empty")
        if not key_looks_valid(provider, key):
            prefixes = " / ".join(provider.key_prefixes)
            raise DashboardError(400, f"{provider.name} keys start with {prefixes}")
        use_file = os.environ.get("CLAUDE_OR_KEY_BACKEND") == "file" or self.home != Path.home()
        if not use_file and sys.platform == "darwin" and shutil.which("security"):
            result = subprocess.run(
                [
                    "security",
                    "add-generic-password",
                    "-U",
                    "-s",
                    provider.key_service,
                    "-a",
                    provider.key_account,
                    "-w",
                    key,
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if result.returncode != 0:
                raise DashboardError(500, result.stderr.strip() or "Keychain write failed")
            return "keychain"
        path = self.key_file(provider)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(key + "\n")
        os.chmod(path, 0o600)
        return "file"

    def key_source(self, provider: Provider, api_key: str = "") -> str:
        if not api_key:
            return "missing"
        if os.environ.get("CLAUDE_OR_API_KEY") or (
            provider.id == "openrouter" and os.environ.get("OPENROUTER_API_KEY")
        ):
            return "env"
        use_file = os.environ.get("CLAUDE_OR_KEY_BACKEND") == "file" or self.home != Path.home()
        if not use_file and sys.platform == "darwin" and shutil.which("security"):
            return "keychain"
        if self.key_file(provider).exists():
            return "file"
        return "keychain"

    def live_quota(self, provider: Provider, api_key: str) -> dict[str, Any] | None:
        if provider.quota != "openrouter-key" or not api_key:
            return None
        now = time.time()
        with self._lock:
            cached = self._quota_cache.get(provider.id)
            if cached and now - cached[0] < QUOTA_TTL:
                return cached[1]
        quota = fetch_quota(api_key)
        with self._lock:
            self._quota_cache[provider.id] = (now, quota)
        return quota

    def run_sync(self, provider: Provider, *, probe: bool) -> dict[str, Any]:
        api_key = self.peek_key(provider)
        catalog = fetch_catalog(provider.catalog_url, api_key=api_key or None)
        usable, _skipped = usable_for_provider(provider, catalog)
        probe_results = None
        if probe and provider.probe == "openrouter-endpoints":
            probe_results = probe_models([item["id"] for item in usable])
        quota = self.live_quota(provider, api_key)
        return write_profile(
            self.config_dir(provider),
            catalog,
            probe_results=probe_results,
            quota=quota,
            provider=provider,
        )

    def launch_in_terminal(self, provider: Provider) -> str:
        launcher = self.root / "bin" / "claude-or"
        command = f"CLAUDE_OR_PROVIDER={shlex.quote(provider.id)} exec {shlex.quote(str(launcher))}"
        if sys.platform == "darwin":
            script = f'tell application "Terminal" to do script {json.dumps(command)}'
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8, check=False)
            if result.returncode != 0:
                raise DashboardError(500, result.stderr.strip() or "could not open Terminal")
            return command
        raise DashboardError(400, f"open a terminal and run: {command}")

    def provider_payload(self, provider: Provider, *, active: str, api_key: str) -> dict[str, Any]:
        snapshot = load_snapshot(self.config_dir(provider))
        quota = None
        if api_key and provider.quota == "openrouter-key":
            quota = self.live_quota(provider, api_key) or ((snapshot or {}).get("quota") if snapshot else None)
        models = []
        defaults: dict[str, Any] = {}
        user_defaults: dict[str, Any] = {}
        catalog_meta: dict[str, Any] = {"fetched_at": None, "stale": True, "usable": 0, "down": 0, "unknown": 0, "up": 0}
        if snapshot:
            defaults = snapshot.get("defaults") or {}
            user_defaults = snapshot.get("user_defaults") or {}
            probe = snapshot.get("probe") or {}
            catalog_meta = {
                "fetched_at": snapshot.get("fetched_at"),
                "stale": is_stale(snapshot.get("fetched_at")),
                "usable": len(snapshot.get("usable") or []),
                "down": probe.get("down") or 0,
                "unknown": probe.get("unknown") or 0,
                "up": probe.get("up") or 0,
            }
            for item in snapshot.get("usable") or []:
                models.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "label": picker_label(item),
                        "stealth": bool(item.get("stealth")),
                        "health": item.get("health") or "unknown",
                        "context_length": int(item.get("context_length") or 0),
                        "probe_reason": item.get("probe_reason") or "",
                    }
                )
        return {
            "id": provider.id,
            "name": provider.name,
            "base_url": provider.base_url,
            "signup": provider.signup,
            "active": provider.id == active,
            "has_key": bool(api_key),
            "key_hint": mask_key(api_key) if api_key else "",
            "key_source": self.key_source(provider, api_key) if api_key else "missing",
            "probe": provider.probe,
            "quota_kind": provider.quota,
            "config_dir": str(self.config_dir(provider)),
            "catalog": catalog_meta,
            "quota": quota,
            "quota_line": format_quota_line(quota, provider=provider, has_key=bool(api_key)),
            "defaults": defaults,
            "user_defaults": user_defaults,
            "models": models,
        }

    def state(self) -> dict[str, Any]:
        active = self.active_id()
        providers = []
        for provider in PROVIDERS.values():
            api_key = self.peek_key(provider)
            providers.append(self.provider_payload(provider, active=active, api_key=api_key))
        return {
            "version": package_version(),
            "lang": ui_lang(),
            "bind": f"{self.host}:{self.port}",
            "active": active,
            "provider_env": os.environ.get("CLAUDE_OR_PROVIDER") or "",
            "providers": providers,
        }

    def dispatch(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes, str]:
        if method in {"POST", "PUT", "PATCH", "DELETE"} and not self.origin_allowed(headers):
            return 403, _json({"error": "origin not allowed"}), "application/json; charset=utf-8"
        try:
            if method == "GET" and path == "/api/state":
                return 200, _json(self.state()), "application/json; charset=utf-8"
            if method == "GET" and path in {"/health", "/healthz"}:
                return 200, b"ok\n", "text/plain; charset=utf-8"
            if method == "POST" and path == "/api/provider":
                payload = _read_json(body)
                provider_id = str(payload.get("id") or "").strip()
                if not provider_id:
                    raise DashboardError(400, "provider id required")
                self.set_provider(provider_id)
                return 200, _json(self.state()), "application/json; charset=utf-8"
            if method == "POST" and path == "/api/defaults":
                payload = _read_json(body)
                provider = get_provider(str(payload.get("provider") or self.active_id()))
                chosen = {
                    key: str(payload[key])
                    for key in ("model", "fable", "opus", "sonnet", "haiku", "subagent")
                    if payload.get(key)
                }
                if not chosen:
                    raise DashboardError(400, "no defaults in body")
                apply_user_defaults(self.config_dir(provider), chosen)
                return 200, _json(self.state()), "application/json; charset=utf-8"
            if method == "POST" and path == "/api/key":
                payload = _read_json(body)
                provider = get_provider(str(payload.get("provider") or self.active_id()))
                source = self.store_key(provider, str(payload.get("key") or ""))
                state = self.state()
                state["key_stored"] = source
                return 200, _json(state), "application/json; charset=utf-8"
            if method == "POST" and path == "/api/sync":
                payload = _read_json(body) if body else {}
                provider = get_provider(str(payload.get("provider") or self.active_id()))
                probe = payload.get("probe", True)
                self.run_sync(provider, probe=bool(probe))
                return 200, _json(self.state()), "application/json; charset=utf-8"
            if method == "POST" and path == "/api/launch":
                payload = _read_json(body) if body else {}
                provider = get_provider(str(payload.get("provider") or self.active_id()))
                if payload.get("provider"):
                    self.set_provider(provider.id)
                command = self.launch_in_terminal(provider)
                return 200, _json({"ok": True, "command": command}), "application/json; charset=utf-8"
            if method == "GET" and path == "/favicon.ico":
                return 204, b"", "image/x-icon"
            if method == "GET":
                return self._static(path)
            return 404, _json({"error": "not found"}), "application/json; charset=utf-8"
        except DashboardError as exc:
            return exc.status, _json({"error": exc.message}), "application/json; charset=utf-8"
        except SystemExit as exc:
            message = str(exc) or "bad request"
            return 400, _json({"error": message}), "application/json; charset=utf-8"
        except ValueError as exc:
            return 400, _json({"error": str(exc)}), "application/json; charset=utf-8"
        except RuntimeError as exc:
            return 502, _json({"error": str(exc)}), "application/json; charset=utf-8"

    def _static(self, path: str) -> tuple[int, bytes, str]:
        name = path.lstrip("/") or "index.html"
        if name not in STATIC_FILES:
            return 404, _json({"error": "not found"}), "application/json; charset=utf-8"
        target = WEB_DIR / name
        if not target.is_file():
            return 404, _json({"error": "missing static file"}), "application/json; charset=utf-8"
        data = target.read_bytes()
        return 200, data, MIME.get(target.suffix, "application/octet-stream")


def _json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def _read_json(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DashboardError(400, f"invalid json: {exc}") from exc
    if not isinstance(data, dict):
        raise DashboardError(400, "json object required")
    return data


def make_handler(dashboard: Dashboard) -> Callable[..., BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("claude-or web: " + (fmt % args) + "\n")

        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def _handle(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._write(413, b'{"error":"payload too large"}\n', "application/json; charset=utf-8")
                return
            body = self.rfile.read(length) if length else b""
            headers = {str(key).lower(): str(value) for key, value in self.headers.items()}
            path = urllib.parse.urlparse(self.path).path
            status, payload, content_type = dashboard.dispatch(method, path, body, headers)
            self._write(status, payload, content_type)

        def _write(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(payload)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def bind_host(value: str) -> str:
    if not is_loopback_host(value):
        raise SystemExit(
            "claude-or web only binds 127.0.0.1 / localhost / ::1. "
            "A LAN bind would expose key storage and profile writes. Use an SSH tunnel if you need remote access."
        )
    return value


def serve(host: str, port: int, *, open_browser: bool, home: Path | None = None) -> None:
    host = bind_host(host)
    dashboard = Dashboard(root=ROOT, host=host, port=port, home=home)
    candidates = list(range(port, port + 10)) if port == DEFAULT_PORT else [port]
    httpd = None
    last_error: OSError | None = None
    for candidate in candidates:
        try:
            httpd = Server((host, candidate), make_handler(dashboard))
            break
        except OSError as exc:
            last_error = exc
            httpd = None
    if httpd is None:
        raise SystemExit(f"claude-or web: cannot bind {host}:{port}: {last_error}")
    actual_host, actual_port = httpd.server_address[:2]
    dashboard.host = "127.0.0.1" if str(actual_host) in {"0.0.0.0", "::"} else str(actual_host)
    dashboard.port = int(actual_port)
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"claude-or web  {url}")
    print("loopback only. changes apply to the next `claude-or` launch, not a running session.")
    if open_browser:
        opener = "open" if sys.platform == "darwin" and shutil.which("open") else None
        if opener:
            subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nclaude-or web: stopped")
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local claude-or dashboard (loopback only)")
    parser.add_argument("--host", default="127.0.0.1", help="must be loopback")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args(argv)
    serve(args.host, args.port, open_browser=not args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
