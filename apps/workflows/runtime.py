"""Bounded deterministic execution of immutable compiled workflow graphs."""

from __future__ import annotations

import ast
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import jsonschema
from django.utils import timezone

from apps.gateway.execution_context import ExecutionContextInvalid, verify_execution_context
from apps.orchestration.runtime import RunResult
from apps.releases.services import get_artifact_body_for_role
from apps.workflows.compiler import (
    COMPILED_WORKFLOW_API_VERSION,
    COMPOSITION_NODE_TYPES,
    MAPPING_ELIGIBLE_NODE_TYPES,
)
from apps.workflows.custom_nodes import CustomNodeError, execute_custom_node
from apps.workflows.models import WorkflowRunEvent, WorkflowRunStatus
from apps.workflows.services import (
    WorkflowRequestError,
    _assert_state_size,
    _next_sequence,
    _redact,
    resolve_release_workflow,
)
from apps.workflows.state_mapping import (
    MappingError,
    apply_output_mapping,
    build_input_envelope,
    parse_pointer,
    resolve_pointer,
)

MAX_NODE_SECONDS = 30


class WorkflowRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class WorkflowPaused(Exception):
    """Signals that a run is suspended at a durable checkpoint."""


class WorkflowParallelPending(Exception):
    """Signals that durable branch intents replaced the current worker execution."""

    def __init__(self, branch_ids: list[int]) -> None:
        self.branch_ids = branch_ids
        super().__init__("parallel_pending")


class WorkflowRetryPending(Exception):
    """Signals that a durable node attempt must be redelivered after bounded backoff."""

    def __init__(self, countdown_seconds: int) -> None:
        self.countdown_seconds = countdown_seconds
        super().__init__("retry_pending")


@dataclass(frozen=True)
class WorkflowResult:
    output: dict[str, Any]
    state: dict[str, Any]
    executed_nodes: tuple[str, ...]


def run_workflow_candidate(*, release: Any, input_payload: dict[str, Any]) -> RunResult:
    """Isolated synchronous candidate seam used only by the governed eval runner."""
    workflow_version = resolve_release_workflow(release)
    run = SimpleNamespace(
        workflow_version=workflow_version,
        release=release,
        redacted_state={"input": _redact(input_payload)},
        status=WorkflowRunStatus.RUNNING,
        deadline_at=timezone.now() + timedelta(seconds=300),
        organization=release.scenario.project.organization,
        organization_id=release.scenario.project.organization_id,
        scenario_id=release.scenario_id,
        release_id=release.id,
        id=0,
        refresh_from_db=lambda **kwargs: None,
    )
    result = execute_graph(run=run, verify_context=False)
    metadata: dict[str, Any] = {
        "workload_type": "workflow",
        "executed_nodes": list(result.executed_nodes),
    }
    metadata.update(_workflow_structure_evidence(run.id))
    return RunResult(
        status="completed",
        output=result.output,
        usage={"input_tokens": 0, "output_tokens": 0},
        fallback_used=False,
        metadata=metadata,
    )


def _workflow_structure_evidence(run_id: int) -> dict[str, Any]:
    """Redacted branch/join/wait/retry/compensation/child summary for eval assertions.

    Content-free identifiers and counts only — never state, merged output or payloads. The
    synchronous candidate seam cannot yet execute async branch/wait structures (they require
    a persisted run with dispatched branches), so for a candidate run (``run_id == 0``) these
    lists are empty. Populating async candidate evidence end-to-end is an owning-part
    follow-up (P2.6.2–P2.6.5); the assertion vocabulary and this contract are in place so a
    later async candidate seam needs no eval change. See the P2.6.11 plan route-back note.
    """
    if not run_id:
        return {
            "branches_completed": [],
            "joins_completed": [],
            "waits_created": [],
            "waits_resumed": [],
            "waits_expired": [],
            "max_retry_attempts": 0,
            "compensations_executed": [],
            "compensations_skipped": [],
            "children_completed": [],
        }
    from apps.workflows.models import (
        WorkflowBranch,
        WorkflowBranchStatus,
        WorkflowChildLink,
        WorkflowCompensationEntry,
        WorkflowCompensationStatus,
        WorkflowJoin,
        WorkflowJoinStatus,
        WorkflowNodeAttempt,
        WorkflowWait,
        WorkflowWaitStatus,
    )

    branches = [
        f"{b.region_node_id}/{b.branch_name}"
        for b in WorkflowBranch.objects.filter(run_id=run_id, status=WorkflowBranchStatus.SUCCEEDED)
    ]
    joins = [
        j.join_node_id
        for j in WorkflowJoin.objects.filter(run_id=run_id, status=WorkflowJoinStatus.SUCCEEDED)
    ]
    waits = list(WorkflowWait.objects.filter(run_id=run_id))
    resumed = [w.node_id for w in waits if w.status == WorkflowWaitStatus.RESUMED]
    expired = [w.node_id for w in waits if w.status == WorkflowWaitStatus.EXPIRED]
    max_attempts = max(
        (a.ordinal for a in WorkflowNodeAttempt.objects.filter(run_id=run_id)), default=0
    )
    comps = list(WorkflowCompensationEntry.objects.filter(run_id=run_id))
    return {
        "branches_completed": branches,
        "joins_completed": joins,
        "waits_created": [w.node_id for w in waits],
        "waits_resumed": resumed,
        "waits_expired": expired,
        "max_retry_attempts": max_attempts,
        "compensations_executed": [
            c.source_node_id for c in comps if c.status == WorkflowCompensationStatus.SUCCEEDED
        ],
        "compensations_skipped": [
            c.source_node_id for c in comps if c.status == WorkflowCompensationStatus.CANCELLED
        ],
        "children_completed": [
            link.call_site
            for link in WorkflowChildLink.objects.filter(parent_run_id=run_id, status="completed")
        ],
    }


