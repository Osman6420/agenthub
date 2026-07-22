"""Real MCP tool adapter: a bounded JSON-RPC ``tools/call`` over the SSRF-safe transport.

Reuses the pinned-IP / TLS-verified / bounded transport of the HTTP adapter, so the same
egress guarantees apply (HTTPS + public-IP only; loopback/private denied). The remote tool
name is the trailing segment of the pinned ``path_prefix``, keeping tool selection inside the
release-pinned, platform-reviewed destination.

Two MCP HTTP shapes are supported for the ``tools/call`` response:

- a single ``application/json`` JSON-RPC body, and
- an MCP **Streamable HTTP** ``text/event-stream`` (SSE) response, from which the single
  JSON-RPC result event is parsed under the same byte cap.

When the author pins ``destination.session: true`` the adapter performs the minimal MCP
session handshake (``initialize`` → capture ``Mcp-Session-Id`` → ``notifications/initialized``
→ ``tools/call`` with the session header). By default (no flag) it stays single-shot. The
connection factory is injectable so tests run fully offline.
"""

from __future__ import annotations

import json
import re
from typing import Any

from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterResponse
from apps.tools.http_adapter import (
    BoundedHttpResponse,
    ConnectionFactory,
    perform_bounded_https_request,
)

_PROTOCOL_VERSION = "2025-06-18"
_ACCEPT = "application/json, text/event-stream"
_SSE_EVENT_SEPARATOR = re.compile(r"\r?\n\r?\n")
_SESSION_ID = re.compile(r"[\x21-\x7e]{1,1024}\Z")


class McpToolAdapter:
    def __init__(self, *, connection_factory: ConnectionFactory | None = None) -> None:
        self._factory = connection_factory

    def call(self, request: ToolAdapterRequest) -> ToolAdapterResponse:
        if request.protocol != "mcp":
            raise ToolAdapterError("PROTOCOL_UNSUPPORTED")
        destination = request.destination
        path = destination.path_prefix or "/"
        tool_name = path.rstrip("/").rsplit("/", 1)[-1] or "invoke"

        session_id = ""
        if destination.session_required:
            session_id = self._handshake(request, path)

        message = self._read_message(
            self._post(
                request,
                path,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": request.payload},
                },
                session_id,
            )
        )
        result = self._result(message)
        if result.get("isError"):
            raise ToolAdapterError("MCP_TOOL_ERROR")
        structured = result.get("structuredContent")
        body_out = structured if isinstance(structured, dict) else result
        return ToolAdapterResponse(status_code=200, body=body_out)

    # --- session handshake (only when author-pinned) ------------------------

    def _handshake(self, request: ToolAdapterRequest, path: str) -> str:
        init = self._post(
            request,
            path,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "agenthub", "version": "1"},
                },
            },
            "",
        )
        session_id = init.session_id
        # The initialize response must itself be a valid JSON-RPC result (fail closed).
        self._result(self._read_message(init))
        # A destination marked session-required must never silently downgrade to the
        # single-shot path. Bound the upstream-controlled value to visible ASCII before
        # reflecting it into subsequent request headers.
        if _SESSION_ID.fullmatch(session_id) is None:
            raise ToolAdapterError("MCP_SESSION_INVALID")
        notify = self._post(
            request,
            path,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id,
        )
        if not 200 <= notify.status < 300:
            raise ToolAdapterError("UPSTREAM_STATUS")
        return session_id

    # --- transport + parsing ------------------------------------------------

    def _post(
        self, request: ToolAdapterRequest, path: str, envelope: dict[str, Any], session_id: str
    ) -> BoundedHttpResponse:
        destination = request.destination
        headers = {
            "Host": destination.host,
            "Content-Type": "application/json",
            "Accept": _ACCEPT,
        }
        if request.credential:
            headers["Authorization"] = f"Bearer {request.credential}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        factory = self._factory or _lazy_default_factory()
        return perform_bounded_https_request(
            factory, request, path=path, headers=headers, body=body
        )

    def _read_message(self, response: BoundedHttpResponse) -> dict[str, Any]:
        if not 200 <= response.status < 300:
            raise ToolAdapterError("UPSTREAM_STATUS")
        if "text/event-stream" in response.content_type.lower():
            message = _parse_sse(response.body)
        else:
            try:
                message = json.loads(response.body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise ToolAdapterError("RESPONSE_NOT_JSON") from exc
        if not isinstance(message, dict):
            raise ToolAdapterError("RESPONSE_NOT_OBJECT")
        if "error" in message:
            raise ToolAdapterError("MCP_ERROR")
        return message

    @staticmethod
    def _result(message: dict[str, Any]) -> dict[str, Any]:
        result = message.get("result")
        if not isinstance(result, dict):
            raise ToolAdapterError("MCP_RESULT_INVALID")
        return result


def _parse_sse(raw: bytes) -> dict[str, Any]:
    """Return the first JSON-RPC response message from a bounded SSE body.

    The body is already capped by ``max_response_bytes`` in the transport. Events are split on
    a blank line; ``data:`` lines within an event are concatenated (SSE framing) and parsed as
    JSON. The first event that is a JSON-RPC response (carries ``result`` or ``error``) wins;
    unrelated notification events are ignored.
    """
    text = raw.decode("utf-8", "replace")
    for block in _SSE_EVENT_SEPARATOR.split(text):
        data_parts = [
            line[len("data:") :].lstrip(" ")
            for line in block.splitlines()
            if line.startswith("data:")
        ]
        if not data_parts:
            continue
        try:
            message = json.loads("\n".join(data_parts))
        except ValueError:
            continue
        if isinstance(message, dict) and ("result" in message or "error" in message):
            return message
    raise ToolAdapterError("MCP_RESULT_INVALID")


def _lazy_default_factory() -> ConnectionFactory:
    from apps.tools.http_adapter import _default_connection_factory

    return _default_connection_factory
