"""Canonical Run-native executor for governed synchronous and background workflows."""

from __future__ import annotations

import os
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypedDict

import jsonschema
from django.db import transaction
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
from apps.workflows.models import (
    RUN_CURSOR_KEY,
    RUN_TERMINAL_STATUSES,
    Run,
    RunAwaitingKind,
    RunBranch,
    RunBranchStatus,
    RunCancellationState,
    RunCompensationEntry,
    RunCompensationStatus,
    RunEventType,
    RunExecutionMode,
    RunJoin,
    RunJoinStatus,
    RunStatus,
)
from apps.workflows.run_parallel import (
    REGION_NODE_TYPES,
    RunParallelError,
    open_run_region,
    renew_run_branch_claim,
)
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
    parse_pointer,
    resolve_pointer,
)
from apps.workflows.transitions import RunTransitionResult, transition_run

_WAIT_KIND_BY_NODE_TYPE = {
    "event_wait": RunAwaitingKind.EVENT,
    "human_task": RunAwaitingKind.HUMAN,
    "timer": RunAwaitingKind.TIMER,
}
# Governed nodes that produce an output envelope through the shared runtime seams. They are
# projected into state by the mapping contract, never by the node writing state itself.
_ELIGIBLE_NODE_TYPES = frozenset({"agent_loop", "custom", "generate", "retrieve", "transform"})
_ENVELOPE_NODE_TYPES = frozenset({"tool"}) | _ELIGIBLE_NODE_TYPES
# A branch body may only contain governed envelope nodes with no durable pause of their own:
# a branch has no checkpoint to park on, so an approval or wait inside one is refused.
_BRANCH_BODY_NODE_TYPES = _ELIGIBLE_NODE_TYPES - {"agent_loop"}
_SUPPORTED_NODE_TYPES = frozenset(
    {
        "condition",
        "end",
        "format_output",
        "input",
        "join",
        "subworkflow",
        "agent_loop",
        "validate_contract",
        *REGION_NODE_TYPES,
        *_ENVELOPE_NODE_TYPES,
        *_WAIT_KIND_BY_NODE_TYPE,
    }
)
_TRANSITION_NAMESPACE = uuid.UUID("d7297f29-2050-48d4-905b-a5f08971e900")

# Server-owned resume cursor. It lives in the checkpoint rather than a column so a durable pause
# needs no schema change, and it is unforgeable: an ``output_mapping`` may only write the six
# business roots, and the executor pops it before any node runs and rewrites it at suspension.
_CURSOR_KEY = RUN_CURSOR_KEY
_AGENT_RESUME_KEY = "_run_agent_resume"
_TRANSIENT_NODE_ERRORS = frozenset(
    {
        "WORKFLOW_GENERATION_FAILED",
        "WORKFLOW_RETRIEVAL_FAILED",
        "WORKFLOW_NODE_TIMED_OUT",
    }
)


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
    duration = "delay_seconds" if node["type"] == "timer" else "timeout_seconds"
    return isinstance(config.get(duration), int) and config[duration] > 0


def _branch_names(join_node: dict[str, Any]) -> list[str]:
    names = join_node["config"].get("branches")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_INVALID")
    return [str(name) for name in names]


