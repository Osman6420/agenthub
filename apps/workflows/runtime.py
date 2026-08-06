"""Governed node-execution helpers used exclusively by the unified Run executor."""

from __future__ import annotations

import ast
from typing import Any

import jsonschema

from apps.releases.services import get_artifact_body_for_role
from apps.workflows.custom_nodes import CustomNodeError, execute_custom_node

MAX_NODE_SECONDS = 30


class WorkflowRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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


def _apply_default_output(
    node: dict[str, Any],
    state: dict[str, Any],
    envelope: dict[str, Any],
) -> None:
    node_type = node["type"]
    if node_type == "retrieve":
        state["retrieval"] = envelope
    elif node_type == "generate":
        # Provider/runtime metadata is not part of the canonical response unless an
        # author explicitly maps it. Keep the default output contract stable.
        state["output"] = {
            "answer": envelope.get("answer", ""),
            "sources": envelope.get("sources", []),
        }
    elif node_type == "agent_loop":
        state["output"] = envelope.get("output", envelope)
    elif node_type == "custom":
        state.update(envelope)
    elif node_type == "tool":
        state[node["config"]["output_key"]] = envelope
    else:
        raise WorkflowRuntimeError("WORKFLOW_NODE_UNSUPPORTED")


def _execute_eligible_node(
    *,
    node: dict[str, Any],
    state: dict[str, Any],
    input_env: dict[str, Any] | None,
    run: Any,
) -> dict[str, Any]:
    """Execute one governed envelope-producing node."""

    node_type = node["type"]
    config = node["config"]
    release = run.release
    if node_type == "retrieve":
        from apps.artifacts.governed_dsl import (
            GovernedDSLValidationError,
            normalize_retrieval_profile,
        )
        from apps.orchestration.rag_steps import retrieve_for_release

        query = _envelope_query(input_env) if input_env is not None else _workflow_query(state)
        retrieval_profile: dict[str, Any] | None = None
        retrieval_ref = config.get("retrieval_profile_ref")
        if isinstance(retrieval_ref, str) and retrieval_ref:
            body = get_artifact_body_for_role(release, retrieval_ref)
            if not isinstance(body, dict):
                raise WorkflowRuntimeError("WORKFLOW_RETRIEVAL_BINDING_INVALID")
            try:
                retrieval_profile = normalize_retrieval_profile(body)
            except GovernedDSLValidationError as exc:
                raise WorkflowRuntimeError("WORKFLOW_RETRIEVAL_BINDING_INVALID") from exc
        try:
            return retrieve_for_release(
                release=release,
                query=query,
                consumer_id=run.consumer_id,
                retrieval_profile=retrieval_profile,
            )
        except Exception as exc:
            raise WorkflowRuntimeError("WORKFLOW_RETRIEVAL_FAILED") from exc
    if node_type == "agent_loop":
        from apps.agents.runtime import AgentPaused, AgentRuntimeError, run_embedded_agent_loop

        policy = config.get("policy")
        if not isinstance(policy, dict):
            raise WorkflowRuntimeError("WORKFLOW_AGENT_LOOP_POLICY_INVALID")
        try:
            result = run_embedded_agent_loop(
                compiled_config=policy,
                release=release,
                workflow_run=run,
                state=input_env if input_env is not None else state,
            )
        except AgentPaused:
            raise
        except AgentRuntimeError as exc:
            raise WorkflowRuntimeError(exc.code) from None
        return {
            "output": result.output,
            "agent": {
                "steps": result.steps,
                "tool_calls": result.tool_calls,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "tools_called": list(result.tools_called),
                "decisions": list(result.decisions),
                "escalation": result.escalation,
            },
        }
    if node_type == "generate":
        from apps.orchestration.providers import ModelProviderError
        from apps.orchestration.rag_steps import (
            chunks_from_state,
            citations_from_state,
            generate_for_release,
            grounding_fallback_answer,
        )

        source = input_env if input_env is not None else state
        fallback = grounding_fallback_answer(release=release, state=source)
        if fallback is not None:
            return {"answer": fallback, "sources": [], "fallback_used": True}
        context = chunks_from_state(source)
        prompt, model_profile = _generate_bindings(config, release)
        user_query = _envelope_query(input_env) if input_env is not None else _workflow_query(state)
        try:
            response = generate_for_release(
                release=release,
                context=context,
                prompt=prompt,
                model_profile=model_profile,
                user_query=user_query,
            )
        except ModelProviderError as exc:
            raise WorkflowRuntimeError("WORKFLOW_GENERATION_FAILED") from exc
        return {
            "answer": response.text,
            "sources": citations_from_state(source),
            "fallback_used": False,
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
        try:
            return execute_custom_node(
                node_ref=node_ref,
                config=custom_config,
                state=input_env if input_env is not None else state,
                run=run,
            )
        except CustomNodeError as exc:
            raise WorkflowRuntimeError(exc.code) from None
    if node_type == "transform":
        return _run_transform_node(config=config, input_env=input_env, release=release)
    raise WorkflowRuntimeError("WORKFLOW_NODE_UNSUPPORTED")


def _execute_node(
    *,
    node: dict[str, Any],
    state: dict[str, Any],
    release: Any,
    run: Any,
) -> bool | None:
    """Execute one bounded structural node; durable pauses are owned by the caller."""

    del run
    node_type = node["type"]
    config = node["config"]
    if node_type in {"input", "end"}:
        return None
    if node_type == "format_output":
        state["output"] = {
            "answer": str(config.get("template_ref", "")),
            "sources": [],
        }
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


def _run_transform_node(
    *,
    config: dict[str, Any],
    input_env: dict[str, Any] | None,
    release: Any,
) -> dict[str, Any]:
    from apps.artifacts.governed_dsl import (
        GovernedDocument,
        GovernedDSLValidationError,
        execute_transform,
    )

    body = get_artifact_body_for_role(release, str(config["transform_profile_ref"]))
    if not isinstance(body, dict):
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


def _workflow_query(state: dict[str, Any]) -> str:
    payload = state.get("input")
    if isinstance(payload, dict):
        query = payload.get("query")
        if isinstance(query, str):
            return query
    return str(payload) if payload is not None else ""


def _generate_bindings(
    config: dict[str, Any],
    release: Any,
) -> tuple[str | None, dict[str, Any] | None]:
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
                matched = _compare(operator, left, right)
            except TypeError:
                return False
            if not matched:
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