def execute_graph(*, run: Any, verify_context: bool = True) -> WorkflowResult:
    if verify_context:
        try:
            verify_execution_context(run.execution_context)
        except ExecutionContextInvalid:
            raise WorkflowRuntimeError("EXECUTION_CONTEXT_INVALID") from None
    graph = run.workflow_version.compiled_graph
    if graph.get("api_version") != COMPILED_WORKFLOW_API_VERSION:
        # A stale compiled graph/checkpoint must never run under the new mapping semantics.
        raise WorkflowRuntimeError("WORKFLOW_COMPILER_VERSION_UNSUPPORTED")
    nodes = {item["id"]: item for item in graph["nodes"]}
    edges: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in nodes}
    for edge in graph["edges"]:
        edges[edge["from"]].append(edge)
    state = dict(run.redacted_state)
    # Resume from the paused tool node when the run is being re-dispatched.
    resuming = bool(getattr(run, "awaiting_node", ""))
    current = run.awaiting_node if resuming else graph["input_node"]
    executed: list[str] = []

    while True:
        run.refresh_from_db(fields=["status", "deadline_at"])
        if run.status == WorkflowRunStatus.CANCELLED:
            raise WorkflowRuntimeError("WORKFLOW_CANCELLED")
        if time.time() > run.deadline_at.timestamp():
            raise WorkflowRuntimeError("WORKFLOW_TIMED_OUT")
        node = nodes[current]
        if resuming and bool(getattr(run, "id", 0)):
            recovery_target = _consume_recovery_decision(
                run=run, node=node, nodes=nodes, edges=graph["edges"], state=state
            )
            if recovery_target is not None:
                run.awaiting_node = ""
                run.save(update_fields=["awaiting_node", "updated_at"])
                resuming = False
                executed.append(current)
                current = recovery_target
                continue
        if resuming and node["type"] in {"event_wait", "human_task", "timer"}:
            run.awaiting_node = ""
            run.save(update_fields=["awaiting_node", "updated_at"])
            resuming = False
            executed.append(current)
            outgoing = [edge for edge in edges[current] if "on_error" not in edge]
            if len(outgoing) != 1:
                raise WorkflowRuntimeError("WORKFLOW_EDGE_INVALID")
            current = outgoing[0]["to"]
            continue
        if node["type"] in {"parallel", "for_each"}:
            from apps.workflows.models import WorkflowBranch
            from apps.workflows.parallel import open_parallel_region

            join = open_parallel_region(
                organization_id=run.organization_id, run_id=run.id, region_node_id=current
            )
            run.awaiting_node = join.join_node_id
            run.save(update_fields=["awaiting_node", "updated_at"])
            branch_ids = list(
                WorkflowBranch.objects.filter(run_id=run.id, region_node_id=current)
                .order_by("branch_name", "item_ordinal")
                .values_list("id", flat=True)
            )
            raise WorkflowParallelPending(branch_ids)
        if node["type"] == "join" and resuming:
            from apps.workflows.models import WorkflowJoin, WorkflowJoinStatus

            join = WorkflowJoin.objects.get(run_id=run.id, join_node_id=current)
            if join.status == WorkflowJoinStatus.FAILED:
                raise WorkflowRuntimeError("WORKFLOW_JOIN_FAILED")
            if join.status != WorkflowJoinStatus.SUCCEEDED:
                raise WorkflowParallelPending([])
            state = deepcopy(join.merged_state)
            run.awaiting_node = ""
            run.save(update_fields=["awaiting_node", "updated_at"])
            resuming = False
            executed.append(current)
            outgoing = [edge for edge in edges[current] if "on_error" not in edge]
            if len(outgoing) != 1:
                raise WorkflowRuntimeError("WORKFLOW_EDGE_INVALID")
            current = outgoing[0]["to"]
            continue
        if node["type"] in MAPPING_ELIGIBLE_NODE_TYPES:
            # May raise WorkflowPaused (tool approval pending). Applies typed mappings or the
            # legacy default write, atomically (copy-on-success) on the returned state.
            attempt = None
            if bool(getattr(run, "id", 0)) and node["type"] not in {
                "event_wait",
                "human_task",
            }:
                from apps.workflows.recovery_services import start_node_attempt

                attempt = start_node_attempt(run=run, node_id=current)
            try:
                state = _run_eligible_node(node=node, state=state, run=run, resuming=resuming)
            except WorkflowRuntimeError as exc:
                failure_class, retry_allowed, countdown = _record_node_failure(
                    run=run, node=node, state=state, attempt=attempt, code=exc.code
                )
                if retry_allowed:
                    run.awaiting_node = current
                    run.redacted_state = state
                    run.save(update_fields=["awaiting_node", "redacted_state", "updated_at"])
                    raise WorkflowRetryPending(countdown) from None
                route = _error_route(
                    edges=graph["edges"], node_id=current, failure_class=failure_class
                )
                if route is not None:
                    state["_recovery"] = {
                        "failure_class": failure_class,
                        "reason_code": exc.code,
                        "failed_node": current,
                    }
                    current = route
                    resuming = False
                    continue
                if failure_class == "outcome_unknown" and bool(getattr(run, "id", 0)):
                    from apps.workflows.recovery_services import open_recovery_case

                    open_recovery_case(
                        run=run,
                        node_id=current,
                        failure_class=failure_class,
                        reason_code=exc.code,
                        high_risk=node["type"] == "tool",
                    )
                    raise WorkflowPaused() from None
                _run_compensations(run=run, nodes=nodes, state=state)
                raise
            if attempt is not None:
                from apps.workflows.recovery_services import (
                    complete_node_attempt,
                    push_compensation,
                )

                run.redacted_state = state
                run.save(update_fields=["redacted_state", "updated_at"])
                complete_node_attempt(attempt=attempt)
                if "compensation" in node:
                    push_compensation(
                        run=run,
                        source_node_id=current,
                        compensation_node_id=str(node["compensation"]),
                    )
            if resuming and getattr(run, "awaiting_node", "") == current:
                run.awaiting_node = ""
                run.save(update_fields=["awaiting_node", "updated_at"])
            resuming = False
            try:
                _assert_state_size(state)
            except WorkflowRequestError:
                raise WorkflowRuntimeError("WORKFLOW_STATE_TOO_LARGE") from None
            executed.append(current)
            outgoing = [edge for edge in edges[current] if "on_error" not in edge]
            if len(outgoing) != 1:
                raise WorkflowRuntimeError("WORKFLOW_EDGE_INVALID")
            current = outgoing[0]["to"]
            continue
        started = time.monotonic()
        decision = _execute_node(node=node, state=state, release=run.release, run=run)
        if time.monotonic() - started > MAX_NODE_SECONDS:
            raise WorkflowRuntimeError("WORKFLOW_NODE_TIMED_OUT")
        try:
            _assert_state_size(state)
        except WorkflowRequestError:
            raise WorkflowRuntimeError("WORKFLOW_STATE_TOO_LARGE") from None
        executed.append(current)
        if node["type"] == "end":
            break
        outgoing = [edge for edge in edges[current] if "on_error" not in edge]
        if node["type"] == "condition":
            matching = [edge for edge in outgoing if edge.get("when") is decision]
            if len(matching) != 1:
                raise WorkflowRuntimeError("WORKFLOW_BRANCH_INVALID")
            current = matching[0]["to"]
        elif len(outgoing) == 1:
            current = outgoing[0]["to"]
        else:
            raise WorkflowRuntimeError("WORKFLOW_EDGE_INVALID")

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
    return WorkflowResult(output=output, state=state, executed_nodes=tuple(executed))


