"""Real MCP tool adapter: a bounded JSON-RPC ``tools/call`` over HTTPS.

Reuses the SSRF-safe pinned-IP / TLS-verified transport of the HTTP adapter, so the
same egress guarantees apply. The remote tool name is taken from the trailing segment
of the destination ``path_prefix`` (the pinned MCP endpoint), keeping tool selection
inside the release-pinned, platform-reviewed destination. Enabled only when tool egress
is configured; the connection factory is injectable so tests run fully offline.
"""

from __future__ import annotations

import json
from typing import Any

from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterResponse
from apps.tools.http_adapter import ConnectionFactory, perform_https_post


class McpToolAdapter:
    def __init__(self, *, connection_factory: ConnectionFactory | None = None) -> None:
        self._factory = connection_factory

    def call(self, request: ToolAdapterRequest) -> ToolAdapterResponse:
        if request.protocol != "mcp":
            raise ToolAdapterError("PROTOCOL_UNSUPPORTED")
        destination = request.destination
        path = destination.path_prefix or "/"
        tool_name = path.rstrip("/").rsplit("/", 1)[-1] or "invoke"
        headers = {
            "Host": destination.host,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if request.credential:
            headers["Authorization"] = f"Bearer {request.credential}"
        envelope = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": request.payload},
        }
        body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")

        factory = self._factory or _lazy_default_factory()
        raw = perform_https_post(factory, request, path=path, headers=headers, body=body)
        try:
            parsed: Any = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ToolAdapterError("RESPONSE_NOT_JSON") from exc
        if not isinstance(parsed, dict):
            raise ToolAdapterError("RESPONSE_NOT_OBJECT")
        if "error" in parsed:
            raise ToolAdapterError("MCP_ERROR")
        result = parsed.get("result")
        if not isinstance(result, dict):
            raise ToolAdapterError("MCP_RESULT_INVALID")
        if result.get("isError"):
            raise ToolAdapterError("MCP_TOOL_ERROR")
        structured = result.get("structuredContent")
        body_out = structured if isinstance(structured, dict) else result
        return ToolAdapterResponse(status_code=200, body=body_out)


def _lazy_default_factory() -> ConnectionFactory:
    from apps.tools.http_adapter import _default_connection_factory

    return _default_connection_factory
