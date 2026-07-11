"""McpToolAdapter JSON-RPC request-building and result parsing (offline)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest
from apps.tools.egress import ValidatedDestination
from apps.tools.mcp_adapter import McpToolAdapter


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


class _FakeConnection:
    def __init__(self, response: Any) -> None:
        self.requests: list[tuple[Any, ...]] = []
        self._response = response

    def request(
        self, method: str, url: str, body: bytes | None = None, headers: Any = None
    ) -> None:
        self.requests.append((method, url, body, headers))

    def getresponse(self) -> Any:
        return self._response

    def close(self) -> None:
        pass


def _factory(capture: list, connection: _FakeConnection):
    def make(ip: str, port: int, timeout: float, server_hostname: str):
        capture.append((ip, port, timeout, server_hostname))
        return connection

    return make


def _request(**overrides: Any) -> ToolAdapterRequest:
    destination = ValidatedDestination(
        scheme="https",
        host="mcp.example.com",
        port=443,
        path_prefix="/mcp/search",
        ip_addresses=("93.184.216.34",),
    )
    base: dict[str, Any] = {
        "protocol": "mcp",
        "method": None,
        "destination": destination,
        "payload": {"query": "hi"},
        "credential": "tok",  # noqa: S106
        "timeout_seconds": 5,
        "max_response_bytes": 1000,
    }
    base.update(overrides)
    return ToolAdapterRequest(**base)


def _rpc(result: Any) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode("utf-8")


def test_success_returns_structured_content_and_calls_tools_call() -> None:
    conn = _FakeConnection(
        _FakeResponse(200, _rpc({"isError": False, "structuredContent": {"status": "ok"}}))
    )
    capture: list = []
    adapter = McpToolAdapter(connection_factory=_factory(capture, conn))
    response = adapter.call(_request())

    assert response.body == {"status": "ok"}
    assert capture[0] == ("93.184.216.34", 443, 5.0, "mcp.example.com")
    _, url, body, headers = conn.requests[0]
    assert url == "/mcp/search"
    assert headers["Authorization"] == "Bearer tok"
    sent = json.loads(body)
    assert sent["method"] == "tools/call"
    assert sent["params"]["name"] == "search"  # trailing path segment
    assert sent["params"]["arguments"] == {"query": "hi"}


def test_structured_content_absent_returns_full_result() -> None:
    conn = _FakeConnection(_FakeResponse(200, _rpc({"isError": False, "status": "ok"})))
    adapter = McpToolAdapter(connection_factory=_factory([], conn))
    response = adapter.call(_request())
    assert response.body == {"isError": False, "status": "ok"}


def test_jsonrpc_error_is_rejected() -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "x"}})
    conn = _FakeConnection(_FakeResponse(200, body.encode("utf-8")))
    adapter = McpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="MCP_ERROR"):
        adapter.call(_request())


def test_tool_error_flag_is_rejected() -> None:
    conn = _FakeConnection(_FakeResponse(200, _rpc({"isError": True})))
    adapter = McpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="MCP_TOOL_ERROR"):
        adapter.call(_request())


def test_result_not_object_is_rejected() -> None:
    conn = _FakeConnection(_FakeResponse(200, _rpc("nope")))
    adapter = McpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="MCP_RESULT_INVALID"):
        adapter.call(_request())


def test_non_mcp_protocol_is_unsupported() -> None:
    conn = _FakeConnection(_FakeResponse(200, _rpc({})))
    adapter = McpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="PROTOCOL_UNSUPPORTED"):
        adapter.call(_request(protocol="http"))
