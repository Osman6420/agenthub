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


# --- Streamable HTTP / SSE + session handshake (Phase 2.7 Part 2) -----------


class _RespH:
    """A fake response that also reports headers (Content-Type, Mcp-Session-Id)."""

    def __init__(
        self, status: int, body: bytes, *, content_type: str = "application/json", session: str = ""
    ) -> None:
        self.status = status
        self._body = body
        self._headers = {"Content-Type": content_type}
        if session:
            self._headers["Mcp-Session-Id"] = session

    def read(self, amount: int) -> bytes:
        return self._body[:amount]

    def getheader(self, name: str, default: str = "") -> str:
        return self._headers.get(name, default)


def _sse(*messages: Any) -> bytes:
    return b"".join((f"event: message\ndata: {json.dumps(m)}\n\n").encode() for m in messages)


def _sequence_factory(connections: list[_FakeConnection]):
    index = {"n": 0}

    def make(ip: str, port: int, timeout: float, server_hostname: str) -> _FakeConnection:
        conn = connections[index["n"]]
        index["n"] += 1
        return conn

    return make


def _session_request(**overrides: Any) -> ToolAdapterRequest:
    destination = ValidatedDestination(
        scheme="https",
        host="mcp.example.com",
        port=443,
        path_prefix="/mcp/search",
        ip_addresses=("93.184.216.34",),
        session_required=True,
    )
    return _request(destination=destination, **overrides)


def test_sse_response_is_parsed() -> None:
    result = {"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": {"status": "ok"}}}
    conn = _FakeConnection(_RespH(200, _sse(result), content_type="text/event-stream"))
    adapter = McpToolAdapter(connection_factory=_factory([], conn))
    assert adapter.call(_request()).body == {"status": "ok"}


def test_sse_ignores_notification_events_before_the_result() -> None:
    notif = {"jsonrpc": "2.0", "method": "notifications/message", "params": {}}
    result = {"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": {"ok": True}}}
    conn = _FakeConnection(_RespH(200, _sse(notif, result), content_type="text/event-stream"))
    adapter = McpToolAdapter(connection_factory=_factory([], conn))
    assert adapter.call(_request()).body == {"ok": True}


def test_sse_without_a_result_event_is_invalid() -> None:
    notif = {"jsonrpc": "2.0", "method": "notifications/message"}
    conn = _FakeConnection(_RespH(200, _sse(notif), content_type="text/event-stream"))
    adapter = McpToolAdapter(connection_factory=_factory([], conn))
    with pytest.raises(ToolAdapterError, match="MCP_RESULT_INVALID"):
        adapter.call(_request())


def test_session_handshake_initializes_then_calls_with_session_header() -> None:
    init = _FakeConnection(
        _RespH(200, _rpc({"serverInfo": {"name": "x"}, "capabilities": {}}), session="sess-123")
    )
    notified = _FakeConnection(_RespH(202, b""))
    called = _FakeConnection(_rpc_response({"structuredContent": {"status": "ok"}}))
    adapter = McpToolAdapter(connection_factory=_sequence_factory([init, notified, called]))

    assert adapter.call(_session_request()).body == {"status": "ok"}
    # 1) initialize first, no session header yet.
    assert json.loads(init.requests[0][2])["method"] == "initialize"
    # 2) notifications/initialized carries the captured session id.
    assert json.loads(notified.requests[0][2])["method"] == "notifications/initialized"
    assert notified.requests[0][3]["Mcp-Session-Id"] == "sess-123"
    # 3) tools/call carries the session id.
    assert json.loads(called.requests[0][2])["method"] == "tools/call"
    assert called.requests[0][3]["Mcp-Session-Id"] == "sess-123"


@pytest.mark.parametrize("session_id", ["", "bad session", "bad\r\nheader", "x" * 1025])
def test_session_required_rejects_missing_or_unsafe_session_id(session_id: str) -> None:
    init = _FakeConnection(
        _RespH(
            200,
            _rpc({"serverInfo": {"name": "x"}, "capabilities": {}}),
            session=session_id,
        )
    )
    adapter = McpToolAdapter(connection_factory=_sequence_factory([init]))

    with pytest.raises(ToolAdapterError, match="MCP_SESSION_INVALID"):
        adapter.call(_session_request())

    assert len(init.requests) == 1


def _rpc_response(result: Any) -> _RespH:
    return _RespH(200, _rpc(result))