def execute_branch_path(*, branch: Any) -> Any:
    """Execute only the immutable graph path owned by a durable branch/item."""
    run = branch.run
    graph = run.workflow_version.compiled_graph
    nodes = {item["id"]: item for item in graph["nodes"]}
    region = nodes[branch.region_node_id]
    branch_name = branch.branch_name
    edge = next(
        item
        for item in graph["edges"]
        if item["from"] == branch.region_node_id and item.get("branch") == branch_name
    )
    current = edge["to"]
    state = deepcopy(branch.input_state)
    while current != region["config"]["join"]:
        run.refresh_from_db(fields=["status", "deadline_at"])
        if run.status == WorkflowRunStatus.CANCELLED:
            raise WorkflowRuntimeError("WORKFLOW_CANCELLED")
        node = nodes[current]
        if node["type"] not in MAPPING_ELIGIBLE_NODE_TYPES:
            raise WorkflowRuntimeError("WORKFLOW_PARALLEL_REGION_INVALID")
        state = _run_eligible_node(node=node, state=state, run=run, resuming=False)
        outgoing = [
            item
            for item in graph["edges"]
            if item["from"] == current and item.get("branch") == branch_name
        ]
        if len(outgoing) != 1:
            raise WorkflowRuntimeError("WORKFLOW_PARALLEL_REGION_INVALID")
        current = outgoing[0]["to"]
    if region["type"] == "parallel":
        try:
            return resolve_pointer(state, parse_pointer(f"/branches/{branch_name}/output"))
        except MappingError as exc:
            raise WorkflowRuntimeError(exc.code) from None
    return state.get("result", state.get("output", state))