def _validated_graph(
    graph: object,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, dict[str, Any]]],
    str,
]:
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
    branch_edges: dict[str, dict[str, dict[str, Any]]] = {node_id: {} for node_id in nodes}
    for edge in raw_edges:
        if (
            not isinstance(edge, dict)
            or edge.get("from") not in nodes
            or edge.get("to") not in nodes
            or "on_error" in edge
        ):
            raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        source = str(edge["from"])
        label = edge.get("branch")
        if label is None:
            outgoing[source].append(edge)
            continue
        if not isinstance(label, str) or label in branch_edges[source]:
            raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        branch_edges[source][label] = edge
    compensation_targets = {
        str(node["compensation"]) for node in nodes.values() if node.get("compensation")
    }
    for node_id, node in nodes.items():
        edges = outgoing[node_id]
        if node_id in compensation_targets:
            if edges or branch_edges[node_id]:
                raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
            continue
        if branch_edges[node_id]:
            # Only a region and its own body nodes fan out through labelled branch edges, and
            # they never also carry an unlabelled edge that would escape the region.
            if node["type"] not in REGION_NODE_TYPES | _BRANCH_BODY_NODE_TYPES:
                raise UnifiedExecutorError("RUN_EXECUTOR_NODE_UNSUPPORTED")
            if edges:
                raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        elif node["type"] in REGION_NODE_TYPES:
            raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        elif node["type"] == "end":
            if edges:
                raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        elif node["type"] == "condition":
            if len(edges) != 2 or {edge.get("when") for edge in edges} != {True, False}:
                raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
        elif len(edges) != 1:
            raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit_branch(region_id: str, join_id: str, name: str) -> None:
        current = region_id
        for _ in range(len(nodes)):
            edge = branch_edges[current].get(name)
            if edge is None:
                raise UnifiedExecutorError("RUN_EXECUTOR_EDGE_UNSUPPORTED")
            current = str(edge["to"])
            if current == join_id:
                return
            # A body already seen belongs to another branch or closes a cycle; both are refused.
            if current in visited or nodes[current]["type"] not in _BRANCH_BODY_NODE_TYPES:
                raise UnifiedExecutorError("RUN_EXECUTOR_NODE_UNSUPPORTED")
            if not nodes[current].get("input_mapping"):
                # The shared eligible-node seam has compatibility fallbacks that can read its
                # supplied state. A unified branch may never rely on them: its compiled mapping
                # is the complete data contract for the independently delivered branch worker.
                raise UnifiedExecutorError("RUN_EXECUTOR_BRANCH_INPUT_MAPPING_REQUIRED")
            visited.add(current)
        raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_UNBOUNDED")

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_UNBOUNDED")
        if node_id in visited:
            return
        visiting.add(node_id)
        node = nodes[node_id]
        if node["type"] in REGION_NODE_TYPES:
            join_id = node["config"].get("join")
            if join_id not in nodes or nodes[join_id]["type"] != "join":
                raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_INVALID")
            for name in _branch_names(nodes[join_id]):
                visit_branch(node_id, str(join_id), name)
            visit(str(join_id))
        else:
            for edge in outgoing[node_id]:
                visit(str(edge["to"]))
        visiting.remove(node_id)
        visited.add(node_id)

    visit(input_node)
    if visited | compensation_targets != set(nodes):
        raise UnifiedExecutorError("RUN_EXECUTOR_GRAPH_INVALID")
    return nodes, outgoing, branch_edges, input_node


class _RunOwnerTransitionKwargs(TypedDict, total=False):
    sync_lease_token: uuid.UUID
    background_claim_token: uuid.UUID


def _owner_transition_kwargs(run: Run, owner_token: uuid.UUID) -> _RunOwnerTransitionKwargs:
    if run.execution_mode == RunExecutionMode.SYNC:
        return {"sync_lease_token": owner_token}
    return {"background_claim_token": owner_token}


def _guard_transition(run: Run, owner_token: uuid.UUID) -> RunTransitionResult | None:
    run.refresh_from_db(
        fields=[
            "background_claim_checkpoint_version",
            "cancellation_state",
            "checkpoint_version",
            "deadline_at",
            "status",
            "sync_lease_expires_at",
            "sync_lease_token",
        ]
    )
    owner = _owner_transition_kwargs(run, owner_token)
    if run.cancellation_state == RunCancellationState.REQUESTED:
        return transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=_transition_token(owner_token, "cancelled"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=str(run.status),
            target_status=RunStatus.CANCELLED,
            reason_code="RUN_CANCELLATION_REQUESTED",
            **owner,
        )
    if timezone.now() >= run.deadline_at:
        return transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=_transition_token(owner_token, "timed-out"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=str(run.status),
            target_status=RunStatus.TIMED_OUT,
            reason_code="RUN_DEADLINE_EXCEEDED",
            **owner,
        )
    return None


