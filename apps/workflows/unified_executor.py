"""Default-off Run-native executor for a bounded side-effect-free workflow subset."""

from __future__ import annotations

import os
import time
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
from apps.workflows.run_waits import RunWaitError, run_tool_idempotency_key, suspend_run_for_wait
from apps.workflows.runtime import (
    MAX_NODE_SECONDS,
    WorkflowRuntimeError,
    _apply_default_output,
    _execute_eligible_node,
    _execute_node,
    _validate_output_policy,
)
from apps.workflows.services import WorkflowRequestError, _assert_state_size
from apps.workflows.state_mapping import (
    MappingError,
    apply_output_mapping,
    build_input_envelope,
)
from apps.workflows.transitions import RunTransitionResult, transition_run

_WAIT_KIND_BY_NODE_TYPE = {
    "event_wait": RunAwaitingKind.EVENT,
    "human_task": RunAwaitingKind.HUMAN,
    "timer": RunAwaitingKind.TIMER,
}
# Governed nodes that produce an output envelope through the shared runtime seams. They are
# projected into state by the mapping contract, never by the node writing state itself.
_ELIGIBLE_NODE_TYPES = frozenset({"custom", "generate", "retrieve", "transform"})
_ENVELOPE_NODE_TYPES = frozenset({"tool"}) | _ELIGIBLE_NODE_TYPES
_SUPPORTED_NODE_TYPES = frozenset(
    {
        "condition",
        "end",
        "format_output",
        "input",
        "validate_contract",
        *_ENVELOPE_NODE_TYPES,
        *_WAIT_KIND_BY_NODE_TYPE,
    }
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


def _node_input(node: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """Build the node-local input envelope, so a node never sees state it did not select."""

    input_mapping = node.get("input_mapping")
    if not input_mapping:
        return None
    try:
        return build_input_envelope(state, input_mapping)
    except MappingError as exc:
        raise WorkflowRuntimeError(exc.code) from None


def _run_eligible(*, run: Run, node: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Produce one governed node envelope through the shared runtime seam, bounded in time."""

    started = time.monotonic()
    envelope = _execute_eligible_node(
        node=node,
        state=state,
        input_env=_node_input(node, state),
        run=run,
    )
    if time.monotonic() - started > MAX_NODE_SECONDS:
        raise WorkflowRuntimeError("WORKFLOW_NODE_TIMED_OUT")
    return envelope


def _invoke_tool(*, run: Run, node: dict[str, Any], state: dict[str, Any]) -> Any:
    """Drive one governed tool call, returning the completed invocation or a pending approval."""

    from apps.tools.approvals import ToolApprovalError, execute_invocation, request_tool_invocation
    from apps.tools.models import ToolInvocationStatus

    config = node["config"]
    envelope = _node_input(node, state)
    if envelope is None:
        raw = state.get(config["input_key"]) if "input_key" in config else None
        envelope = raw if isinstance(raw, dict) else {}
    context = run.execution_context if isinstance(run.execution_context, dict) else {}
    capabilities = [str(item) for item in context.get("capabilities", [])]
    try:
        invocation = request_tool_invocation(
            release=run.release,
            consumer=run.consumer,
            role=config["binding_role"],
            tool_input=envelope,
            idempotency_key=run_tool_idempotency_key(run.id, str(node["id"])),
            consumer_capabilities=capabilities,
            requested_by=run.consumer.subject,
        )
        if invocation.status == ToolInvocationStatus.APPROVED:
            invocation = execute_invocation(
                invocation_id=invocation.id,
                tool_input=envelope,
                consumer_capabilities=capabilities,
            )
    except ToolApprovalError as exc:
        raise WorkflowRuntimeError(f"TOOL_{exc.code}") from None
    if invocation.status in {
        ToolInvocationStatus.PENDING_APPROVAL,
        ToolInvocationStatus.COMPLETED,
    }:
        return invocation
    # Rejection and every unresolved outcome fail the Run closed; a dispatched-but-unconfirmed
    # call is never retried.
    raise WorkflowRuntimeError(f"TOOL_{str(invocation.status).upper()}")


def _project_envelope(
    node: dict[str, Any], state: dict[str, Any], envelope: dict[str, Any]
) -> dict[str, Any]:
    output_mapping = node.get("output_mapping")
    if output_mapping:
        try:
            return apply_output_mapping(state, envelope, output_mapping)
        except MappingError as exc:
            raise WorkflowRuntimeError(exc.code) from None
    projected = dict(state)
    _apply_default_output(node, projected, envelope)
    return projected


def _suspend_for_approval(
    *,
    run: Run,
    node: dict[str, Any],
    state: dict[str, Any],
    invocation_id: int,
    claim_token: uuid.UUID,
    step_delta: int,
    tool_call_delta: int,
) -> RunExecution:
    """Park the Run on a pending approval, re-entering the same node once it is decided."""

    run.refresh_from_db()
    return _execution(
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=_transition_token(claim_token, f"approval:{node['id']}"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=WorkflowRunStatus.RUNNING,
            target_status=WorkflowRunStatus.WAITING_APPROVAL,
            checkpoint={**state, _CURSOR_KEY: str(node["id"])},
            awaiting_reference=str(invocation_id),
            step_delta=step_delta,
            tool_call_delta=tool_call_delta,
            background_claim_token=claim_token,
        )
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
    tool_calls = 0
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
            decision: bool | None = None
            if node["type"] == "tool":
                from apps.tools.models import ToolInvocationStatus

                invocation = _invoke_tool(run=run, node=node, state=state)
                if invocation.status == ToolInvocationStatus.PENDING_APPROVAL:
                    return _suspend_for_approval(
                        run=run,
                        node=node,
                        state=state,
                        invocation_id=invocation.id,
                        claim_token=claim_token,
                        step_delta=len(executed) + 1,
                        tool_call_delta=tool_calls,
                    )
                tool_calls += 1
                output = invocation.redacted_output
                state = _project_envelope(node, state, output if isinstance(output, dict) else {})
            elif node["type"] in _ELIGIBLE_NODE_TYPES:
                state = _project_envelope(
                    node, state, _run_eligible(run=run, node=node, state=state)
                )
            else:
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
                tool_call_delta=tool_calls,
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
            tool_call_delta=tool_calls,
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