def _record_node_failure(
    *, run: Any, node: dict[str, Any], state: dict[str, Any], attempt: Any, code: str
) -> tuple[str, bool, int]:
    from apps.workflows.recovery import classify_failure

    failure_class = classify_failure(code)
    if attempt is None:
        return failure_class, False, 0
    from apps.workflows.recovery_services import fail_node_attempt

    # Tool calls are never automatically retried in v1. Their durable invocation may represent a
    # dispatched side effect; a future verified reconciliation contract can explicitly widen this.
    policy = node.get("retry_policy") if node["type"] != "tool" else None
    durable_class, allowed, countdown = fail_node_attempt(
        attempt=attempt, code=code, retry_policy=policy
    )
    run.redacted_state = state
    run.save(update_fields=["redacted_state", "updated_at"])
    return durable_class, allowed, countdown


def _consume_recovery_decision(
    *,
    run: Any,
    node: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    state: dict[str, Any],
) -> str | None:
    from apps.workflows.models import WorkflowRecoveryCase, WorkflowRecoveryStatus

    case = (
        WorkflowRecoveryCase.objects.filter(
            run=run,
            node_id=node["id"],
            status=WorkflowRecoveryStatus.RESOLVED,
        )
        .order_by("-revision")
        .first()
    )
    if case is None:
        return None
    if case.resolved_action == "reconcile_confirmed_success":
        outgoing = [edge for edge in edges if edge["from"] == node["id"] and "on_error" not in edge]
        if len(outgoing) != 1:
            raise WorkflowRuntimeError("WORKFLOW_EDGE_INVALID")
        return str(outgoing[0]["to"])
    if case.resolved_action == "reconcile_confirmed_failure":
        route = _error_route(edges=edges, node_id=str(node["id"]), failure_class=case.failure_class)
        if route is None:
            _run_compensations(run=run, nodes=nodes, state=state)
            raise WorkflowRuntimeError(case.reason_code)
        state["_recovery"] = {
            "failure_class": case.failure_class,
            "reason_code": case.reason_code,
            "failed_node": node["id"],
        }
        return route
    if case.resolved_action == "resume_compensation":
        _run_compensations(run=run, nodes=nodes, state=state)
        raise WorkflowRuntimeError(case.reason_code)
    return None


def _error_route(*, edges: list[dict[str, Any]], node_id: str, failure_class: str) -> str | None:
    from apps.workflows.recovery import select_error_route

    return select_error_route(
        edges=edges,
        node_id=node_id,
        failure_class=failure_class,  # type: ignore[arg-type]
    )