def _wait_arguments(node: dict[str, Any]) -> dict[str, Any]:
    """Translate one compiled wait node into the durable-wait contract."""

    config = node["config"]
    node_type = node["type"]
    schema: dict[str, Any]
    if node_type == "timer":
        seconds, schema = int(config["delay_seconds"]), {}
    elif node_type == "event_wait":
        seconds = int(config["timeout_seconds"])
        schema = config.get("payload_schema") or {}
    else:
        seconds = int(config["timeout_seconds"])
        schema = config.get("decision_schema") or {}
    return {
        "kind": _WAIT_KIND_BY_NODE_TYPE[node_type],
        "node_id": str(node["id"]),
        "deadline_at": timezone.now() + timedelta(seconds=seconds),
        "payload_schema": schema,
        "output_mapping": list(node.get("output_mapping", [])),
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
    input_env = _node_input(node, state)
    if node["type"] == "agent_loop":
        resume = state.get(_AGENT_RESUME_KEY)
        if (
            isinstance(resume, dict)
            and resume.get("node_id") == node["id"]
            and isinstance(resume.get("checkpoint"), dict)
        ):
            input_env = dict(resume["checkpoint"])
    retry_policy = node.get("retry_policy")
    max_attempts = int(retry_policy["max_attempts"]) if isinstance(retry_policy, dict) else 1
    for attempt in range(1, max_attempts + 1):
        try:
            envelope = _execute_eligible_node(
                node=node,
                state=state,
                input_env=input_env,
                run=run,
            )
            if time.monotonic() - started > MAX_NODE_SECONDS:
                raise WorkflowRuntimeError("WORKFLOW_NODE_TIMED_OUT")
            return envelope
        except WorkflowRuntimeError as exc:
            if exc.code not in _TRANSIENT_NODE_ERRORS or attempt >= max_attempts:
                raise
            from apps.workflows.run_events import append_locked_run_event

            append_locked_run_event(
                run=run,
                event_type=RunEventType.NODE_RETRIED,
                node_id=str(node["id"]),
                outcome="retrying",
                reason_code=exc.code,
                payload={"attempt": attempt + 1},
            )
            run.save(update_fields=["next_event_sequence", "updated_at"])
    raise WorkflowRuntimeError("WORKFLOW_RETRY_EXHAUSTED")


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
            expected_status=RunStatus.RUNNING,
            target_status=RunStatus.WAITING_APPROVAL,
            checkpoint={**state, _CURSOR_KEY: str(node["id"])},
            awaiting_reference=str(invocation_id),
            step_delta=step_delta,
            tool_call_delta=tool_call_delta,
            background_claim_token=claim_token,
        )
    )


def _region_for_join(nodes: dict[str, dict[str, Any]], join_node_id: str) -> str:
    for node in nodes.values():
        if node["type"] in REGION_NODE_TYPES and str(node["config"]["join"]) == join_node_id:
            return str(node["id"])
    raise WorkflowRuntimeError("WORKFLOW_PARALLEL_REGION_INVALID")


def _park_on_region(
    *,
    run: Run,
    region_node_id: str,
    join_node_id: str,
    state: dict[str, Any],
    claim_token: uuid.UUID,
    step_delta: int,
    purpose: str,
) -> RunExecution:
    """Release the claim and wait on the region, resuming at its join node."""

    run.refresh_from_db()
    return _execution(
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=_transition_token(claim_token, purpose),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=RunStatus.RUNNING,
            target_status=RunStatus.WAITING_CHILD,
            checkpoint={**state, _CURSOR_KEY: join_node_id},
            awaiting_reference=region_node_id,
            step_delta=step_delta,
            background_claim_token=claim_token,
        )
    )


def _open_region(
    *,
    run: Run,
    node: dict[str, Any],
    state: dict[str, Any],
    claim_token: uuid.UUID,
    step_delta: int,
) -> RunExecution:
    """Park on the region first, so its branches fan out from the committed checkpoint."""

    from apps.workflows.tasks import dispatch_unified_run_branches

    region_node_id = str(node["id"])
    join_node_id = str(node["config"]["join"])
    parked = _park_on_region(
        run=run,
        region_node_id=region_node_id,
        join_node_id=join_node_id,
        state=state,
        claim_token=claim_token,
        step_delta=step_delta,
        purpose=f"region:{region_node_id}",
    )
    if parked.outcome != "committed" or parked.status != RunStatus.WAITING_CHILD:
        return parked
    try:
        open_run_region(
            organization_id=run.organization_id, run_id=run.id, region_node_id=region_node_id
        )
    except RunParallelError as exc:
        # The wait released the claim, so this closes the Run through the unowned-wait path.
        run.refresh_from_db()
        return _execution(
            transition_run(
                organization_id=run.organization_id,
                run_id=run.id,
                transition_token=_transition_token(claim_token, f"region-failed:{region_node_id}"),
                expected_checkpoint_version=run.checkpoint_version,
                expected_status=RunStatus.WAITING_CHILD,
                target_status=RunStatus.FAILED,
                error_code=exc.code,
            )
        )
    dispatch_unified_run_branches(
        organization_id=run.organization_id, run_id=run.id, region_node_id=region_node_id
    )
    return parked


