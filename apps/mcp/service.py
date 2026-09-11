"""Transport-independent MCP operations using existing AgentHub policy seams."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any

import jsonschema
from django.db import transaction
from django.db.models import Exists, OuterRef

from apps.documents.models import ScenarioDocumentSetBinding
from apps.documents.retrieve_scope import live_consumer_scenario_grants
from apps.gateway.errors import ApiError, ErrorCode
from apps.gateway.views import ResponsesView
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.services import resolve_active_binding
from apps.ingestion.models import IngestionRun
from apps.mcp.schemas import TOOL_BY_NAME, TOOLS
from apps.tenancy.context import set_tenant_context


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
    if Capability.WORKFLOW_RUN in capabilities:
        allowed.add("agenthub__responses")
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
    if name == "agenthub__responses":
        return _responses(args, context)
    if name == "agenthub__run_status":
        return _run_status(args, context)
    if name == "agenthub__ingestion_status":
        return _ingestion_status(args, context.consumer)
    if name == "agenthub__retrieve_debug":
        return _retrieve_debug(args, context)
    raise AssertionError("validated MCP tool has no handler")


def _responses(args: dict[str, Any], context: McpRequestContext) -> dict[str, Any]:
    """Reuse canonical admission/execution without accepting tenant or release authority."""

    class _McpResponsesView(ResponsesView):
        required_protocol = ConsumerProtocol.MCP

    view = _McpResponsesView()
    view._idempotency_key = args["idempotency_key"]  # noqa: SLF001
    request_body = {
        "model": args["model"],
        "input": args["input"],
        "background": args.get("background", False),
    }
    original_data = context.request._full_data  # noqa: SLF001
    context.request._full_data = request_body  # noqa: SLF001
    try:
        admitted = view._admit(context.request)  # noqa: SLF001
        if args.get("background", False):
            body = dict(admitted.data)
            body["_http_status"] = admitted.status_code
            result = view._adapt_success(body)  # noqa: SLF001
        else:
            response = view._complete_sync_run(context.request, admitted)  # noqa: SLF001
            result = dict(response.data)
    finally:
        context.request._full_data = original_data  # noqa: SLF001
    result["transport"] = "mcp"
    result["operation"] = "responses"
    return result


def _run_status(args: dict[str, Any], context: McpRequestContext) -> dict[str, Any]:
    from uuid import UUID

    from apps.tenancy.context import set_tenant_context
    from apps.workflows.models import Run, RunStatus

    try:
        run_id = UUID(args["run_id"])
    except (TypeError, ValueError):
        raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404) from None
    set_tenant_context(context.consumer.organization_id)
    run = Run.objects.filter(
        pk=run_id,
        organization_id=context.consumer.organization_id,
        consumer=context.consumer,
    ).first()
    if run is None:
        raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404)
    result: dict[str, Any] = {
        "run_id": str(run.id),
        "response_id": run.response_id,
        "status": str(run.status),
        "release_id": run.release_id,
    }
    output = run.redacted_state.get("output")
    if run.status == RunStatus.COMPLETED and isinstance(output, dict):
        result["output"] = output
    return result


@transaction.atomic
def _ingestion_status(args: dict[str, Any], consumer: Consumer) -> dict[str, Any]:
    set_tenant_context(consumer.organization_id)
    scenario_ids = [
        scenario_id
        for scenario_id, capabilities in consumer.bindings.filter(
            organization_id=consumer.organization_id,
            status="active",
            consumer__status="active",
            consumer__organization__status="active",
            scenario__project__organization_id=consumer.organization_id,
        ).values_list("scenario_id", "capabilities")
        if Capability.INGESTION_READ in capabilities
    ]
    # Correlate both keys: a grant for another scenario must not authorize this
    # binding, even when both scenarios belong to the same project.
    scenario_grants = live_consumer_scenario_grants(
        consumer=consumer,
        scenario_ids=scenario_ids,
    ).filter(
        scenario_id=OuterRef("scenario_id"),
        document_set_id=OuterRef("document_set_id"),
    )
    document_sets = ScenarioDocumentSetBinding.objects.filter(
        organization_id=consumer.organization_id,
        scenario_id__in=scenario_ids,
        document_set__organization_id=consumer.organization_id,
    ).filter(Exists(scenario_grants))
    runs = IngestionRun.objects.filter(
        organization_id=consumer.organization_id,
        source__organization_id=consumer.organization_id,
        source__document_set_id__in=document_sets.values("document_set_id"),
    )
    if "run_id" in args:
        runs = runs.filter(pk=args["run_id"])
    run = runs.order_by("-created_at", "-pk").first()
    if run is None:
        raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404)

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
