from __future__ import annotations

from apps.evaluations.assertions import evaluate_assertion
from apps.orchestration.runtime import RunResult


def test_workflow_assertions_use_redacted_trajectory_metadata() -> None:
    result = RunResult(
        status="completed",
        output={"answer": "ok", "sources": []},
        usage={"input_tokens": 0, "output_tokens": 0},
        fallback_used=False,
        metadata={"workload_type": "workflow", "executed_nodes": ["request", "done"]},
    )
    assert evaluate_assertion({"type": "workflow_completed"}, result) == (
        True,
        "workflow_completed",
    )
    assert evaluate_assertion({"type": "node_executed", "value": "done"}, result) == (
        True,
        "node_executed",
    )
    assert evaluate_assertion({"type": "node_executed", "value": "secret-node"}, result) == (
        False,
        "node_not_executed",
    )


def test_workflow_structure_assertions_read_redacted_summary_metadata() -> None:
    result = RunResult(
        status="completed",
        output={"answer": "ok", "sources": []},
        usage={"input_tokens": 0, "output_tokens": 0},
        fallback_used=False,
        metadata={
            "workload_type": "workflow",
            "executed_nodes": ["request", "done"],
            "branches_completed": ["fan/left"],
            "joins_completed": ["join"],
            "waits_created": ["approve"],
            "waits_resumed": ["approve"],
            "waits_expired": [],
            "max_retry_attempts": 2,
            "compensations_executed": ["charge"],
            "compensations_skipped": [],
            "children_completed": ["review_call"],
        },
    )
    cases: list[tuple[dict[str, object], bool, str]] = [
        ({"type": "workflow_branch_completed", "value": "fan/left"}, True, "branch_completed"),
        (
            {"type": "workflow_branch_completed", "value": "fan/right"},
            False,
            "branch_not_completed",
        ),
        ({"type": "workflow_join_completed", "value": "join"}, True, "join_completed"),
        ({"type": "workflow_wait_created", "value": "approve"}, True, "wait_created"),
        ({"type": "workflow_wait_resumed", "value": "approve"}, True, "wait_resumed"),
        ({"type": "workflow_wait_expired", "value": "approve"}, False, "wait_not_expired"),
        ({"type": "workflow_retry_within", "count": 3}, True, "within_retry_budget"),
        ({"type": "workflow_retry_within", "count": 1}, False, "retry_budget_exceeded"),
        (
            {"type": "workflow_compensation_executed", "value": "charge"},
            True,
            "compensation_executed",
        ),
        (
            {"type": "workflow_compensation_skipped", "value": "charge"},
            False,
            "compensation_not_skipped",
        ),
        ({"type": "workflow_child_completed", "value": "review_call"}, True, "child_completed"),
    ]
    for assertion, passed, reason in cases:
        assert evaluate_assertion(assertion, result) == (passed, reason), assertion


def test_agent_trajectory_assertions_read_decisions_metadata() -> None:
    verified = RunResult(
        status="completed",
        output={"answer": "ok"},
        usage={"input_tokens": 1, "output_tokens": 1},
        fallback_used=False,
        metadata={
            "workload_type": "agent",
            "steps": 3,
            "decisions": ["retrieve", "verify", "respond"],
        },
    )
    escalated = RunResult(
        status="escalated",
        output={},
        usage={"input_tokens": 1, "output_tokens": 0},
        fallback_used=False,
        metadata={
            "workload_type": "agent",
            "steps": 2,
            "decisions": ["retrieve", "escalate"],
            "escalation": {"reason_code": "AGENT_ESCALATED", "steps": 1},
        },
    )
    assert evaluate_assertion({"type": "agent_verified"}, verified) == (True, "verified")
    assert evaluate_assertion({"type": "agent_verified"}, escalated) == (False, "not_verified")
    assert evaluate_assertion({"type": "agent_arguments_valid"}, verified) == (
        True,
        "arguments_valid",
    )
    assert evaluate_assertion({"type": "agent_arguments_valid"}, escalated) == (
        True,
        "arguments_valid",
    )
    assert evaluate_assertion({"type": "agent_escalated"}, escalated) == (True, "escalated")
    assert evaluate_assertion({"type": "agent_escalated"}, verified) == (False, "not_escalated")