def _open_child(
    *,
    run: Run,
    node: dict[str, Any],
    state: dict[str, Any],
    resume_node: str,
    claim_token: uuid.UUID,
    step_delta: int,
) -> RunExecution:
    """Admit one pinned child Run and park the parent on its exact UUID."""

    from apps.workflows.run_children import RunChildError, admit_run_child

    input_envelope = _node_input(node, state)
    if input_envelope is None:
        raise WorkflowRuntimeError("COMPOSITION_CHILD_INPUT_INVALID")
    try:
        link = admit_run_child(parent_run=run, node=node, input_envelope=input_envelope)
    except RunChildError as exc:
        raise WorkflowRuntimeError(exc.code) from None
    run.refresh_from_db()
    return _execution(
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=_transition_token(claim_token, f"child:{node['id']}"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=RunStatus.RUNNING,
            target_status=RunStatus.WAITING_CHILD,
            checkpoint={**state, _CURSOR_KEY: resume_node},
            awaiting_reference=str(link.child_run_id),
            step_delta=step_delta,
            background_claim_token=claim_token,
        )
    )


def _record_compensation(run: Run, node: dict[str, Any]) -> None:
    target = node.get("compensation")
    if not isinstance(target, str):
        return
    if RunCompensationEntry.objects.filter(run=run, source_node_id=node["id"]).exists():
        return
    RunCompensationEntry.objects.create(
        organization_id=run.organization_id,
        run=run,
        sequence=RunCompensationEntry.objects.filter(run=run).count() + 1,
        source_node_id=str(node["id"]),
        compensation_node_id=target,
    )


def _execute_compensations(
    *, run: Run, nodes: dict[str, dict[str, Any]], state: dict[str, Any]
) -> bool:
    """Execute durable compensation intent in reverse order; ambiguity requires recovery."""

    from apps.tools.models import ToolInvocationStatus
    from apps.workflows.run_events import append_locked_run_event

    entries = list(
        RunCompensationEntry.objects.select_for_update()
        .filter(run=run, status=RunCompensationStatus.PENDING)
        .order_by("-sequence")
    )
    for entry in entries:
        node = nodes.get(entry.compensation_node_id)
        try:
            if node is None:
                raise WorkflowRuntimeError("WORKFLOW_COMPENSATION_INVALID")
            if node["type"] == "tool":
                invocation = _invoke_tool(run=run, node=node, state=state)
                if invocation.status != ToolInvocationStatus.COMPLETED:
                    raise WorkflowRuntimeError("WORKFLOW_COMPENSATION_UNRESOLVED")
            elif node["type"] == "transform":
                _run_eligible(run=run, node=node, state=state)
            else:
                raise WorkflowRuntimeError("WORKFLOW_COMPENSATION_INVALID")
        except WorkflowRuntimeError as exc:
            entry.status = RunCompensationStatus.FAILED
            entry.reason_code = exc.code
            entry.save(update_fields=["status", "reason_code", "updated_at"])
            append_locked_run_event(
                run=run,
                event_type=RunEventType.COMPENSATION,
                node_id=entry.compensation_node_id,
                outcome=RunCompensationStatus.FAILED,
                reason_code=exc.code,
                payload={"sequence": entry.sequence},
            )
            run.save(update_fields=["next_event_sequence", "updated_at"])
            return False
        entry.status = RunCompensationStatus.COMPLETED
        entry.save(update_fields=["status", "updated_at"])
        append_locked_run_event(
            run=run,
            event_type=RunEventType.COMPENSATION,
            node_id=entry.compensation_node_id,
            outcome=RunCompensationStatus.COMPLETED,
            payload={"sequence": entry.sequence},
        )
        run.save(update_fields=["next_event_sequence", "updated_at"])
    return True


