"""Transport-independent MCP operations using existing AgentHub policy seams."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any

import jsonschema

from apps.gateway.errors import ApiError, ErrorCode
from apps.gateway.views import InvokeView, QueryView
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.services import resolve_active_binding
from apps.ingestion.models import IngestionRun
from apps.mcp.schemas import TOOL_BY_NAME, TOOLS


@dataclass(frozen=True)
class McpRequestContext:
    request: Any
    consumer: Consumer
    request_id: str


def visible_tools(consumer: Consumer) -> list[dict[str, Any]]:
    """Return only tools backed by at least one granted capability."""
    capabilities: set[str] = set()
    for binding in consumer.bindings.filter(status="active").only("capabilities"):
        capabilities.update(binding.capabilities)
    allowed = {"agenthub__run_status"}
    if Capability.QUERY in capabilities:
        allowed.update({"agenthub__invoke", "agenthub__query"})
    if Capability.INGESTION_READ in capabilities:
        allowed.add("agenthub__ingestion_status")
    if consumer.protocol == ConsumerProtocol.MCP and Capability.RETRIEVE_DEBUG in capabilities:
        allowed.add("agenthub__retrieve_debug")
    return [tool for tool in TOOLS if tool["name"] in allowed]


def _validate(name: str, arguments: Any) -> dict[str, Any]:
    schema = TOOL_BY_NAME.get(name)
    if schema is None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Unknown MCP tool.",
            http_status_code=400,
        )
    if not isinstance(arguments, dict):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Tool arguments must be an object.",
            http_status_code=400,
        )
    try:
        jsonschema.validate(arguments, schema["inputSchema"])
    except jsonschema.ValidationError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Tool arguments do not match the MCP schema.",
            http_status_code=400,
            details=[{"path": [str(part) for part in exc.absolute_path]}],
        ) from None
    return arguments


def call_tool(name: str, arguments: Any, context: McpRequestContext) -> dict[str, Any]:
    args = _validate(name, arguments)
    if name == "agenthub__invoke":
        return _invoke(args, context, InvokeView(), "invoke")
    if name == "agenthub__query":
        payload: dict[str, Any] = {"query": args["query"]}
        if "conversation_id" in args:
            payload["conversation_id"] = args["conversation_id"]
        return _invoke(
            {"scenario_alias": args["scenario_alias"], "input": payload},
            context,
            QueryView(),
            "query",
        )
    if name == "agenthub__run_status":
        raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404)
    if name == "agenthub__ingestion_status":
        return _ingestion_status(args, context.consumer)
    if name == "agenthub__retrieve_debug":
        return _retrieve_debug(args, context)
    raise AssertionError("validated MCP tool has no handler")


def _invoke(
    args: dict[str, Any], context: McpRequestContext, view: Any, operation: str
) -> dict[str, Any]:
    # Reuse the gateway's authorization, Sprint 6 release routing, contract,
    # idempotency, runtime, usage, and success-audit path. No release/tenant is
    # accepted from MCP arguments.
    response = view._process(  # noqa: SLF001 - intentional shared policy seam
        context.request,
        context.consumer,
        context.request_id,
        args["scenario_alias"],
        args["input"],
    )
    result = dict(response.data)
    result["transport"] = "mcp"
    result["operation"] = operation
    return result


def _ingestion_status(args: dict[str, Any], consumer: Consumer) -> dict[str, Any]:
    runs = IngestionRun.objects.filter(source__organization_id=consumer.organization_id)
    if "run_id" in args:
        runs = runs.filter(pk=args["run_id"])
    run = runs.order_by("-created_at").first()
    if run is None:
        raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404)

    # Status access is capability-gated through a binding for the source's project.
    bindings = consumer.bindings.filter(status="active").only("capabilities")
    allowed = any(Capability.INGESTION_READ in binding.capabilities for binding in bindings)
    if not allowed:
        raise ApiError(
            ErrorCode.CAPABILITY_DENIED,
            "The request is not permitted.",
            http_status_code=403,
        )
    return {
        "run_id": run.id,
        "status": run.status,
        "source_id": run.source_id,
        "updated_at": run.updated_at.astimezone(UTC).isoformat(),
    }


def _retrieve_debug(args: dict[str, Any], context: McpRequestContext) -> dict[str, Any]:
    consumer = context.consumer
    # Debug is deliberately limited to MCP-designated internal consumers plus the
    # explicit capability. This is not inferred from a caller-supplied flag.
    if consumer.protocol != ConsumerProtocol.MCP:
        raise ApiError(
            ErrorCode.CAPABILITY_DENIED,
            "The request is not permitted.",
            http_status_code=403,
        )
    resolved = resolve_active_binding(
        organization_id=consumer.organization_id,
        subject=consumer.subject,
        alias=args["scenario_alias"],
    )
    if resolved is None or Capability.RETRIEVE_DEBUG not in resolved.capabilities:
        raise ApiError(
            ErrorCode.CAPABILITY_DENIED,
            "The request is not permitted.",
            http_status_code=403,
        )
    # Raw chunks are intentionally not returned in Sprint 7. This coarse response
    # proves authorization without widening confidential document exposure.
    return {"scenario_alias": args["scenario_alias"], "chunks": [], "redacted": True}