def _run_compensations(
    *, run: Any, nodes: dict[str, dict[str, Any]], state: dict[str, Any]
) -> None:
    if not bool(getattr(run, "id", 0)):
        return
    from apps.workflows.models import WorkflowCompensationEntry, WorkflowCompensationStatus
    from apps.workflows.recovery import classify_failure
    from apps.workflows.recovery_services import mark_compensation, open_recovery_case

    entries = WorkflowCompensationEntry.objects.filter(
        run=run,
        status__in=[WorkflowCompensationStatus.PENDING, WorkflowCompensationStatus.BLOCKED],
    ).order_by("-sequence")
    for entry in entries:
        node = nodes.get(entry.compensation_node_id)
        if node is None:
            mark_compensation(
                entry=entry,
                status=WorkflowCompensationStatus.BLOCKED,
                reason_code="WORKFLOW_COMPENSATION_INVALID",
            )
            open_recovery_case(
                run=run,
                node_id=entry.compensation_node_id,
                failure_class="permanent",
                reason_code="WORKFLOW_COMPENSATION_INVALID",
                high_risk=True,
            )
            raise WorkflowPaused()
        try:
            mark_compensation(entry=entry, status=WorkflowCompensationStatus.RUNNING)
            updated = _run_eligible_node(node=node, state=state, run=run, resuming=False)
            if updated is not state:
                state.clear()
                state.update(updated)
        except WorkflowRuntimeError as exc:
            failure_class = classify_failure(exc.code)
            mark_compensation(
                entry=entry,
                status=WorkflowCompensationStatus.BLOCKED,
                reason_code=exc.code,
            )
            open_recovery_case(
                run=run,
                node_id=entry.compensation_node_id,
                failure_class=failure_class,
                reason_code=exc.code,
                high_risk=True,
            )
            raise WorkflowPaused() from None
        mark_compensation(entry=entry, status=WorkflowCompensationStatus.SUCCEEDED)


def _validate_output_policy(release: Any, output: dict[str, Any]) -> None:
    policy = get_artifact_body_for_role(release, "policy_profile")
    if not isinstance(policy, dict):
        return
    output_policy = policy.get("output", {})
    if not isinstance(output_policy, dict):
        raise WorkflowRuntimeError("POLICY_VIOLATION")
    if output_policy.get("citations") == "required":
        sources = output.get("sources")
        if not isinstance(sources, list) or not sources:
            raise WorkflowRuntimeError("POLICY_VIOLATION")


def _run_eligible_node(
    *, node: dict[str, Any], state: dict[str, Any], run: Any, resuming: bool
) -> dict[str, Any]:
    """Run a mapping-eligible node and apply its output to the run state.

    Builds a node-local input envelope from a pre-node snapshot when ``input_mapping`` is
    declared (so the node never receives ambient state it did not select), then projects the
    node's output envelope into state through ``output_mapping`` (copy-on-success) or the
    node's legacy default write. A required tool approval raises :class:`WorkflowPaused`
    before any output is applied.
    """
    input_mapping = node.get("input_mapping")
    output_mapping = node.get("output_mapping")
    try:
        input_env = build_input_envelope(state, input_mapping) if input_mapping else None
    except MappingError as exc:
        raise WorkflowRuntimeError(exc.code) from None

    if node["type"] in COMPOSITION_NODE_TYPES:
        envelope = _run_composition_node(node=node, state=state, input_env=input_env, run=run)
    elif node["type"] == "tool":
        envelope = _run_tool_node(
            node=node, state=state, input_env=input_env, run=run, resuming=resuming
        )
    elif node["type"] in {"event_wait", "human_task"}:
        from apps.workflows.waits import create_wait

        create_wait(run=run, node=node, state=state)
        raise WorkflowPaused()
    else:
        started = time.monotonic()
        envelope = _execute_eligible_node(node=node, state=state, input_env=input_env, run=run)
        if time.monotonic() - started > MAX_NODE_SECONDS:
            raise WorkflowRuntimeError("WORKFLOW_NODE_TIMED_OUT")

    try:
        if output_mapping:
            return apply_output_mapping(state, envelope, output_mapping)
    except MappingError as exc:
        raise WorkflowRuntimeError(exc.code) from None
    _apply_default_output(node, state, envelope)
    return state


