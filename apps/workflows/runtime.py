"""Bounded deterministic execution of immutable compiled workflow graphs."""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import jsonschema
from django.utils import timezone

from apps.gateway.execution_context import ExecutionContextInvalid, verify_execution_context
from apps.orchestration.runtime import RunResult
from apps.releases.services import get_artifact_body_for_role
from apps.workflows.custom_nodes import CustomNodeError, execute_custom_node
from apps.workflows.models import WorkflowRunStatus
from apps.workflows.services import (
    WorkflowRequestError,
    _assert_state_size,
    _redact,
    resolve_release_workflow,
)

MAX_NODE_SECONDS = 30


class WorkflowRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
    return RunResult(
        status="completed",
        output=result.output,
        usage={"input_tokens": 0, "output_tokens": 0},
        fallback_used=False,
        metadata={"workload_type": "workflow", "executed_nodes": list(result.executed_nodes)},
    )


def execute_graph(*, run: Any, verify_context: bool = True) -> WorkflowResult:
    if verify_context:
        try:
            verify_execution_context(run.execution_context)
        except ExecutionContextInvalid:
            raise WorkflowRuntimeError("EXECUTION_CONTEXT_INVALID") from None
    graph = run.workflow_version.compiled_graph
    nodes = {item["id"]: item for item in graph["nodes"]}
    edges: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in nodes}
    for edge in graph["edges"]:
        edges[edge["from"]].append(edge)
    state = dict(run.redacted_state)
    current = graph["input_node"]
    executed: list[str] = []

    while True:
        run.refresh_from_db(fields=["status", "deadline_at"])
        if run.status == WorkflowRunStatus.CANCELLED:
            raise WorkflowRuntimeError("WORKFLOW_CANCELLED")
        if time.time() > run.deadline_at.timestamp():
            raise WorkflowRuntimeError("WORKFLOW_TIMED_OUT")
        node = nodes[current]
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
        outgoing = edges[current]
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


def _execute_node(
    *, node: dict[str, Any], state: dict[str, Any], release: Any, run: Any
) -> bool | None:
    node_type = node["type"]
    config = node["config"]
    if node_type in {"input", "end"}:
        return None
    if node_type == "retrieve":
        state["retrieval"] = {"chunks": [], "top_score": 0.0}
        return None
    if node_type == "generate":
        state["output"] = {"answer": "generated", "sources": []}
        return None
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
    if node_type == "custom":
        node_ref = str(config["node_ref"])
        custom_config = {key: value for key, value in config.items() if key != "node_ref"}
        try:
            patch = execute_custom_node(
                node_ref=node_ref,
                config=custom_config,
                state=state,
                run=run,
            )
        except CustomNodeError as exc:
            raise WorkflowRuntimeError(exc.code) from None
        state.update(patch)
        return None
    raise WorkflowRuntimeError("WORKFLOW_NODE_UNSUPPORTED")


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
