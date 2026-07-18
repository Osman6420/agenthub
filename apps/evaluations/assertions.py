"""Deterministic, allowlisted assertions over governed runtime output (Sprint 6).

Each assertion inspects only the *governed* :class:`RunResult` (the same output the
gateway would return) and yields ``(passed, reason_code)``. Reason codes are stable and
content-free, so eval reports never carry raw answers or retrieved text. The set of
supported types is the allowlist enforced at author time by
:func:`apps.artifacts.eval_suite.validate_eval_suite_body`.
"""

from __future__ import annotations

from typing import Any

from apps.orchestration.runtime import RunResult


def _answer(result: RunResult) -> str:
    answer = result.output.get("answer", "")
    return answer if isinstance(answer, str) else ""


def _sources(result: RunResult) -> list[Any]:
    sources = result.output.get("sources", [])
    return sources if isinstance(sources, list) else []


def _meta_list(result: RunResult, key: str) -> list[str]:
    value = result.metadata.get(key, [])
    return [str(v) for v in value] if isinstance(value, list) else []


def evaluate_assertion(assertion: dict[str, Any], result: RunResult) -> tuple[bool, str]:
    """Return ``(passed, reason_code)`` for one allowlisted assertion."""
    kind = assertion["type"]
    if kind == "answer_contains":
        ok = assertion["value"].casefold() in _answer(result).casefold()
        return ok, "matched" if ok else "substring_absent"
    if kind == "answer_not_contains":
        ok = assertion["value"].casefold() not in _answer(result).casefold()
        return ok, "absent" if ok else "substring_present"
    if kind == "grounded":
        ok = not result.fallback_used
        return ok, "grounded" if ok else "fell_back"
    if kind == "not_grounded":
        ok = result.fallback_used
        return ok, "fell_back" if ok else "grounded"
    if kind == "citations_present":
        ok = len(_sources(result)) > 0
        return ok, "citations_present" if ok else "no_citations"
    if kind == "min_sources":
        ok = len(_sources(result)) >= int(assertion["count"])
        return ok, "enough_sources" if ok else "too_few_sources"
    if kind == "workflow_completed":
        ok = result.status == "completed" and result.metadata.get("workload_type") == "workflow"
        return ok, "workflow_completed" if ok else "workflow_incomplete"
    if kind == "node_executed":
        executed = result.metadata.get("executed_nodes", [])
        ok = isinstance(executed, list) and assertion["value"] in executed
        return ok, "node_executed" if ok else "node_not_executed"
    if kind == "agent_completed":
        ok = result.status == "completed" and result.metadata.get("workload_type") == "agent"
        return ok, "agent_completed" if ok else "agent_incomplete"
    if kind == "agent_tool_invoked":
        called = result.metadata.get("tools_called", [])
        ok = isinstance(called, list) and assertion["value"] in called
        return ok, "tool_invoked" if ok else "tool_not_invoked"
    if kind == "agent_no_tools":
        called = result.metadata.get("tools_called", [])
        ok = isinstance(called, list) and len(called) == 0
        return ok, "no_tools" if ok else "tools_invoked"
    if kind == "agent_max_steps":
        steps = result.metadata.get("steps", 0)
        ok = isinstance(steps, int) and steps <= int(assertion["count"])
        return ok, "within_step_budget" if ok else "step_budget_exceeded"
    # --- P2.6.11 agent trajectory evidence (P2.6.6 schema-v2) -----------------------------
    if kind == "agent_verified":
        ok = "verify" in _meta_list(result, "decisions")
        return ok, "verified" if ok else "not_verified"
    if kind == "agent_arguments_valid":
        # A completed agent run means every executed structured decision passed argument
        # validation (invalid arguments terminate the run with a stable failure code).
        decisions = _meta_list(result, "decisions")
        ok = (
            result.status in {"completed", "escalated"}
            and result.metadata.get("workload_type") == "agent"
            and len(decisions) > 0
        )
        return ok, "arguments_valid" if ok else "arguments_invalid"
    if kind == "agent_escalated":
        ok = result.metadata.get("escalation") is not None or "escalate" in _meta_list(
            result, "decisions"
        )
        return ok, "escalated" if ok else "not_escalated"
    # --- P2.6.11 durable workflow-structure evidence -------------------------------------
    # These read redacted summary metadata the workflow candidate seam attaches from durable
    # branch/join/wait/retry/compensation/child records (see run_workflow_candidate). Values
    # are bounded, content-free identifiers (region/branch/node/child ids), never payloads.
    if kind == "workflow_branch_completed":
        ok = assertion["value"] in _meta_list(result, "branches_completed")
        return ok, "branch_completed" if ok else "branch_not_completed"
    if kind == "workflow_join_completed":
        ok = assertion["value"] in _meta_list(result, "joins_completed")
        return ok, "join_completed" if ok else "join_not_completed"
    if kind == "workflow_wait_created":
        ok = assertion["value"] in _meta_list(result, "waits_created")
        return ok, "wait_created" if ok else "wait_not_created"
    if kind == "workflow_wait_resumed":
        ok = assertion["value"] in _meta_list(result, "waits_resumed")
        return ok, "wait_resumed" if ok else "wait_not_resumed"
    if kind == "workflow_wait_expired":
        ok = assertion["value"] in _meta_list(result, "waits_expired")
        return ok, "wait_expired" if ok else "wait_not_expired"
    if kind == "workflow_retry_within":
        attempts = result.metadata.get("max_retry_attempts", 0)
        ok = isinstance(attempts, int) and attempts <= int(assertion["count"])
        return ok, "within_retry_budget" if ok else "retry_budget_exceeded"
    if kind == "workflow_compensation_executed":
        ok = assertion["value"] in _meta_list(result, "compensations_executed")
        return ok, "compensation_executed" if ok else "compensation_not_executed"
    if kind == "workflow_compensation_skipped":
        ok = assertion["value"] in _meta_list(result, "compensations_skipped")
        return ok, "compensation_skipped" if ok else "compensation_not_skipped"
    if kind == "workflow_child_completed":
        ok = assertion["value"] in _meta_list(result, "children_completed")
        return ok, "child_completed" if ok else "child_not_completed"
    # Unreachable: suite validation rejects unknown assertion types before storage.
    return False, "unsupported_assertion"