def _apply_default_output(
    node: dict[str, Any], state: dict[str, Any], envelope: dict[str, Any]
) -> None:
    """Legacy per-node default write used when a node declares no ``output_mapping``."""
    node_type = node["type"]
    if node_type == "retrieve":
        state["retrieval"] = envelope
    elif node_type == "generate":
        state["output"] = envelope
    elif node_type == "custom":
        state.update(envelope)
    elif node_type == "tool":
        state[node["config"]["output_key"]] = envelope
    else:  # pragma: no cover - transform always declares output_mapping (compiler-enforced)
        raise WorkflowRuntimeError("WORKFLOW_NODE_UNSUPPORTED")


def _execute_eligible_node(
    *, node: dict[str, Any], state: dict[str, Any], input_env: dict[str, Any] | None, run: Any
) -> dict[str, Any]:
    """Execute a non-tool mapping-eligible node and return its output envelope."""
    node_type = node["type"]
    config = node["config"]
    release = run.release
    if node_type == "retrieve":
        from apps.orchestration.rag_steps import retrieve_for_release

        query = _envelope_query(input_env) if input_env is not None else _workflow_query(state)
        try:
            return retrieve_for_release(release=release, query=query, consumer_id=run.consumer_id)
        except Exception as exc:  # provider-opaque failure -> fail the node with a stable code
            raise WorkflowRuntimeError("WORKFLOW_RETRIEVAL_FAILED") from exc
    if node_type == "generate":
        from apps.orchestration.providers import ModelProviderError
        from apps.orchestration.rag_steps import chunks_from_state, generate_for_release

        context = chunks_from_state(input_env if input_env is not None else state)
        prompt, model_profile = _generate_bindings(config, release)
        try:
            response = generate_for_release(
                release=release, context=context, prompt=prompt, model_profile=model_profile
            )
        except ModelProviderError as exc:
            raise WorkflowRuntimeError("WORKFLOW_GENERATION_FAILED") from exc
        source = input_env if input_env is not None else state
        retrieval = source.get("retrieval") if isinstance(source.get("retrieval"), dict) else {}
        return {
            "answer": response.text,
            "sources": retrieval.get("chunks", []) if isinstance(retrieval, dict) else [],
        }
    if node_type == "custom":
        if config.get("execution_class", "managed") == "python":
            from apps.workflows.python_nodes import PythonNodeError, execute_configured_python_node

            try:
                return execute_configured_python_node(
                    config=config,
                    input_payload=input_env if input_env is not None else state,
                    run=run,
                    node_id=str(node["id"]),
                )
            except PythonNodeError as exc:
                raise WorkflowRuntimeError(exc.code) from None
        node_ref = str(config["node_ref"])
        custom_config = {key: value for key, value in config.items() if key != "node_ref"}
        # With input_mapping the node sees only its declared envelope, not ambient state.
        node_state = input_env if input_env is not None else state
        try:
            return execute_custom_node(
                node_ref=node_ref, config=custom_config, state=node_state, run=run
            )
        except CustomNodeError as exc:
            raise WorkflowRuntimeError(exc.code) from None
    if node_type == "transform":
        return _run_transform_node(config=config, input_env=input_env, release=release)
    raise WorkflowRuntimeError("WORKFLOW_NODE_UNSUPPORTED")


def _run_transform_node(
    *, config: dict[str, Any], input_env: dict[str, Any] | None, release: Any
) -> dict[str, Any]:
    """Execute the pinned governed transform profile over the node-local input envelope."""
    from apps.artifacts.governed_dsl import (
        GovernedDocument,
        GovernedDSLValidationError,
        execute_transform,
    )

    body = get_artifact_body_for_role(release, str(config["transform_profile_ref"]))
    if not isinstance(body, dict):
        # A missing/foreign/unpinned profile fails closed; there is no ambient fallback.
        raise WorkflowRuntimeError("WORKFLOW_TRANSFORM_PROFILE_UNRESOLVED")
    try:
        result = execute_transform(body, input_env if input_env is not None else {})
    except GovernedDSLValidationError:
        raise WorkflowRuntimeError("WORKFLOW_TRANSFORM_FAILED") from None
    if isinstance(result, list) and result and isinstance(result[0], GovernedDocument):
        result = [
            {
                "source_id": document.source_id,
                "title": document.title,
                "content": document.content,
                "metadata": document.metadata,
            }
            for document in result
        ]
    return {"result": result}


def _envelope_query(envelope: dict[str, Any]) -> str:
    query = envelope.get("query")
    if isinstance(query, str):
        return query
    return str(query) if query is not None else ""


