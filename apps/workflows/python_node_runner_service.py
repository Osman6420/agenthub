"""Credentials-free, single-execution OpenShift Python-node runner supervisor.

The service is intentionally stdlib-only and stores no durable state. OpenShift supplies the
security boundary (restricted-v2, NetworkPolicy, resource limits and service-mesh transport); each
accepted request is executed by a fresh isolated Python process with a scrubbed environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 400_000
MAX_SOURCE_BYTES = 32_768
MAX_OUTPUT_BYTES = 262_144
MAX_WALL_MILLISECONDS = 30_000
ALLOWED_MODULES = frozenset({"decimal", "fractions", "math", "statistics"})
MAX_EXECUTIONS = int(os.environ.get("PYTHON_NODE_RUNNER_MAX_EXECUTIONS", "20"))
MAX_AGE_SECONDS = int(os.environ.get("PYTHON_NODE_RUNNER_MAX_AGE_SECONDS", "900"))
STARTED_AT = time.monotonic()
EXECUTION_LOCK = threading.Lock()
EXECUTION_COUNT = 0


class RunnerHandler(BaseHTTPRequestHandler):
    server_version = "agenthub-python-runner/v1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/live":
            self._send(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/ready":
            ready = not _recycle_due() and not EXECUTION_LOCK.locked()
            self._send(
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                {"status": "ready" if ready else "unavailable"},
            )
            return
        self._send(HTTPStatus.NOT_FOUND, {"status": "error", "code": "NOT_FOUND"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/execute":
            self._send(HTTPStatus.NOT_FOUND, {"status": "error", "code": "NOT_FOUND"})
            return
        if _recycle_due() or not EXECUTION_LOCK.acquire(blocking=False):
            self._send(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"status": "error", "code": "PYTHON_NODE_RUNNER_CAPACITY"},
            )
            return
        try:
            request = self._read_request()
            response = _execute(request)
            self._send(HTTPStatus.OK, response)
        except RunnerRequestError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"status": "error", "code": exc.code})
        finally:
            global EXECUTION_COUNT
            EXECUTION_COUNT += 1
            EXECUTION_LOCK.release()
            if _recycle_due():
                threading.Thread(target=_exit_after_response, daemon=True).start()

    def _read_request(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise RunnerRequestError("PYTHON_NODE_PROTOCOL_INVALID") from None
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise RunnerRequestError("PYTHON_NODE_REQUEST_TOO_LARGE")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RunnerRequestError("PYTHON_NODE_PROTOCOL_INVALID") from None
        if not isinstance(value, dict) or value.get("protocol_version") != "python-node-runner/v1":
            raise RunnerRequestError("PYTHON_NODE_PROTOCOL_INVALID")
        return value

    def _send(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args  # never log tenant-controlled paths, source or payloads


class RunnerRequestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _execute(request: dict[str, Any]) -> dict[str, Any]:
    try:
        wall_ms = int(request["wall_milliseconds"])
        memory_bytes = int(request["memory_bytes"])
        output_bytes = int(request["output_bytes"])
        source = request["source"]
        config = request["config"]
        input_payload = request["input"]
        requested_modules = request["requested_modules"]
        idempotency_key = request["idempotency_key"]
        expires_at_unix_ms = int(request["expires_at_unix_ms"])
    except (KeyError, TypeError, ValueError):
        raise RunnerRequestError("PYTHON_NODE_PROTOCOL_INVALID") from None
    if (
        not isinstance(source, str)
        or len(source.encode("utf-8")) > MAX_SOURCE_BYTES
        or not isinstance(config, dict)
        or not isinstance(input_payload, dict)
        or not isinstance(requested_modules, list)
        or not all(isinstance(item, str) for item in requested_modules)
        or not set(requested_modules).issubset(ALLOWED_MODULES)
        or not isinstance(idempotency_key, str)
        or not 1 <= len(idempotency_key) <= 200
        or not int(time.time() * 1000) <= expires_at_unix_ms <= int((time.time() + 60) * 1000)
        or not 1 <= wall_ms <= MAX_WALL_MILLISECONDS
        or not 1 <= output_bytes <= MAX_OUTPUT_BYTES
        or not 16 * 1024 * 1024 <= memory_bytes <= 256 * 1024 * 1024
    ):
        raise RunnerRequestError("PYTHON_NODE_PROTOCOL_INVALID")
    worker = Path(__file__).with_name("python_node_worker.py")
    worker_request = json.dumps(
        {
            "source": source,
            "config": config,
            "input": input_payload,
            "memory_bytes": memory_bytes,
            "output_bytes": output_bytes,
            "requested_modules": requested_modules,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    idempotency_checksum = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    try:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-I", str(worker)],
            input=worker_request,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=wall_ms / 1000,
            check=False,
            env={"PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "code": "PYTHON_NODE_TIMEOUT",
            "idempotency_checksum": idempotency_checksum,
        }
    if len(completed.stdout) > output_bytes + 256:
        return {
            "status": "error",
            "code": "PYTHON_NODE_OUTPUT_LIMIT",
            "idempotency_checksum": idempotency_checksum,
        }
    try:
        response = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "error",
            "code": "PYTHON_NODE_PROTOCOL_INVALID",
            "idempotency_checksum": idempotency_checksum,
        }
    if completed.returncode != 0 or not isinstance(response, dict):
        return {
            "status": "error",
            "code": "PYTHON_NODE_RUNNER_FAILED",
            "idempotency_checksum": idempotency_checksum,
        }
    response["idempotency_checksum"] = idempotency_checksum
    return response


def _recycle_due() -> bool:
    return EXECUTION_COUNT >= MAX_EXECUTIONS or time.monotonic() - STARTED_AT >= MAX_AGE_SECONDS


def _exit_after_response() -> None:
    time.sleep(0.1)
    os._exit(0)


def main() -> None:
    # The Service/NetworkPolicy is the ingress boundary; no Route exposes this listener.
    host = os.environ.get("PYTHON_NODE_RUNNER_HOST", "0.0.0.0")  # noqa: S104
    port = int(os.environ.get("PYTHON_NODE_RUNNER_PORT", "8080"))
    ThreadingHTTPServer((host, port), RunnerHandler).serve_forever()


if __name__ == "__main__":
    main()
