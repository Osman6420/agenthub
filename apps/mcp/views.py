"""Stateless MCP Streamable HTTP JSON-RPC endpoint."""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record_event
from apps.gateway.errors import ApiError
from apps.mcp.service import McpRequestContext, call_tool, visible_tools

_JSONRPC = "2.0"


def _depth(value: Any, current: int = 0) -> int:
    if isinstance(value, dict):
        return max((_depth(item, current + 1) for item in value.values()), default=current)
    if isinstance(value, list):
        return max((_depth(item, current + 1) for item in value), default=current)
    return current


class McpView(APIView):
    """Authenticated stateless subset of MCP Streamable HTTP."""

    def post(self, request: Request) -> Response:
        if not settings.MCP_ENABLED:
            return self._rpc_error(None, -32601, "MCP ingress is disabled.", status=404)
        origin = request.headers.get("Origin")
        if origin and origin not in settings.MCP_ALLOWED_ORIGINS:
            return self._rpc_error(None, -32000, "Origin is not allowed.", status=403)
        requested_version = request.headers.get("MCP-Protocol-Version")
        if requested_version and requested_version != settings.MCP_PROTOCOL_VERSION:
            return self._rpc_error(None, -32600, "Unsupported protocol version.", status=400)
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        if content_length > settings.MCP_MAX_REQUEST_BYTES:
            return self._rpc_error(None, -32600, "Request is too large.", status=413)

        body = request.data
        request_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(body, dict) or _depth(body) > settings.MCP_MAX_NESTING_DEPTH:
            return self._rpc_error(request_id, -32600, "Invalid Request.", status=400)
        if body.get("jsonrpc") != _JSONRPC or not isinstance(body.get("method"), str):
            return self._rpc_error(request_id, -32600, "Invalid Request.", status=400)

        method = body["method"]
        if method == "initialize":
            return self._result(
                request_id,
                {
                    "protocolVersion": settings.MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "agenthub", "version": "0.0.0"},
                },
            )
        if method == "ping":
            return self._result(request_id, {})
        if method == "notifications/initialized":
            return Response(status=202)
        if method == "tools/list":
            return self._result(request_id, {"tools": visible_tools(request.auth)})
        if method != "tools/call":
            return self._rpc_error(request_id, -32601, "Method not found.", status=404)

        params = body.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return self._rpc_error(request_id, -32602, "Invalid params.", status=400)
        consumer = request.auth
        try:
            result = call_tool(
                params["name"],
                params.get("arguments", {}),
                McpRequestContext(
                    request=request,
                    consumer=consumer,
                    request_id=getattr(request, "request_id", ""),
                ),
            )
        except ApiError as exc:
            record_event(
                actor_type="consumer",
                actor_id=consumer.subject,
                action="mcp.tools.call",
                outcome="deny",
                organization_id=consumer.organization_id,
                resource_type="mcp_tool",
                resource_id=params["name"],
                reason=exc.code,
                request_id=getattr(request, "request_id", ""),
            )
            return self._result(
                request_id,
                {
                    "content": [{"type": "text", "text": exc.message}],
                    "structuredContent": {"error": {"code": exc.code, "retryable": exc.retryable}},
                    "isError": True,
                },
                status=exc.http_status_code,
            )
        return self._result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}],
                "structuredContent": result,
                "isError": False,
            },
        )

    @staticmethod
    def _result(request_id: Any, result: Any, status: int = 200) -> Response:
        return Response(
            {"jsonrpc": _JSONRPC, "id": request_id, "result": result},
            status=status,
            headers={"MCP-Protocol-Version": settings.MCP_PROTOCOL_VERSION},
        )

    @staticmethod
    def _rpc_error(request_id: Any, code: int, message: str, status: int) -> Response:
        return Response(
            {"jsonrpc": _JSONRPC, "id": request_id, "error": {"code": code, "message": message}},
            status=status,
            headers={"MCP-Protocol-Version": settings.MCP_PROTOCOL_VERSION},
        )