def _run_tool_node(
    *,
    node: dict[str, Any],
    state: dict[str, Any],
    input_env: dict[str, Any] | None,
    run: Any,
    resuming: bool,
) -> dict[str, Any]:
    """Execute a governed tool call, pausing the run if approval is pending.

    Returns the tool's output envelope (the caller applies ``output_mapping`` or the legacy
    ``output_key`` write). Raises :class:`WorkflowPaused` when approval is pending.
    """
    from apps.tools.approvals import ToolApprovalError, execute_invocation, request_tool_invocation
    from apps.tools.models import ToolInvocationStatus

    config = node["config"]
    role = config["binding_role"]
    if input_env is not None:
        tool_input: dict[str, Any] = input_env
    else:
        raw = state.get(config["input_key"]) if "input_key" in config else None
        tool_input = raw if isinstance(raw, dict) else {}

    # The eval candidate seam runs without a consumer; produce a deterministic stub so
    # tool-containing workflows remain evaluable without real egress or approval.
    if getattr(run, "consumer_id", None) is None:
        return {"status": "ok"}

    context = run.execution_context if isinstance(run.execution_context, dict) else {}
    capabilities = list(context.get("capabilities", []))
    idempotency_key = f"wf:{run.id}:{node['id']}"
    try:
        invocation = request_tool_invocation(
            release=run.release,
            consumer=run.consumer,
            role=role,
            tool_input=tool_input,
            idempotency_key=idempotency_key,
            consumer_capabilities=capabilities,
            requested_by=run.consumer.subject,
        )
    except ToolApprovalError as exc:
        raise WorkflowRuntimeError(f"TOOL_{exc.code}") from None

    if invocation.status == ToolInvocationStatus.PENDING_APPROVAL:
        _pause_for_approval(run, str(node["id"]), state)
        raise WorkflowPaused()

    if invocation.status == ToolInvocationStatus.APPROVED:
        try:
            invocation = execute_invocation(
                invocation_id=invocation.id,
                tool_input=tool_input,
                consumer_capabilities=capabilities,
            )
        except ToolApprovalError as exc:
            raise WorkflowRuntimeError(f"TOOL_{exc.code}") from None

    if invocation.status == ToolInvocationStatus.COMPLETED:
        output = invocation.redacted_output if isinstance(invocation.redacted_output, dict) else {}
        if resuming:
            run.awaiting_node = ""
            run.save(update_fields=["awaiting_node", "updated_at"])
        return output
    raise WorkflowRuntimeError(f"TOOL_{str(invocation.status).upper()}")


def _run_composition_node(
    *, node: dict[str, Any], state: dict[str, Any], input_env: dict[str, Any] | None, run: Any
) -> dict[str, Any]:
    """Admit or resume a pinned child (``subworkflow``/``agent_call``), pausing the parent.

    On first entry the child is admitted (authority-attenuated, budget-checked) and the parent
    pauses (``waiting_child``) until the child's terminal transition re-dispatches the parent. On
    resume the untrusted child output is validated and returned so the caller applies
    ``output_mapping``. A required-authority or budget denial fails the parent closed.
    """
    from apps.workflows.composition import (
        CompositionError,
        CompositionPending,
        admit_child,
        finalize_child,
    )
    from apps.workflows.models import WorkflowChildLink

    node_id = str(node["id"])
    link = (
        WorkflowChildLink.objects.select_for_update()
        .filter(parent_run=run, call_site=node_id)
        .first()
    )
    try:
        if link is None:
            admit_child(parent_run=run, node=node, input_env=input_env or {})
            _pause_for_child(run, node_id, state)
            raise WorkflowPaused()
        output_env = finalize_child(link=link)
    except CompositionPending:
        _pause_for_child(run, node_id, state)
        raise WorkflowPaused() from None
    except CompositionError as exc:
        raise WorkflowRuntimeError(exc.code) from None
    if getattr(run, "awaiting_node", "") == node_id:
        run.awaiting_node = ""
        run.save(update_fields=["awaiting_node", "updated_at"])
    return output_env


def _pause_for_child(run: Any, node_id: str, state: dict[str, Any]) -> None:
    run.status = WorkflowRunStatus.WAITING_CHILD
    run.awaiting_node = node_id
    run.redacted_state = _redact(state)
    run.save(update_fields=["status", "awaiting_node", "redacted_state", "updated_at"])
    WorkflowRunEvent.objects.create(
        run=run,
        sequence=_next_sequence(run),
        event_type="run_waiting_child",
        node_id=node_id,
        outcome="waiting_child",
    )