def execute_run_branch_path(*, branch: RunBranch, delivery_token: uuid.UUID) -> Any:
    """Execute only the immutable branch path this durable branch owns."""

    initial_run = branch.run
    nodes, _outgoing, branch_edges, _input_node = _validated_graph(
        initial_run.workflow_version.compiled_graph
    )
    region = nodes.get(branch.region_node_id)
    if region is None or region["type"] not in REGION_NODE_TYPES:
        raise WorkflowRuntimeError("WORKFLOW_PARALLEL_REGION_INVALID")
    join_node_id = str(region["config"]["join"])
    name = branch.branch_name
    state = deepcopy(branch.input_state)
    current = branch.region_node_id
    for _ in range(len(nodes)):
        # Keep RLS scope for a node's governed database work, but commit its lease renewal
        # before beginning the next node. This bounds Run/RunJoin/RunBranch lock duration to
        # the safe boundary rather than the complete multi-node branch path.
        with transaction.atomic():
            set_tenant_context(branch.organization_id)
            run = Run.objects.select_related("workflow_version", "release", "consumer").get(
                pk=branch.run_id, organization_id=branch.organization_id
            )
            active_branch = RunBranch.objects.get(
                pk=branch.id, organization_id=branch.organization_id
            )
            if (
                run.status in RUN_TERMINAL_STATUSES
                or run.cancellation_state == RunCancellationState.REQUESTED
            ):
                raise WorkflowRuntimeError("WORKFLOW_CANCELLED")
            if timezone.now() >= run.deadline_at:
                raise WorkflowRuntimeError("RUN_DEADLINE_EXCEEDED")
            if (
                active_branch.status != RunBranchStatus.RUNNING
                or active_branch.claim_expires_at is None
                or active_branch.claim_expires_at <= timezone.now()
            ):
                raise WorkflowRuntimeError("WORKFLOW_BRANCH_CLAIM_INVALID")
            edge = branch_edges[current].get(name)
            if edge is None:
                raise WorkflowRuntimeError("WORKFLOW_PARALLEL_REGION_INVALID")
            current = str(edge["to"])
            if current == join_node_id:
                if region["type"] == "parallel":
                    try:
                        return resolve_pointer(state, parse_pointer(f"/branches/{name}/output"))
                    except MappingError as exc:
                        raise WorkflowRuntimeError(exc.code) from None
                return state.get("result", state.get("output", state))
            node = nodes[current]
            state = _project_envelope(node, state, _run_eligible(run=run, node=node, state=state))
            try:
                _assert_state_size(state)
            except WorkflowRequestError:
                raise WorkflowRuntimeError("WORKFLOW_STATE_TOO_LARGE") from None
            try:
                renew_run_branch_claim(
                    organization_id=run.organization_id,
                    branch_id=active_branch.id,
                    delivery_token=delivery_token,
                )
            except RunParallelError as exc:
                raise WorkflowRuntimeError(exc.code) from None
    raise WorkflowRuntimeError("WORKFLOW_PARALLEL_REGION_INVALID")


