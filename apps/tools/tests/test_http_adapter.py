"""HttpToolAdapter request-building and response-handling (fully offline)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterUncertain
from apps.tools.egress import ValidatedDestination
from apps.tools.http_adapter import HttpToolAdapter


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


class _FakeConnection:
    def __init__(self, response: Any = None, raise_exc: Exception | None = None) -> None:
        self.requests: list[tuple[Any, ...]] = []
        self._response = response
        self._raise = raise_exc
        self.closed = False

    def request(
        self, method: str, url: str, body: bytes | None = None, headers: Any = None
    ) -> None:
        self.requests.append((method, url, body, headers))
        if self._raise is not None:
            raise self._raise

    def getresponse(self) -> Any:
        return self._response

    def close(self) -> None:
        self.closed = True


def _factory(capture: list, connection: _FakeConnection):
    def make(ip: str, port: int, timeout: float, server_hostname: str):
        capture.append((ip, port, timeout, server_hostname))
        return connection

    return make


def _dest(**overrides: Any) -> ValidatedDestination:
    base: dict[str, Any] = {
        "scheme": "https",
        "host": "api.example.com",
        "port": 443,
        "path_prefix": "/v1",
        "ip_addresses": ("93.184.216.34",),
    }
    base.update(overrides)
    return ValidatedDestination(**base)


def _request(**overrides: Any) -> ToolAdapterRequest:
    base: dict[str, Any] = {
        "protocol": "http",
        "method": "POST",
        "destination": _dest(),
        "payload": {"query": "hi"},
        "credential": "tok",  # noqa: S106
        "timeout_seconds": 5,
        "max_response_bytes": 1000,
    }
    base.update(overrides)
    return ToolAdapterRequest(**base)


def test_success_connects_to_validated_ip_and_sends_host_and_auth() -> None:
    conn = _FakeConnection(_FakeResponse(200, b'{"status":"ok"}'))
    capture: list = []
    adapter = HttpToolAdapter(connection_factory=_factory(capture, conn))
    response = adapter.call(_request())

    assert response.status_code == 200
    assert response.body == {"status": "ok"}
    # Dials the validated IP, but verifies TLS/Host for the original hostname.
    assert capture[0] == ("93.184.216.34", 443, 5.0, "api.example.com")
    method, url, body, headers = conn.requests[0]
    assert method == "POST"
    assert url == "/v1"
    assert headers["Host"] == "api.example.com"
    assert headers["Authorization"] == "Bearer tok"
    assert json.loads(body) == {"query": "hi"}
    assert conn.closed is True


def test_no_credential_omits_authorization_header() -> None:
    conn = _FakeConnection(_FakeResponse(200, b"{}"))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    adapter.call(_request(credential=None))
    _, _, _, headers = conn.requests[0]
    assert "Authorization" not in headers


def test_redirect_is_not_followed() -> None:
    conn = _FakeConnection(_FakeResponse(302, b""))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="REDIRECT_NOT_ALLOWED"):
        adapter.call(_request())


def test_non_2xx_status_is_error() -> None:
    conn = _FakeConnection(_FakeResponse(500, b"{}"))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="UPSTREAM_STATUS"):
        adapter.call(_request())


def test_oversized_response_is_denied() -> None:
    conn = _FakeConnection(_FakeResponse(200, b'{"status":"loooong"}'))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="RESPONSE_TOO_LARGE"):
        adapter.call(_request(max_response_bytes=5))


def test_non_json_response_is_error() -> None:
    conn = _FakeConnection(_FakeResponse(200, b"not json"))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="RESPONSE_NOT_JSON"):
        adapter.call(_request())


def test_non_object_json_is_error() -> None:
    conn = _FakeConnection(_FakeResponse(200, b"[1, 2, 3]"))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="RESPONSE_NOT_OBJECT"):
        adapter.call(_request())


def test_timeout_after_dispatch_is_uncertain() -> None:
    conn = _FakeConnection(raise_exc=TimeoutError("read timed out"))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterUncertain):
        adapter.call(_request())


def test_connection_error_is_failed() -> None:
    conn = _FakeConnection(raise_exc=OSError("connection refused"))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="CONNECTION_FAILED"):
        adapter.call(_request())


def test_mcp_protocol_is_unsupported_by_http_adapter() -> None:
    conn = _FakeConnection(_FakeResponse(200, b"{}"))
    adapter = HttpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="PROTOCOL_UNSUPPORTED"):
        adapter.call(_request(protocol="mcp"))
