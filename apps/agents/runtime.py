"""Bounded, guarded execution of a compiled agent's decision loop (Sprint 10 + P2.6.6).

The planner proposes the next action; this runtime is the trust boundary that turns
proposals into governed effects. Every iteration re-checks cancellation, the deadline,
and the step cap; a decision is re-validated against the immutable compiled tool allowlist
and action policy (schema version, kind, role, arguments, verify/escalate opt-in, and the
composition ``allowed_actions`` attenuation); a tool proposal is executed only through the
Sprint 9 tool proxy/approval flow (pausing the run for a required approval); token,
per-role, and state-size caps are enforced; repeated identical actions and non-converging
planners are bounded; and the final output must pass the release output contract and
policy. A resource breach terminates the run deterministically with a stable code — never
an uncontrolled requeue.

Model decisions are proposals, never authorization. The runtime operates on the redacted
durable checkpoint (raw input is redacted at ingress, per the workflow-runtime precedent),
so no raw chain-of-thought, argument body, or unredacted payload is ever persisted or
handed to the planner. Planner-visible observations are bounded, redacted code/count
summaries only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import jsonschema
from django.utils import timezone

from apps.agents.limits import (
    CHECKPOINT_SCHEMA_VERSION,
    MAX_ARGUMENTS_BYTES,
    MAX_OBSERVATION_BYTES,
    MAX_OBSERVATION_CONTEXT_BYTES,
    NO_PROGRESS_LIMIT,
    resolve_limits,
)
from apps.agents.models import AgentRunEvent, AgentRunStatus
from apps.agents.planner import (
    AGENT_DECISION_SCHEMA_VERSION,
    DECISION_ESCALATE,
    DECISION_KINDS,
    DECISION_RESPOND,
    DECISION_RETRIEVE,
    DECISION_TOOL,
    DECISION_VERIFY,
    AgentDecision,
    AgentObservation,
    ObservationSummary,
    get_configured_planner,
)
from apps.agents.services import (
    AgentRequestError,
    _assert_checkpoint_size,
    _next_sequence,
    _redact,
    resolve_release_agent,
)
from apps.artifacts.validation import canonical_json, compute_checksum
from apps.gateway.execution_context import ExecutionContextInvalid, verify_execution_context
from apps.orchestration.runtime import RunResult
from apps.releases.services import get_artifact_body_for_role
from apps.workflows.state_mapping import PROTECTED_WRITE_ROOTS

# Verification target that re-runs the pinned release retrieval (no side effect).
VERIFY_RETRIEVAL = "retrieval"


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
    # Set when the loop terminates via a governed ``escalate`` decision (P2.6.6). Carries a
    # closed, platform-owned envelope (stable reason code + step count); no free text.
    escalation: dict[str, Any] | None = None


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
        status="escalated" if result.escalation else "completed",
        output=result.output,
        usage={"input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
        fallback_used=False,
        metadata={
            "workload_type": "agent",
            "steps": result.steps,
            "tools_called": list(result.tools_called),
            "decisions": list(result.decisions),
            **({"escalation": result.escalation} if result.escalation else {}),
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
    actions = config.get("actions") or {}
    verify_roles = frozenset(actions.get("verify_roles", []))
    role_call_caps = actions.get("role_call_caps") or {}
    repeat_retrieval = bool(actions.get("repeat_retrieval", False))
    escalation_enabled = bool(actions.get("escalation_enabled", False))

    # Child-composition attenuation (P2.6.5): when this agent runs as a pinned ``agent_call``
    # child, the parent call-site's ``max_decisions`` further lowers the step budget, and its
    # authored ``allowed_actions`` restricts the reachable decision kinds. Both are part of the
    # server-signed, already-verified execution context. A parent compiled before P2.6.6 has no
    # ``verify``/``escalate`` in ``allowed_actions``, so those kinds are denied by default.
    max_steps = int(limits["max_steps"])
    composition = (
        run.execution_context.get("composition")
        if isinstance(run.execution_context, dict)
        else None
    )
    allowed_actions: frozenset[str] | None = None
    if isinstance(composition, dict):
        if isinstance(composition.get("max_decisions"), int):
            max_steps = min(max_steps, int(composition["max_decisions"]))
        if isinstance(composition.get("allowed_actions"), list):
            allowed_actions = frozenset(str(a) for a in composition["allowed_actions"])
    objective_key = config["objective_key"]
    output_key = config["output_key"]
    planner = get_configured_planner()

    state = dict(run.checkpoint) if run.checkpoint else dict(run.start_snapshot)
    objective = _objective(state, objective_key)
    retrieved = bool(state.get("_retrieved", False))
    tools_called = tuple(state.get("_tools_called", []))
    role_calls: dict[str, int] = dict(state.get("_role_calls", {}))
    action_checksums: list[str] = list(state.get("_action_checksums", []))
    summaries: list[dict[str, Any]] = list(state.get("_summaries", []))
    step_index = int(run.step_count)
    tool_calls = int(run.tool_call_count)
    in_tokens = int(run.input_tokens)
    out_tokens = int(run.output_tokens)
    resuming_step = run.awaiting_step
    run_ref = str(getattr(run, "public_id", "") or "")
    decisions: list[str] = []
    no_progress = 0

    while True:
        run.refresh_from_db(fields=["status", "deadline_at"])
        if run.status == AgentRunStatus.CANCELLED:
            raise AgentRuntimeError("AGENT_CANCELLED")
        if time.time() > run.deadline_at.timestamp():
            raise AgentRuntimeError("AGENT_TIMED_OUT")
        if step_index >= max_steps:
            raise AgentRuntimeError("AGENT_MAX_STEPS")

        observation = AgentObservation(
            objective,
            retrieved,
            tools_called,
            summaries=tuple(ObservationSummary(**s) for s in summaries),
        )
        is_resume = resuming_step is not None and step_index == resuming_step
        if is_resume:
            decision = AgentDecision(DECISION_TOOL, role=run.awaiting_role, reason_code="resume")
        else:
            decision = planner.next_action(
                config=config, observation=observation, step_index=step_index, run_ref=run_ref
            )
        _validate_decision(
            decision,
            config,
            verify_roles=verify_roles,
            escalation_enabled=escalation_enabled,
            allowed_actions=allowed_actions,
        )

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

        if decision.kind == DECISION_ESCALATE:
            envelope = {"reason_code": _safe_reason_code(decision.reason_code), "steps": step_index}
            state["_escalation"] = envelope
            decisions.append(DECISION_ESCALATE)
            return AgentResult(
                output={},
                state=state,
                steps=step_index + 1,
                tool_calls=tool_calls,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                tools_called=tools_called,
                decisions=tuple(decisions),
                escalation=envelope,
            )

        # retrieve / tool / verify: apply the bounded repeat + per-role budget policy.
        # A soft denial (bounded, planner may self-correct) does not consume a step; after
        # NO_PROGRESS_LIMIT consecutive soft denials the loop terminates deterministically.
        checksum = _action_checksum(decision)
        if not is_resume:
            denial = _policy_denial(
                decision=decision,
                checksum=checksum,
                retrieved=retrieved,
                repeat_retrieval=repeat_retrieval,
                role_calls=role_calls,
                role_call_caps=role_call_caps,
                action_checksums=action_checksums,
            )
            if denial is not None:
                no_progress += 1
                if persist:
                    _emit_denial(run, step_index, decision, denial)
                if no_progress >= NO_PROGRESS_LIMIT:
                    raise AgentRuntimeError("AGENT_NO_PROGRESS")
                continue
        no_progress = 0

        if decision.kind == DECISION_RETRIEVE:
            chunk_count, byte_count = _do_retrieve(run, state, objective)
            retrieved = True
            state["_retrieved"] = True
            _append_summary(
                summaries,
                {
                    "kind": DECISION_RETRIEVE,
                    "role": "",
                    "outcome": "ok",
                    "count": chunk_count,
                    "bytes": byte_count,
                },
            )
        elif decision.kind == DECISION_VERIFY:
            outcome, count, byte_count = _do_verify(
                run=run,
                state=state,
                config=config,
                objective=objective,
                decision=decision,
                step_index=step_index,
                tool_calls=tool_calls,
                role_calls=role_calls,
                persist=persist,
            )
            if decision.role != VERIFY_RETRIEVAL:
                tool_calls = _bump_tool_calls(tool_calls, limits, is_resume=False)
            role_calls[decision.role] = role_calls.get(decision.role, 0) + 1
            _append_summary(
                summaries,
                {
                    "kind": DECISION_VERIFY,
                    "role": decision.role,
                    "outcome": outcome,
                    "count": count,
                    "bytes": byte_count,
                },
            )
        else:  # DECISION_TOOL
            role = decision.role
            if not is_resume:
                tool_calls = _bump_tool_calls(tool_calls, limits, is_resume=False)
                role_calls[role] = role_calls.get(role, 0) + 1
            tool_output = _run_tool_step(
                run=run,
                state=state,
                config=config,
                objective=objective,
                decision=decision,
                step_index=step_index,
                tool_calls=tool_calls,
                role_calls=role_calls,
                summaries=summaries,
                retrieved=retrieved,
                action_checksums=action_checksums,
                persist=persist,
            )
            state["tool_output"] = tool_output
            state.pop("_pending_tool_input", None)
            tools_called = tools_called + (role,)
            state["_tools_called"] = list(tools_called)
            byte_count = (
                len(canonical_json(tool_output).encode("utf-8"))
                if isinstance(tool_output, dict)
                else 0
            )
            _append_summary(
                summaries,
                {
                    "kind": DECISION_TOOL,
                    "role": role,
                    "outcome": "ok",
                    "count": 0,
                    "bytes": byte_count,
                },
            )
            resuming_step = None

        action_checksums.append(checksum)
        state["_role_calls"] = role_calls
        state["_action_checksums"] = action_checksums
        state["_summaries"] = summaries
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


def _bump_tool_calls(tool_calls: int, limits: dict[str, Any], *, is_resume: bool) -> int:
    if is_resume:
        return tool_calls
    tool_calls += 1
    if tool_calls > limits["max_tool_calls"]:
        raise AgentRuntimeError("AGENT_MAX_TOOL_CALLS")
    return tool_calls


def _do_retrieve(run: Any, state: dict[str, Any], objective: str) -> tuple[int, int]:
    # Governed release-scoped retrieval (P5): the P4 document-ACL retriever behind the
    # same provider seam as run_rag. Deterministic default keeps CI hermetic.
    from apps.orchestration.rag_steps import retrieve_for_release

    try:
        retrieval = retrieve_for_release(
            release=run.release, query=objective, consumer_id=run.consumer_id
        )
    except Exception as exc:
        raise AgentRuntimeError("AGENT_RETRIEVAL_FAILED") from exc
    state["retrieval"] = retrieval
    chunks = retrieval.get("chunks", []) if isinstance(retrieval, dict) else []
    chunk_count = len(chunks) if isinstance(chunks, list) else 0
    byte_count = (
        len(canonical_json(retrieval).encode("utf-8")) if isinstance(retrieval, dict) else 0
    )
    return chunk_count, byte_count


def _do_verify(
    *,
    run: Any,
    state: dict[str, Any],
    config: dict[str, Any],
    objective: str,
    decision: AgentDecision,
    step_index: int,
    tool_calls: int,
    role_calls: dict[str, int],
    persist: bool,
) -> tuple[str, int, int]:
    """Execute a governed no-side-effect verification observation and derive its outcome.

    A verification role is compiler-guaranteed to be either release retrieval or a pinned
    no-side-effect, no-approval tool. The outcome is a stable code only: ``verified`` when
    the observation returns data, ``inconclusive`` when it is empty. Errors already raise.
    """
    if decision.role == VERIFY_RETRIEVAL:
        chunk_count, byte_count = _do_retrieve(run, state, objective)
        state["_retrieved"] = True
        return ("verified" if chunk_count else "inconclusive"), chunk_count, byte_count
    tool_output = _run_tool_step(
        run=run,
        state=state,
        config=config,
        objective=objective,
        decision=decision,
        step_index=step_index,
        tool_calls=tool_calls,
        role_calls=role_calls,
        summaries=None,
        retrieved=False,
        action_checksums=None,
        persist=persist,
    )
    state["verification"] = tool_output
    state.pop("_pending_tool_input", None)
    byte_count = (
        len(canonical_json(tool_output).encode("utf-8")) if isinstance(tool_output, dict) else 0
    )
    return ("verified" if tool_output else "inconclusive"), (1 if tool_output else 0), byte_count


def _run_tool_step(
    *,
    run: Any,
    state: dict[str, Any],
    config: dict[str, Any],
    objective: str,
    decision: AgentDecision,
    step_index: int,
    tool_calls: int,
    role_calls: dict[str, int],
    summaries: list[dict[str, Any]] | None,
    retrieved: bool,
    action_checksums: list[str] | None,
    persist: bool,
) -> dict[str, Any]:
    """Execute one governed tool call, pausing the run if approval is pending."""
    from apps.tools.approvals import ToolApprovalError, execute_invocation, request_tool_invocation
    from apps.tools.models import ToolInvocationStatus

    role = decision.role
    is_resume = run.awaiting_step is not None and step_index == run.awaiting_step
    if is_resume and isinstance(state.get("_pending_tool_input"), dict):
        tool_input = dict(state["_pending_tool_input"])
    else:
        tool_input = _tool_input(state, config, objective, decision)

    # The eval candidate seam runs without a consumer; produce a deterministic stub so
    # tool-using agents stay evaluable without real egress or approval.
    if getattr(run, "consumer_id", None) is None:
        return {"status": "ok"}

    # Defense in depth (P2.6.6): re-validate the planner-supplied arguments against the
    # pinned tool contract at the runtime boundary *before* the proxy, which re-validates
    # again. The runtime never builds authority from planner values.
    _validate_arguments_against_contract(run.release, role, tool_input)

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
            _pause_for_approval(run, step_index, role, state, tool_input, tool_calls)
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
    run: Any,
    step_index: int,
    role: str,
    state: dict[str, Any],
    tool_input: dict[str, Any],
    tool_calls: int,
) -> None:
    run.status = AgentRunStatus.WAITING_APPROVAL
    run.awaiting_step = step_index
    run.awaiting_role = role
    run.tool_call_count = tool_calls
    # Persist the exact (already redacted) tool input so the approval-driven resume
    # reproduces the request-checksum-bound input rather than rebuilding it.
    state = dict(state)
    state["_pending_tool_input"] = tool_input
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


def _emit_denial(run: Any, step_index: int, decision: AgentDecision, code: str) -> None:
    """Audit-adjacent durable event for a bounded soft policy denial (no state change)."""
    AgentRunEvent.objects.create(
        run=run,
        sequence=_next_sequence(run),
        event_type="decision_denied",
        step_index=step_index,
        decision=decision.kind,
        outcome="denied",
        reason_code=code,
    )


def _validate_decision(
    decision: AgentDecision,
    config: dict[str, Any],
    *,
    verify_roles: frozenset[str] = frozenset(),
    escalation_enabled: bool = False,
    allowed_actions: frozenset[str] | None = None,
) -> None:
    # Defense in depth: an untrusted planner (LangGraph or a compromised model) can never
    # widen the tool surface, reach an out-of-band action, or emit a mismatched schema.
    if decision.schema_version != AGENT_DECISION_SCHEMA_VERSION:
        raise AgentRuntimeError("AGENT_DECISION_SCHEMA_MISMATCH")
    if decision.kind not in DECISION_KINDS:
        raise AgentRuntimeError("AGENT_DECISION_INVALID")
    # Child-composition attenuation: the parent call-site's allowed_actions is authoritative.
    if allowed_actions is not None and decision.kind not in allowed_actions:
        raise AgentRuntimeError("AGENT_ACTION_NOT_ALLOWED")
    if decision.kind == DECISION_TOOL:
        if decision.role not in config.get("tools", []):
            raise AgentRuntimeError("AGENT_TOOL_NOT_ALLOWED")
    elif decision.kind == DECISION_VERIFY:
        if decision.role not in verify_roles:
            raise AgentRuntimeError("AGENT_VERIFY_NOT_ALLOWED")
    elif decision.kind == DECISION_ESCALATE:
        if not escalation_enabled:
            raise AgentRuntimeError("AGENT_ESCALATE_NOT_ALLOWED")
    # Arguments are only meaningful for role-addressed actions; reject them elsewhere.
    if decision.arguments is not None:
        if decision.kind not in (DECISION_TOOL, DECISION_VERIFY):
            raise AgentRuntimeError("AGENT_ARGUMENTS_INVALID")
        _validate_arguments_shape(decision.arguments)


def _validate_arguments_shape(arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise AgentRuntimeError("AGENT_ARGUMENTS_INVALID")
    if len(canonical_json(arguments).encode("utf-8")) > MAX_ARGUMENTS_BYTES:
        raise AgentRuntimeError("AGENT_ARGUMENTS_INVALID")
    for key in arguments:
        if not isinstance(key, str) or not key or key.startswith("_"):
            raise AgentRuntimeError("AGENT_ARGUMENTS_INVALID")
        if key.strip().casefold() in PROTECTED_WRITE_ROOTS:
            raise AgentRuntimeError("AGENT_ARGUMENTS_INVALID")


def _validate_arguments_against_contract(
    release: Any, role: str, tool_input: dict[str, Any]
) -> None:
    """Runtime-side pre-validation of the tool input against the pinned binding contract."""
    from apps.tools.proxy import ToolExecutionError, resolve_release_tool, validate_tool_input

    try:
        tool = resolve_release_tool(release, role)
        validate_tool_input(tool, tool_input)
    except ToolExecutionError as exc:
        raise AgentRuntimeError(f"TOOL_{exc.code}") from None


def _policy_denial(
    *,
    decision: AgentDecision,
    checksum: str,
    retrieved: bool,
    repeat_retrieval: bool,
    role_calls: dict[str, int],
    role_call_caps: dict[str, Any],
    action_checksums: list[str],
) -> str | None:
    """Return a stable soft-denial code, or ``None`` if the action is admitted by policy.

    Soft denials are bounded (no-progress counted): a repeated identical already-succeeded
    action outside policy, or a per-role budget overrun. Hard structural failures are handled
    earlier in :func:`_validate_decision`.
    """
    if decision.kind == DECISION_RETRIEVE:
        # A plain retrieval repeat is governed by the repeat-retrieval flag. A verification
        # observation (below) is a distinct governed action even when it re-runs retrieval.
        if retrieved and not repeat_retrieval:
            return "AGENT_REPEATED_ACTION"
        return None
    # tool / verify: per-role budget (default single use) governs both fresh and repeat calls.
    role = decision.role
    cap = int(role_call_caps.get(role, 1))
    current = int(role_calls.get(role, 0))
    if current >= cap:
        return (
            "AGENT_REPEATED_ACTION"
            if checksum in action_checksums
            else "AGENT_ROLE_BUDGET_EXCEEDED"
        )
    return None


def _action_checksum(decision: AgentDecision) -> str:
    return compute_checksum(
        {"kind": decision.kind, "role": decision.role, "arguments": decision.arguments or {}}
    )


def _append_summary(summaries: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    """Append a bounded, redacted code/count summary, enforcing the context byte budget."""
    if len(canonical_json(summary).encode("utf-8")) > MAX_OBSERVATION_BYTES:
        # Structurally impossible for code/count summaries, but fail safe rather than persist.
        summary = {
            "kind": summary.get("kind", ""),
            "role": "",
            "outcome": "truncated",
            "count": 0,
            "bytes": 0,
        }
    summaries.append(summary)
    while (
        len(canonical_json(summaries).encode("utf-8")) > MAX_OBSERVATION_CONTEXT_BYTES
        and len(summaries) > 1
    ):
        summaries.pop(0)


def _safe_reason_code(value: str) -> str:
    """Bound and sanitize a planner reason code for the closed escalation envelope."""
    if not isinstance(value, str):
        return "escalated"
    trimmed = value[:64]
    if trimmed and all(ch.isalnum() or ch in "._-" for ch in trimmed):
        return trimmed
    return "escalated"


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


def _tool_input(
    state: dict[str, Any], config: dict[str, Any], objective: str, decision: AgentDecision
) -> dict[str, Any]:
    # Structured planner arguments take precedence (validated at the runtime boundary and
    # again by the proxy). They are redacted for parity with the durable checkpoint so the
    # request-checksum binding holds across an approval pause/resume. Otherwise the
    # deterministic convention applies: agent tools receive the objective as ``query``.
    if decision.arguments is not None:
        return _redact(decision.arguments)
    explicit = state.get("tool_input")
    if isinstance(explicit, dict):
        return explicit
    return {"query": objective}
