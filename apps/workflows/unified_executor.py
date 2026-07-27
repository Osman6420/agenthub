"""Default-off Run-native executor for a bounded side-effect-free workflow subset."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import jsonschema
from django.conf import settings
from django.utils import timezone

from apps.releases.services import get_artifact_body_for_role
from apps.tenancy.context import set_tenant_context
from apps.workflows.background_claims import (
    _validate_run_pins,
    claim_background_run,
    parse_background_delivery,
    resolve_expired_background_claim,
)
from apps.workflows.compiler import COMPILED_WORKFLOW_API_VERSION
from apps.workflows.models import Run, RunAwaitingKind, RunCancellationState, WorkflowRunStatus
from apps.workflows.run_waits import RunWaitError, suspend_run_for_wait
from apps.workflows.runtime import WorkflowRuntimeError, _execute_node, _validate_output_policy
from apps.workflows.services import WorkflowRequestError, _assert_state_size
from apps.workflows.transitions import RunTransitionResult, transition_run

_WAIT_KIND_BY_NODE_TYPE = {
    "event_wait": RunAwaitingKind.EVENT,
    "human_task": RunAwaitingKind.HUMAN,
    "timer": RunAwaitingKind.TIMER,
}
_SUPPORTED_NODE_TYPES = frozenset(
    {"condition", "end", "format_output", "input", "validate_contract", *_WAIT_KIND_BY_NODE_TYPE}
)
_TRANSITION_NAMESPACE = uuid.UUID("d7297f29-2050-48d4-905b-a5f08971e900")

# Server-owned resume cursor. It lives in the checkpoint rather than a column so a durable pause
# needs no schema change, and it is unforgeable: an ``output_mapping`` may only write the six
# business roots, and the executor pops it before any node runs and rewrites it at suspension.
_CURSOR_KEY = "__resume_node"


class UnifiedExecutorError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RunExecution:
    """One execution outcome, plus the one-shot authority a durable pause issued."""

    outcome: str
    status: str
    checkpoint_version: int
    wait_id: uuid.UUID | None = None
    resume_token: uuid.UUID | None = None


def _execution(result: RunTransitionResult) -> RunExecution:
    return RunExecution(result.outcome, result.status, result.checkpoint_version)


def service_revision() -> str:
    return os.environ.get("AGENTHUB_SERVICE_REVISION", "development")[:64] or "development"


def _transition_token(claim_token: uuid.UUID, purpose: str) -> uuid.UUID:
    return uuid.uuid5(_TRANSITION_NAMESPACE, f"{claim_token}:{purpose}")


def _wait_node_supported(node: dict[str, Any]) -> bool:
    config = node["config"]
    if node["type"] == "human_task" and (
        # RunWait carries no escalation policy, so an authored escalation would be silently
        # dropped. Refuse the graph instead of weakening the authored control.
        config.get("escalation_role") or config.get("escalation_timeout_seconds")
    ):
        return False
    duration = "delay_seconds" if node["type"] == "timer" else "timeout_seconds"
    return isinstance(config.get(duration), int) and config[duration] > 0


def _validated_graph(
    graph: object,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], str]:
    if not isinstance(graph, dict) or graph.get("api_version") != COMPILED_WORKFLOW_API_VERSION:
        raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_VERSION_UNSUPPORTED")
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    input_node = graph.get("input_node")
    if (
        not isinstance(raw_nodes, list)
        or not isinstance(raw_edges, list)
        or not isinstance(input_node, str)
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
        if item["type"] in _WAIT_KIND_BY_NODE_TYPE and not _wait_node_supported(item):
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


def _wait_arguments(node: dict[str, Any]) -> dict[str, Any]:
    """Translate one compiled wait node into the durable-wait contract."""

    config = node["config"]
    node_type = node["type"]
    schema: dict[str, Any]
    roles: list[str]
    if node_type == "timer":
        seconds, schema, roles = int(config["delay_seconds"]), {}, []
    elif node_type == "event_wait":
        seconds = int(config["timeout_seconds"])
        schema, roles = config.get("payload_schema") or {}, []
    else:
        seconds = int(config["timeout_seconds"])
        schema = config.get("decision_schema") or {}
        roles = list(config.get("allowed_decision_roles") or [])
    return {
        "kind": _WAIT_KIND_BY_NODE_TYPE[node_type],
        "node_id": str(node["id"]),
        "deadline_at": timezone.now() + timedelta(seconds=seconds),
        "payload_schema": schema,
        "output_mapping": list(node.get("output_mapping", [])),
        "allowed_roles": roles,
        "deny_self_decision": bool(config.get("deny_self_decision", True)),
    }


def _suspend_at_wait(
    *,
    run: Run,
    node: dict[str, Any],
    state: dict[str, Any],
    resume_node: str,
    claim_token: uuid.UUID,
    step_delta: int,
) -> RunExecution:
    """Checkpoint the resume position and hand the Run to a durable wait authority."""

    run.refresh_from_db()
    try:
        creation = suspend_run_for_wait(
            organization_id=run.organization_id,
            run_id=run.id,
            claim_token=claim_token,
            expected_checkpoint_version=run.checkpoint_version,
            checkpoint={**state, _CURSOR_KEY: resume_node},
            step_delta=step_delta,
            **_wait_arguments(node),
        )
    except RunWaitError as exc:
        raise WorkflowRuntimeError(exc.code) from None
    return RunExecution(
        creation.outcome,
        creation.status,
        creation.checkpoint_version,
        creation.wait_id,
        creation.resume_token,
    )


def execute_claimed_bounded_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    claim_token: uuid.UUID,
) -> RunExecution:
    """Execute one claimed graph without touching legacy WorkflowRun side tables."""

    if not bool(getattr(settings, "UNIFIED_BACKGROUND_EXECUTOR_ENABLED", False)):
        raise UnifiedExecutorError("RUN_EXECUTOR_DISABLED")
    set_tenant_context(organization_id)
    run = Run.objects.select_related("workflow_version", "release").get(
        pk=run_id,
        organization_id=organization_id,
    )
    _validate_run_pins(run)
    if (
        run.background_claim_token != claim_token
        or run.background_claim_checkpoint_version != run.checkpoint_version
        or run.background_claim_expires_at is None
        or run.background_claim_expires_at <= timezone.now()
    ):
        raise UnifiedExecutorError("RUN_EXECUTOR_CLAIM_INVALID")
    nodes, outgoing, current = _validated_graph(run.workflow_version.compiled_graph)
    if run.status == WorkflowRunStatus.QUEUED:
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
            return _execution(started)
        run.refresh_from_db()
    if run.status != WorkflowRunStatus.RUNNING:
        outcome = (
            "terminal"
            if run.status in {"completed", "failed", "timed_out", "cancelled"}
            else "stale"
        )
        return RunExecution(outcome, str(run.status), run.checkpoint_version)
    state = dict(run.redacted_state)
    # Server-owned and never visible to a node: read once, then removed from the working state.
    cursor = state.pop(_CURSOR_KEY, None)
    if isinstance(cursor, str) and cursor in nodes:
        current = cursor
    executed: list[str] = []
    try:
        while True:
            guarded = _guard_transition(run, claim_token)
            if guarded is not None:
                return _execution(guarded)
            node = nodes[current]
            if node["type"] in _WAIT_KIND_BY_NODE_TYPE:
                return _suspend_at_wait(
                    run=run,
                    node=node,
                    state=state,
                    resume_node=str(outgoing[current][0]["to"]),
                    claim_token=claim_token,
                    step_delta=len(executed) + 1,
                )
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
        return _execution(
            transition_run(
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
        )
    run.refresh_from_db()
    return _execution(
        transition_run(
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
    )


def execute_background_delivery(
    *,
    body: dict[str, object],
    headers: dict[str, object],
    lease_seconds: int = 30,
) -> str:
    """Converge one validated Celery delivery through claim and bounded execution."""

    if not bool(getattr(settings, "UNIFIED_BACKGROUND_EXECUTOR_ENABLED", False)):
        raise UnifiedExecutorError("RUN_EXECUTOR_DISABLED")
    delivery = parse_background_delivery(body=body, headers=headers)
    if delivery.service_revision != service_revision():
        raise UnifiedExecutorError("RUN_EXECUTOR_REVISION_MISMATCH")
    claim = claim_background_run(
        organization_id=delivery.organization_id,
        run_id=delivery.run_id,
        claim_token=delivery.delivery_token,
        lease_seconds=lease_seconds,
    )
    if claim.outcome == "expired":
        resolved = resolve_expired_background_claim(
            organization_id=delivery.organization_id,
            run_id=delivery.run_id,
            claim_token=delivery.delivery_token,
            transition_token=_transition_token(delivery.delivery_token, "claim-expired"),
        )
        if resolved != "released":
            return resolved
        claim = claim_background_run(
            organization_id=delivery.organization_id,
            run_id=delivery.run_id,
            claim_token=delivery.delivery_token,
            lease_seconds=lease_seconds,
        )
    elif claim.outcome == "recovery_required":
        resolve_expired_background_claim(
            organization_id=delivery.organization_id,
            run_id=delivery.run_id,
            claim_token=delivery.delivery_token,
            transition_token=_transition_token(delivery.delivery_token, "claim-expired"),
        )
        return WorkflowRunStatus.RECOVERY_REQUIRED
    if claim.outcome == "cancellation_requested":
        result = transition_run(
            organization_id=delivery.organization_id,
            run_id=delivery.run_id,
            transition_token=_transition_token(delivery.delivery_token, "cancelled"),
            expected_checkpoint_version=claim.checkpoint_version,
            expected_status=claim.status,
            target_status=WorkflowRunStatus.CANCELLED,
            reason_code="RUN_CANCELLATION_REQUESTED",
        )
        return result.status
    if claim.outcome == "deadline_exceeded":
        result = transition_run(
            organization_id=delivery.organization_id,
            run_id=delivery.run_id,
            transition_token=_transition_token(delivery.delivery_token, "timed-out"),
            expected_checkpoint_version=claim.checkpoint_version,
            expected_status=claim.status,
            target_status=WorkflowRunStatus.TIMED_OUT,
            reason_code="RUN_DEADLINE_EXCEEDED",
        )
        return result.status
    if claim.outcome == "terminal":
        return claim.status
    if claim.outcome in {"busy", "suspended"}:
        return claim.outcome
    if claim.outcome not in {"claimed", "replayed"}:
        raise UnifiedExecutorError("RUN_EXECUTOR_CLAIM_INVALID")
    execution = execute_claimed_bounded_run(
        organization_id=delivery.organization_id,
        run_id=delivery.run_id,
        claim_token=delivery.delivery_token,
    )
    return execution.status