def _execute_owned_bounded_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    owner_token: uuid.UUID,
    execution_mode: RunExecutionMode,
) -> RunExecution:
    """Execute one exactly owned graph using only canonical Run persistence."""

    with transaction.atomic():
        set_tenant_context(organization_id)
        run = Run.objects.select_related("workflow_version", "release").get(
            pk=run_id,
            organization_id=organization_id,
        )
        _validate_run_pins(run)
        if run.execution_mode != execution_mode:
            raise UnifiedExecutorError("RUN_EXECUTOR_CLAIM_INVALID")
        if execution_mode == RunExecutionMode.BACKGROUND:
            if (
                run.background_claim_token != owner_token
                or run.background_claim_checkpoint_version != run.checkpoint_version
                or run.background_claim_expires_at is None
                or run.background_claim_expires_at <= timezone.now()
            ):
                raise UnifiedExecutorError("RUN_EXECUTOR_CLAIM_INVALID")
        elif (
            run.sync_lease_token != owner_token
            or run.sync_lease_expires_at is None
            or run.sync_lease_expires_at <= timezone.now()
        ):
            raise UnifiedExecutorError("RUN_EXECUTOR_SYNC_LEASE_INVALID")
        nodes, outgoing, _branch_edges, current = _validated_graph(
            run.workflow_version.compiled_graph
        )
    owner = _owner_transition_kwargs(run, owner_token)
    if run.status == RunStatus.QUEUED:
        started = transition_run(
            organization_id=organization_id,
            run_id=run.id,
            transition_token=_transition_token(owner_token, "started"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=RunStatus.QUEUED,
            target_status=RunStatus.RUNNING,
            **owner,
        )
        if started.outcome != "committed":
            return _execution(started)
    return _execute_started_owned_run(
        organization_id=organization_id,
        run_id=run.id,
        owner_token=owner_token,
        execution_mode=execution_mode,
        nodes=nodes,
        outgoing=outgoing,
        current=current,
    )


@transaction.atomic
def _execute_started_owned_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    owner_token: uuid.UUID,
    execution_mode: RunExecutionMode,
    nodes: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    current: str,
) -> RunExecution:
    """Run node work after the durable running transition has committed."""

    set_tenant_context(organization_id)
    run = Run.objects.select_related("workflow_version", "release").get(
        pk=run_id,
        organization_id=organization_id,
    )
    owner = _owner_transition_kwargs(run, owner_token)
    if run.status != RunStatus.RUNNING:
        outcome = (
            "terminal"
            if run.status in {"completed", "failed", "timed_out", "cancelled"}
            else "stale"
        )
        return RunExecution(outcome, str(run.status), run.checkpoint_version)
    state = dict(run.checkpoint)
    # Server-owned and never visible to a node: read once, then removed from the working state.
    cursor = state.pop(_CURSOR_KEY, None)
    if isinstance(cursor, str) and cursor in nodes:
        current = cursor
    executed: list[str] = []
    tool_calls = 0
    input_tokens = 0
    output_tokens = 0
    try:
        while True:
            guarded = _guard_transition(run, owner_token)
            if guarded is not None:
                return _execution(guarded)
            node = nodes[current]
            if node["type"] in _WAIT_KIND_BY_NODE_TYPE:
                if execution_mode == RunExecutionMode.SYNC:
                    raise WorkflowRuntimeError("SYNC_DURABLE_PAUSE_FORBIDDEN")
                return _suspend_at_wait(
                    run=run,
                    node=node,
                    state=state,
                    resume_node=str(outgoing[current][0]["to"]),
                    claim_token=owner_token,
                    step_delta=len(executed) + 1,
                )
            if node["type"] in REGION_NODE_TYPES:
                if execution_mode == RunExecutionMode.SYNC:
                    raise WorkflowRuntimeError("SYNC_PARALLEL_REGION_FORBIDDEN")
                return _open_region(
                    run=run,
                    node=node,
                    state=state,
                    claim_token=owner_token,
                    step_delta=len(executed) + 1,
                )
            if node["type"] == "subworkflow":
                if execution_mode == RunExecutionMode.SYNC:
                    raise WorkflowRuntimeError("SYNC_CHILD_RUN_FORBIDDEN")
                return _open_child(
                    run=run,
                    node=node,
                    state=state,
                    resume_node=str(outgoing[current][0]["to"]),
                    claim_token=owner_token,
                    step_delta=len(executed) + 1,
                )
            decision: bool | None = None
            if node["type"] == "join":
                join = RunJoin.objects.filter(run_id=run.id, join_node_id=current).first()
                if join is None or join.status == RunJoinStatus.OPEN:
                    # A delivery reached the join before its region closed. Park again rather
                    # than fail: branches may still be in flight and the deadline still bounds it.
                    return _park_on_region(
                        run=run,
                        region_node_id=(
                            join.region_node_id
                            if join is not None
                            else _region_for_join(nodes, current)
                        ),
                        join_node_id=current,
                        state=state,
                        claim_token=owner_token,
                        step_delta=len(executed) + 1,
                        purpose=f"join-pending:{current}",
                    )
                if join.status != RunJoinStatus.SUCCEEDED:
                    raise WorkflowRuntimeError(join.reason_code or "WORKFLOW_JOIN_FAILED")
                state = deepcopy(join.merged_state)
            elif node["type"] == "tool":
                from apps.tools.models import ToolInvocationStatus

                invocation = _invoke_tool(run=run, node=node, state=state)
                if invocation.status == ToolInvocationStatus.PENDING_APPROVAL:
                    if execution_mode == RunExecutionMode.SYNC:
                        raise WorkflowRuntimeError("SYNC_APPROVAL_PAUSE_FORBIDDEN")
                    return _suspend_for_approval(
                        run=run,
                        node=node,
                        state=state,
                        invocation_id=invocation.id,
                        claim_token=owner_token,
                        step_delta=len(executed) + 1,
                        tool_call_delta=tool_calls,
                    )
                tool_calls += 1
                output = invocation.redacted_output
                _record_compensation(run, node)
                state = _project_envelope(node, state, output if isinstance(output, dict) else {})
            elif node["type"] in _ELIGIBLE_NODE_TYPES:
                from apps.agents.runtime import AgentPaused

                try:
                    envelope = _run_eligible(run=run, node=node, state=state)
                except AgentPaused as exc:
                    if (
                        execution_mode == RunExecutionMode.SYNC
                        or not isinstance(exc.invocation_id, int)
                        or not isinstance(exc.checkpoint, dict)
                    ):
                        raise WorkflowRuntimeError("AGENT_APPROVAL_PAUSE_INVALID") from None
                    paused_state = {
                        **state,
                        _AGENT_RESUME_KEY: {
                            "node_id": str(node["id"]),
                            "checkpoint": exc.checkpoint,
                        },
                    }
                    return _suspend_for_approval(
                        run=run,
                        node=node,
                        state=paused_state,
                        invocation_id=exc.invocation_id,
                        claim_token=owner_token,
                        step_delta=len(executed) + 1,
                        tool_call_delta=tool_calls,
                    )
                state.pop(_AGENT_RESUME_KEY, None)
                state = _project_envelope(node, state, envelope)
                if node["type"] == "agent_loop":
                    agent_usage = envelope.get("agent")
                    if isinstance(agent_usage, dict):
                        tool_calls += int(agent_usage.get("tool_calls", 0))
                        input_tokens += int(agent_usage.get("input_tokens", 0))
                        output_tokens += int(agent_usage.get("output_tokens", 0))
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
        compensated = _execute_compensations(run=run, nodes=nodes, state=state)
        target_status = RunStatus.FAILED if compensated else RunStatus.RECOVERY_REQUIRED
        return _execution(
            transition_run(
                organization_id=organization_id,
                run_id=run.id,
                transition_token=_transition_token(owner_token, "failed"),
                expected_checkpoint_version=run.checkpoint_version,
                expected_status=RunStatus.RUNNING,
                target_status=target_status,
                checkpoint=state,
                awaiting_reference="compensation" if not compensated else "",
                error_code=exc.code if compensated else "WORKFLOW_COMPENSATION_FAILED",
                step_delta=len(executed),
                tool_call_delta=tool_calls,
                input_token_delta=input_tokens,
                output_token_delta=output_tokens,
                **owner,
            )
        )
    run.refresh_from_db()
    return _execution(
        transition_run(
            organization_id=organization_id,
            run_id=run.id,
            transition_token=_transition_token(owner_token, "completed"),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=RunStatus.RUNNING,
            target_status=RunStatus.COMPLETED,
            checkpoint=state,
            step_delta=len(executed),
            tool_call_delta=tool_calls,
            input_token_delta=input_tokens,
            output_token_delta=output_tokens,
            **owner,
        )
    )


