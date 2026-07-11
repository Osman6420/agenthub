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