def _pause_for_approval(run: Any, node_id: str, state: dict[str, Any]) -> None:
    run.status = WorkflowRunStatus.WAITING_APPROVAL
    run.awaiting_node = node_id
    run.redacted_state = _redact(state)
    run.save(update_fields=["status", "awaiting_node", "redacted_state", "updated_at"])
    WorkflowRunEvent.objects.create(
        run=run,
        sequence=_next_sequence(run),
        event_type="run_waiting_approval",
        node_id=node_id,
        outcome="waiting_approval",
    )


def _execute_node(
    *, node: dict[str, Any], state: dict[str, Any], release: Any, run: Any
) -> bool | None:
    node_type = node["type"]
    config = node["config"]
    if node_type in {"input", "end"}:
        return None
    if node_type == "timer":
        from apps.workflows.waits import create_wait

        create_wait(run=run, node=node, state=state)
        raise WorkflowPaused()
    if node_type == "format_output":
        state["output"] = {"answer": str(config.get("template_ref", "")), "sources": []}
        return None
    if node_type == "validate_contract":
        output = state.get("output")
        schema = get_artifact_body_for_role(release, "output_contract")
        if not isinstance(output, dict):
            raise WorkflowRuntimeError("WORKFLOW_OUTPUT_MISSING")
        if schema is not None:
            try:
                jsonschema.validate(output, schema)
            except jsonschema.ValidationError:
                raise WorkflowRuntimeError("OUTPUT_CONTRACT_VIOLATION") from None
        return None
    if node_type == "condition":
        return _evaluate_condition(config["expression"], state)
    raise WorkflowRuntimeError("WORKFLOW_NODE_UNSUPPORTED")


def _workflow_query(state: dict[str, Any]) -> str:
    """Derive the retrieval query from the workflow input (server-side; no client filter)."""
    payload = state.get("input")
    if isinstance(payload, dict):
        query = payload.get("query")
        if isinstance(query, str):
            return query
    return str(payload) if payload is not None else ""


def _generate_bindings(
    config: dict[str, Any], release: Any
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve per-node prompt/model binding for a ``generate`` node (P5.2).

    ``prompt_ref``/``model_profile_ref`` name manifest roles pinned into the release, so a workflow
    with several ``generate`` nodes runs distinct governed prompts/models. Absent -> the
    release-level ``prompt``/``model_profile`` roles (bundle defaults).
    """
    prompt: str | None = None
    model_profile: dict[str, Any] | None = None
    prompt_ref = config.get("prompt_ref")
    if isinstance(prompt_ref, str) and prompt_ref:
        body = get_artifact_body_for_role(release, prompt_ref)
        if isinstance(body, dict):
            prompt = str(body.get("template", ""))
    model_ref = config.get("model_profile_ref")
    if isinstance(model_ref, str) and model_ref:
        body = get_artifact_body_for_role(release, model_ref)
        if isinstance(body, dict):
            model_profile = body
    return prompt, model_profile


def _evaluate_condition(expression: str, state: dict[str, Any]) -> bool:
    tree = ast.parse(expression, mode="eval")
    result = _eval_ast(tree.body, state)
    if not isinstance(result, bool):
        raise WorkflowRuntimeError("WORKFLOW_CONDITION_INVALID")
    return result


def _eval_ast(node: ast.AST, state: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return state.get(node.id)
    if isinstance(node, ast.Attribute):
        value = _eval_ast(node.value, state)
        return value.get(node.attr) if isinstance(value, dict) else None
    if isinstance(node, ast.BoolOp):
        values = [_eval_ast(item, state) for item in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        left = _eval_ast(node.left, state)
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval_ast(comparator, state)
            try:
                ok = _compare(operator, left, right)
            except TypeError:
                return False
            if not ok:
                return False
            left = right
        return True
    raise WorkflowRuntimeError("WORKFLOW_CONDITION_INVALID")


def _compare(operator: ast.cmpop, left: Any, right: Any) -> bool:
    if isinstance(operator, ast.Eq):
        return left == right
    if isinstance(operator, ast.NotEq):
        return left != right
    if isinstance(operator, ast.Gt):
        return left > right
    if isinstance(operator, ast.GtE):
        return left >= right
    if isinstance(operator, ast.Lt):
        return left < right
    if isinstance(operator, ast.LtE):
        return left <= right
    raise WorkflowRuntimeError("WORKFLOW_CONDITION_INVALID")