def execute_claimed_bounded_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    claim_token: uuid.UUID,
) -> RunExecution:
    """Execute one PostgreSQL-claimed background Run."""

    return _execute_owned_bounded_run(
        organization_id=organization_id,
        run_id=run_id,
        owner_token=claim_token,
        execution_mode=RunExecutionMode.BACKGROUND,
    )


def execute_sync_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    lease_token: uuid.UUID,
) -> RunExecution:
    """Execute one bounded synchronous Run under its exact renewable lease."""

    return _execute_owned_bounded_run(
        organization_id=organization_id,
        run_id=run_id,
        owner_token=lease_token,
        execution_mode=RunExecutionMode.SYNC,
    )


def execute_background_delivery(
    *,
    body: dict[str, object],
    headers: dict[str, object],
    lease_seconds: int = 30,
) -> str:
    """Converge one validated Celery delivery through claim and bounded execution."""

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
        return RunStatus.RECOVERY_REQUIRED
    if claim.outcome == "cancellation_requested":
        result = transition_run(
            organization_id=delivery.organization_id,
            run_id=delivery.run_id,
            transition_token=_transition_token(delivery.delivery_token, "cancelled"),
            expected_checkpoint_version=claim.checkpoint_version,
            expected_status=claim.status,
            target_status=RunStatus.CANCELLED,
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
            target_status=RunStatus.TIMED_OUT,
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
