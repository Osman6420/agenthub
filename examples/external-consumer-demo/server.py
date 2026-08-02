"""Loopback-only static server and narrow AgentHub reverse proxy for the demo UI."""

from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MAX_REQUEST_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 2_000_000
RUN_PATH = re.compile(r"^/v1/runs/[0-9a-fA-F-]{36}(?:/cancel)?$")
POST_PATHS = {"/v1/responses", "/v1/chat/completions"}


def load_credentials(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("consumers"), dict):
        raise ValueError("credentials file is invalid")
    base = urlsplit(str(value.get("api_base", "")))
    if base.scheme != "http" or base.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("api_base must be loopback HTTP")
    if base.port not in {8000, None} or base.path not in {"", "/"}:
        raise ValueError("api_base must target the local AgentHub gateway")
    return value


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "AgentHubExternalDemo/1.0"

    @property
    def config(self) -> dict:
        return self.server.config  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:
        # Default logging includes only method/path/status; no request headers or bodies.
        super().log_message(fmt, *args)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/demo-config":
            consumers = {
                key: {
                    "subject": entry.get("subject", ""),
                    "scenarios": entry.get("scenarios", []),
                }
                for key, entry in self.config["consumers"].items()
                if isinstance(entry, dict)
            }
            self._json(
                HTTPStatus.OK,
                {"consumers": consumers, "wikipedia": self.config.get("wikipedia", {})},
            )
            return
        if self.path.startswith("/proxy"):
            self._proxy("GET")
            return
        relative = "index.html" if self.path in {"", "/"} else self.path.lstrip("/")
        if relative not in {"index.html", "app.js", "styles.css"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        target = (ROOT / relative).resolve()
        if target.parent != ROOT or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/proxy"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._proxy("POST")

    def _proxy(self, method: str) -> None:
        upstream_path = self.path.removeprefix("/proxy")
        post_denied = (
            method == "POST"
            and upstream_path not in POST_PATHS
            and not RUN_PATH.fullmatch(upstream_path)
        )
        if post_denied:
            self._json(HTTPStatus.NOT_FOUND, {"error": "proxy_path_denied"})
            return
        if method == "GET" and not RUN_PATH.fullmatch(upstream_path):
            self._json(HTTPStatus.NOT_FOUND, {"error": "proxy_path_denied"})
            return
        consumer_key = self.headers.get("X-Demo-Consumer", "")
        entry = self.config["consumers"].get(consumer_key)
        if not isinstance(entry, dict) or not isinstance(entry.get("token"), str):
            self._json(HTTPStatus.FORBIDDEN, {"error": "consumer_denied"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = MAX_REQUEST_BYTES + 1
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request_too_large"})
            return
        request_body = self.rfile.read(length) if length else None
        headers = {
            "Authorization": f"Bearer {entry['token']}",
            "Accept": "application/json",
        }
        if request_body is not None:
            headers["Content-Type"] = "application/json"
        idempotency = self.headers.get("Idempotency-Key", "")
        idempotency_valid = (
            idempotency
            and len(idempotency) <= 128
            and all(ch.isalnum() or ch in "._:-" for ch in idempotency)
        )
        if idempotency_valid:
            headers["Idempotency-Key"] = idempotency
        connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=65)
        try:
            connection.request(method, upstream_path, body=request_body, headers=headers)
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                self._json(HTTPStatus.BAD_GATEWAY, {"error": "upstream_response_too_large"})
                return
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            run_id = response.getheader("X-AgentHub-Run-Id")
            if run_id:
                self.send_header("X-AgentHub-Run-Id", run_id)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (OSError, TimeoutError, http.client.HTTPException):
            self._json(HTTPStatus.BAD_GATEWAY, {"error": "agenthub_unavailable"})
        finally:
            connection.close()

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", default=str(ROOT / "credentials.local.json"))
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port must be between 1024 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    server.config = load_credentials(Path(args.credentials).resolve())  # type: ignore[attr-defined]
    print(f"External demo: http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
