"""Bounded, guarded execution of a compiled agent's decision loop (Sprint 10).

The planner proposes the next action; this runtime is the trust boundary that turns
proposals into governed effects. Every iteration re-checks cancellation, the deadline,
and the step cap; a tool proposal is re-validated against the immutable compiled tool
allowlist and executed only through the Sprint 9 tool proxy/approval flow (pausing the
run for a required approval); token and state-size caps are enforced; and the final
output must pass the release output contract and policy. A resource breach terminates the
run deterministically with a stable code — never an uncontrolled requeue.

Model decisions are proposals, never authorization. The runtime operates on the redacted
durable checkpoint (raw input is redacted at ingress, per the workflow-runtime precedent),
so no raw chain-of-thought or unredacted payload is ever persisted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import jsonschema
from django.utils import timezone

from apps.agents.limits import CHECKPOINT_SCHEMA_VERSION, resolve_limits
from apps.agents.models import AgentRunEvent, AgentRunStatus
from apps.agents.planner import (
    DECISION_KINDS,
    DECISION_RESPOND,
    DECISION_RETRIEVE,
    DECISION_TOOL,
    AgentDecision,
    AgentObservation,
    get_configured_planner,
)
from apps.agents.services import (
    AgentRequestError,
    _assert_checkpoint_size,
    _next_sequence,
    _redact,
    resolve_release_agent,
)
from apps.artifacts.validation import compute_checksum
from apps.gateway.execution_context import ExecutionContextInvalid, verify_execution_context
from apps.orchestration.runtime import RunResult
from apps.releases.services import get_artifact_body_for_role


class AgentRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AgentPaused(Exception):
    """Signals that a run is suspended awaiting a tool approval decision."""


@dataclass(frozen=True)
class AgentResult:
    output: dict[str, Any]
    state: dict[str, Any]
    steps: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    tools_called: tuple[str, ...]
    decisions: tuple[str, ...] = field(default_factory=tuple)


def run_agent_candidate(*, release: Any, input_payload: dict[str, Any]) -> RunResult:
    """Isolated synchronous candidate seam used only by the governed eval runner."""
    agent_version = resolve_release_agent(release)
    limits = resolve_limits(agent_version.compiled_config.get("limits"))
    snapshot = {"input": _redact(input_payload), "limits": limits.as_dict()}
    run = SimpleNamespace(
        agent_version=agent_version,
        release=release,
        execution_context={},
        start_snapshot=snapshot,
        checkpoint=dict(snapshot),
        checkpoint_version=CHECKPOINT_SCHEMA_VERSION,
        status=AgentRunStatus.RUNNING,
        deadline_at=timezone.now() + timedelta(seconds=limits.deadline_seconds),
        organization=release.scenario.project.organization,
        organization_id=release.scenario.project.organization_id,
        scenario_id=release.scenario_id,
        release_id=release.id,
        id=0,
        public_id="",
        consumer_id=None,
        step_count=0,
        tool_call_count=0,
        input_tokens=0,
        output_tokens=0,
        awaiting_step=None,
        awaiting_role="",
        refresh_from_db=lambda **kwargs: None,
    )
    result = execute_agent(run=run, verify_context=False, persist=False)
    return RunResult(
        status="completed",
        output=result.output,
        usage={"input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
        fallback_used=False,
        metadata={
            "workload_type": "agent",
            "steps": result.steps,
            "tools_called": list(result.tools_called),
            "decisions": list(result.decisions),
        },
    )


def execute_agent(*, run: Any, verify_context: bool = True, persist: bool = True) -> AgentResult:
    if verify_context:
        try:
            verify_execution_context(run.execution_context)
        except ExecutionContextInvalid:
            raise AgentRuntimeError("EXECUTION_CONTEXT_INVALID") from None
    if run.checkpoint_version != CHECKPOINT_SCHEMA_VERSION:
        # Never resume a checkpoint written by an incompatible schema/code version.
        raise AgentRuntimeError("AGENT_CHECKPOINT_INCOMPATIBLE")

    config = run.agent_version.compiled_config
    limits = config["limits"]
    objective_key = config["objective_key"]
    output_key = config["output_key"]
    planner = get_configured_planner()

    state = dict(run.checkpoint) if run.checkpoint else dict(run.start_snapshot)
    objective = _objective(state, objective_key)
    retrieved = bool(state.get("_retrieved", False))
    tools_called = tuple(state.get("_tools_called", []))
    step_index = int(run.step_count)
    tool_calls = int(run.tool_call_count)
    in_tokens = int(run.input_tokens)
    out_tokens = int(run.output_tokens)
    resuming_step = run.awaiting_step
    run_ref = str(getattr(run, "public_id", "") or "")
    decisions: list[str] = []

    while True:
        run.refresh_from_db(fields=["status", "deadline_at"])
        if run.status == AgentRunStatus.CANCELLED:
            raise AgentRuntimeError("AGENT_CANCELLED")
        if time.time() > run.deadline_at.timestamp():
            raise AgentRuntimeError("AGENT_TIMED_OUT")
        if step_index >= limits["max_steps"]:
            raise AgentRuntimeError("AGENT_MAX_STEPS")

        observation = AgentObservation(objective, retrieved, tools_called)
        is_resume = resuming_step is not None and step_index == resuming_step
        if is_resume:
            decision = AgentDecision(DECISION_TOOL, role=run.awaiting_role, reason_code="resume")
        else:
            decision = planner.next_action(
                config=config, observation=observation, step_index=step_index, run_ref=run_ref
            )
        _validate_decision(decision, config)

        if decision.kind == DECISION_RESPOND:
            output, delta_in, delta_out = _respond(objective, state, config, run.release)
            in_tokens += delta_in
            out_tokens += delta_out
            if in_tokens + out_tokens > limits["max_tokens"]:
                raise AgentRuntimeError("AGENT_MAX_TOKENS")
            state[output_key] = output
            _validate_output(run.release, output)
            decisions.append(DECISION_RESPOND)
            return AgentResult(
                output=output,
                state=state,
                steps=step_index + 1,
                tool_calls=tool_calls,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                tools_called=tools_called,
                decisions=tuple(decisions),
            )

        if decision.kind == DECISION_RETRIEVE:
            # Governed release-scoped retrieval (P5): the P4 document-ACL retriever behind the
            # same provider seam as run_rag. Deterministic default keeps CI hermetic.
            from apps.orchestration.rag_steps import retrieve_for_release

            try:
                state["retrieval"] = retrieve_for_release(release=run.release, query=objective)
            except Exception as exc:
                raise AgentRuntimeError("AGENT_RETRIEVAL_FAILED") from exc
            retrieved = True
            state["_retrieved"] = True
        else:  # DECISION_TOOL
            role = decision.role
            if not is_resume:
                tool_calls += 1
                if tool_calls > limits["max_tool_calls"]:
                    raise AgentRuntimeError("AGENT_MAX_TOOL_CALLS")
            tool_output = _run_tool_step(
                run=run,
                state=state,
                config=config,
                objective=objective,
                role=role,
                step_index=step_index,
                tool_calls=tool_calls,
                persist=persist,
            )
            state["tool_output"] = tool_output
            tools_called = tools_called + (role,)
            state["_tools_called"] = list(tools_called)
            resuming_step = None

        step_index += 1
        try:
            _assert_checkpoint_size(state)
        except AgentRequestError:
            raise AgentRuntimeError("AGENT_STATE_TOO_LARGE") from None
        decisions.append(decision.kind)
        if persist:
            _persist_step(
                run=run,
                state=state,
                step_index=step_index,
                tool_calls=tool_calls,
                in_tokens=in_tokens,
                out_tokens=out_tokens,
                decision=decision.kind,
            )


def _run_tool_step(
    *,
    run: Any,
    state: dict[str, Any],
    config: dict[str, Any],
    objective: str,
    role: str,
    step_index: int,
    tool_calls: int,
    persist: bool,
) -> dict[str, Any]:
    """Execute one governed tool call, pausing the run if approval is pending."""
    from apps.tools.approvals import ToolApprovalError, execute_invocation, request_tool_invocation
    from apps.tools.models import ToolInvocationStatus

    tool_input = _tool_input(state, config, objective)

    # The eval candidate seam runs without a consumer; produce a deterministic stub so
    # tool-using agents stay evaluable without real egress or approval.
    if getattr(run, "consumer_id", None) is None:
        return {"status": "ok"}

    context = run.execution_context if isinstance(run.execution_context, dict) else {}
    capabilities = list(context.get("capabilities", []))
    idempotency_key = f"agent:{run.id}:{step_index}"
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
        raise AgentRuntimeError(f"TOOL_{exc.code}") from None

    if invocation.status == ToolInvocationStatus.PENDING_APPROVAL:
        if persist:
            _pause_for_approval(run, step_index, role, state, tool_calls)
        raise AgentPaused()

    if invocation.status == ToolInvocationStatus.APPROVED:
        try:
            invocation = execute_invocation(
                invocation_id=invocation.id,
                tool_input=tool_input,
                consumer_capabilities=capabilities,
            )
        except ToolApprovalError as exc:
            raise AgentRuntimeError(f"TOOL_{exc.code}") from None

    if invocation.status == ToolInvocationStatus.COMPLETED:
        output = invocation.redacted_output if isinstance(invocation.redacted_output, dict) else {}
        return output
    raise AgentRuntimeError(f"TOOL_{str(invocation.status).upper()}")


def _pause_for_approval(
    run: Any, step_index: int, role: str, state: dict[str, Any], tool_calls: int
) -> None:
    run.status = AgentRunStatus.WAITING_APPROVAL
    run.awaiting_step = step_index
    run.awaiting_role = role
    run.tool_call_count = tool_calls
    run.checkpoint = _redact(state)
    run.save(
        update_fields=[
            "status",
            "awaiting_step",
            "awaiting_role",
            "tool_call_count",
            "checkpoint",
            "updated_at",
        ]
    )
    AgentRunEvent.objects.create(
        run=run,
        sequence=_next_sequence(run),
        event_type="run_waiting_approval",
        step_index=step_index,
        decision=DECISION_TOOL,
        outcome="waiting_approval",
    )


def _persist_step(
    *,
    run: Any,
    state: dict[str, Any],
    step_index: int,
    tool_calls: int,
    in_tokens: int,
    out_tokens: int,
    decision: str,
) -> None:
    run.checkpoint = _redact(state)
    run.step_count = step_index
    run.tool_call_count = tool_calls
    run.input_tokens = in_tokens
    run.output_tokens = out_tokens
    run.awaiting_step = None
    run.awaiting_role = ""
    run.save(
        update_fields=[
            "checkpoint",
            "step_count",
            "tool_call_count",
            "input_tokens",
            "output_tokens",
            "awaiting_step",
            "awaiting_role",
            "updated_at",
        ]
    )
    AgentRunEvent.objects.create(
        run=run,
        sequence=_next_sequence(run),
        event_type="step_completed",
        step_index=step_index,
        decision=decision,
        outcome=decision,
        state_checksum=compute_checksum(run.checkpoint),
    )


def _validate_decision(decision: AgentDecision, config: dict[str, Any]) -> None:
    # Defense in depth: an untrusted planner (LangGraph or a compromised model) can never
    # widen the tool surface or emit an out-of-band action.
    if decision.kind not in DECISION_KINDS:
        raise AgentRuntimeError("AGENT_DECISION_INVALID")
    if decision.kind == DECISION_TOOL and decision.role not in config.get("tools", []):
        raise AgentRuntimeError("AGENT_TOOL_NOT_ALLOWED")


def _respond(
    objective: str, state: dict[str, Any], config: dict[str, Any], release: Any
) -> tuple[dict[str, Any], int, int]:
    # Generate over the governed model provider using the retrieved context (P5). The prompt is the
    # authored, release-pinned agent system prompt when present (P6), else the user objective; the
    # objective still drives retrieval. The system prompt is input, never authorization.
    from apps.orchestration.rag_steps import chunks_from_state, generate_for_release

    context = chunks_from_state(state)
    prompt = config.get("system_prompt") or objective or ""
    response = generate_for_release(release=release, context=context, prompt=prompt)
    sources = state.get("retrieval", {}).get("chunks", []) if isinstance(state, dict) else []
    output = {"answer": response.text, "sources": sources if isinstance(sources, list) else []}
    return output, response.input_tokens, response.output_tokens


def _validate_output(release: Any, output: dict[str, Any]) -> None:
    schema = get_artifact_body_for_role(release, "output_contract")
    if schema is not None:
        try:
            jsonschema.validate(output, schema)
        except jsonschema.ValidationError:
            raise AgentRuntimeError("OUTPUT_CONTRACT_VIOLATION") from None
    policy = get_artifact_body_for_role(release, "policy_profile")
    if not isinstance(policy, dict):
        return
    output_policy = policy.get("output", {})
    if not isinstance(output_policy, dict):
        raise AgentRuntimeError("POLICY_VIOLATION")
    if output_policy.get("citations") == "required":
        sources = output.get("sources")
        if not isinstance(sources, list) or not sources:
            raise AgentRuntimeError("POLICY_VIOLATION")


def _objective(state: dict[str, Any], objective_key: str) -> str:
    payload = state.get("input")
    if isinstance(payload, dict):
        value = payload.get(objective_key)
        if isinstance(value, str):
            return value
    return ""


def _tool_input(state: dict[str, Any], config: dict[str, Any], objective: str) -> dict[str, Any]:
    # Deterministic convention: agent tools receive the objective as a ``query`` field.
    # The binding's field allowlist and input contract still gate what is accepted.
    explicit = state.get("tool_input")
    if isinstance(explicit, dict):
        return explicit
    return {"query": objective}
