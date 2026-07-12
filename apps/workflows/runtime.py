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
from apps.workflows.models import WorkflowRunEvent, WorkflowRunStatus
from apps.workflows.services import (
    WorkflowRequestError,
    _assert_state_size,
    _next_sequence,
    _redact,
    resolve_release_workflow,
)

MAX_NODE_SECONDS = 30


class WorkflowRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class WorkflowPaused(Exception):
    """Signals that a run is suspended awaiting a tool approval decision."""


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
        if node["type"] == "tool":
            # May raise WorkflowPaused (approval pending) or merge output into state.
            _run_tool_node(node=node, state=state, run=run, resuming=resuming)
            resuming = False
            try:
                _assert_state_size(state)
            except WorkflowRequestError:
                raise WorkflowRuntimeError("WORKFLOW_STATE_TOO_LARGE") from None
            executed.append(current)
            outgoing = edges[current]
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


def _run_tool_node(
    *, node: dict[str, Any], state: dict[str, Any], run: Any, resuming: bool
) -> None:
    """Execute a governed tool call, pausing the run if approval is pending."""
    from apps.tools.approvals import ToolApprovalError, execute_invocation, request_tool_invocation
    from apps.tools.models import ToolInvocationStatus

    config = node["config"]
    role = config["binding_role"]
    input_key = config["input_key"]
    output_key = config["output_key"]
    tool_input = state.get(input_key)
    if not isinstance(tool_input, dict):
        tool_input = {}

    # The eval candidate seam runs without a consumer; produce a deterministic stub so
    # tool-containing workflows remain evaluable without real egress or approval.
    if getattr(run, "consumer_id", None) is None:
        state[output_key] = {"status": "ok"}
        return

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
        state[output_key] = output
        if resuming:
            run.awaiting_node = ""
            run.save(update_fields=["awaiting_node", "updated_at"])
        return
    raise WorkflowRuntimeError(f"TOOL_{str(invocation.status).upper()}")


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
    if node_type == "retrieve":
        from apps.orchestration.rag_steps import retrieve_for_release

        try:
            state["retrieval"] = retrieve_for_release(release=release, query=_workflow_query(state))
        except Exception as exc:  # provider-opaque failure -> fail the node with a stable code
            raise WorkflowRuntimeError("WORKFLOW_RETRIEVAL_FAILED") from exc
        return None
    if node_type == "generate":
        from apps.orchestration.providers import ModelProviderError
        from apps.orchestration.rag_steps import chunks_from_state, generate_for_release

        context = chunks_from_state(state)
        prompt, model_profile = _generate_bindings(config, release)
        try:
            response = generate_for_release(
                release=release, context=context, prompt=prompt, model_profile=model_profile
            )
        except ModelProviderError as exc:
            raise WorkflowRuntimeError("WORKFLOW_GENERATION_FAILED") from exc
        retrieval = state.get("retrieval") if isinstance(state.get("retrieval"), dict) else {}
        state["output"] = {
            "answer": response.text,
            "sources": retrieval.get("chunks", []) if isinstance(retrieval, dict) else [],
        }
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
