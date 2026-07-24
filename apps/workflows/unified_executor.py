"""Default-off Run-native executor for a bounded side-effect-free workflow subset."""

from __future__ import annotations

import uuid
from typing import Any

import jsonschema
from django.conf import settings

from apps.releases.services import get_artifact_body_for_role
from apps.tenancy.context import set_tenant_context
from apps.workflows.background_claims import _validate_run_pins
from apps.workflows.compiler import COMPILED_WORKFLOW_API_VERSION
from apps.workflows.models import Run, RunCancellationState, WorkflowRunStatus
from apps.workflows.runtime import WorkflowRuntimeError, _execute_node, _validate_output_policy
from apps.workflows.services import WorkflowRequestError, _assert_state_size
from apps.workflows.transitions import RunTransitionResult, transition_run

_SUPPORTED_NODE_TYPES = frozenset(
    {"condition", "end", "format_output", "input", "validate_contract"}
)
_TRANSITION_NAMESPACE = uuid.UUID("d7297f29-2050-48d4-905b-a5f08971e900")


class UnifiedExecutorError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _transition_token(claim_token: uuid.UUID, purpose: str) -> uuid.UUID:
    return uuid.uuid5(_TRANSITION_NAMESPACE, f"{claim_token}:{purpose}")


def _validated_graph(
    graph: object,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], str]:
    if not isinstance(graph, dict) or graph.get("api_version") != COMPILED_WORKFLOW_API_VERSION:
        raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_VERSION_UNSUPPORTED")
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    input_node = graph.get("input_node")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list) or not isinstance(
        input_node, str
    ):
        raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_INVALID")
    nodes: dict[str, dict[str, Any]] = {}
    for item in raw_nodes:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or item.get("type") not in _SUPPORTED_NODE_TYPES
            or not isinstance(item.get("config"), dict)
            or item["id"] in nodes
        ):
            raise UnifiedExecutorError("RUN_EXECUTOR_NODE_UNSUPPORTED")
        nodes[item["id"]] = item
    if input_node not in nodes or nodes[input_node]["type"] != "input":
        raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_INVALID")
    outgoing: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in nodes}
    for edge in raw_edges:
        if (
            not isinstance(edge, dict)
            or edge.get("from") not in nodes
            or edge.get("to") not in nodes
            or "on_error" in edge
        ):
            raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        outgoing[str(edge["from"])].append(edge)
    for node_id, node in nodes.items():
        edges = outgoing[node_id]
        if node["type"] == "end":
            if edges:
                raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        elif node["type"] == "condition":
            if len(edges) != 2 or {edge.get("when") for edge in edges} != {True, False}:
                raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        elif len(edges) != 1:
            raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_UNBOUNDED")
        if node_id in visited:
            return
        visiting.add(node_id)
        for edge in outgoing[node_id]:
            visit(str(edge["to"]))
        visiting.remove(node_id)
        visited.add(node_id)

    visit(input_node)
    if visited != set(nodes):
        raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_INVALID")
    return nodes, outgoing, input_node


def _guard_transition(run: Run, claim_token: uuid.UUID) -> RunTransitionResult | None:
    run.refresh_from_db(
        fields=[
            "background_claim_checkpoint_version",
            "cancellation_state",
            "checkpoint_version",
            "deadline_at",
            "status",
        ]
    )
    if run.cancellation_state == RunCancellationState.REQUESTED:
        return transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=_transition_token(claim_token, "cancelled"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=str(run.status),
            target_status=WorkflowRunStatus.CANCELLED,
            reason_code="RUN_CANCELLATION_REQUESTED",
            background_claim_token=claim_token,
        )
    from django.utils import timezone

    if timezone.now() >= run.deadline_at:
        return transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=_transition_token(claim_token, "timed-out"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=str(run.status),
            target_status=WorkflowRunStatus.TIMED_OUT,
            reason_code="RUN_DEADLINE_EXCEEDED",
            background_claim_token=claim_token,
        )
    return None


def execute_claimed_bounded_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    claim_token: uuid.UUID,
) -> RunTransitionResult:
    """Execute one claimed graph without touching legacy WorkflowRun side tables."""

    if not bool(getattr(settings, "UNIFIED_BACKGROUND_EXECUTOR_ENABLED", False)):
        raise UnifiedExecutorError("RUN_EXECUTOR_DISABLED")
    set_tenant_context(organization_id)
    run = Run.objects.select_related("workflow_version", "release").get(
        pk=run_id,
        organization_id=organization_id,
    )
    _validate_run_pins(run)
    nodes, outgoing, current = _validated_graph(run.workflow_version.compiled_graph)
    started = transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=_transition_token(claim_token, "started"),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=WorkflowRunStatus.QUEUED,
        target_status=WorkflowRunStatus.RUNNING,
        background_claim_token=claim_token,
    )
    if started.outcome != "committed":
        return started
    run.refresh_from_db()
    state = dict(run.redacted_state)
    executed: list[str] = []
    try:
        while True:
            guarded = _guard_transition(run, claim_token)
            if guarded is not None:
                return guarded
            node = nodes[current]
            decision = _execute_node(
                node=node,
                state=state,
                release=run.release,
                run=run,
            )
            try:
                _assert_state_size(state)
            except WorkflowRequestError:
                raise WorkflowRuntimeError("WORKFLOW_STATE_TOO_LARGE") from None
            executed.append(current)
            if node["type"] == "end":
                break
            edges = outgoing[current]
            if node["type"] == "condition":
                current = next(edge["to"] for edge in edges if edge.get("when") is decision)
            else:
                current = edges[0]["to"]
        output = state.get("output")
        if not isinstance(output, dict):
            raise WorkflowRuntimeError("WORKFLOW_OUTPUT_MISSING")
        schema = get_artifact_body_for_role(run.release, "output_contract")
        if schema is not None:
            try:
                jsonschema.validate(output, schema)
            except jsonschema.ValidationError:
                raise WorkflowRuntimeError("OUTPUT_CONTRACT_VIOLATION") from None
        _validate_output_policy(run.release, output)
    except WorkflowRuntimeError as exc:
        run.refresh_from_db()
        return transition_run(
            organization_id=organization_id,
            run_id=run.id,
            transition_token=_transition_token(claim_token, "failed"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=WorkflowRunStatus.RUNNING,
            target_status=WorkflowRunStatus.FAILED,
            checkpoint=state,
            error_code=exc.code,
            step_delta=len(executed),
            background_claim_token=claim_token,
        )
    run.refresh_from_db()
    return transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=_transition_token(claim_token, "completed"),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=WorkflowRunStatus.RUNNING,
        target_status=WorkflowRunStatus.COMPLETED,
        checkpoint=state,
        step_delta=len(executed),
        background_claim_token=claim_token,
    )
