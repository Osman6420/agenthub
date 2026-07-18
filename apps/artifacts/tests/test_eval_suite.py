"""Structural validation of the eval_suite artifact type (Sprint 6)."""

from __future__ import annotations

import pytest

from apps.artifacts.eval_suite import (
    MAX_CASES,
    EvalSuiteError,
    validate_eval_suite_body,
)
from apps.artifacts.validation import ArtifactValidationError, validate_body


def _valid_suite() -> dict:
    return {
        "cases": [
            {
                "id": "returns-14-days",
                "input": {"query": "iade suresi"},
                "assertions": [
                    {"type": "answer_contains", "value": "14"},
                    {"type": "grounded"},
                    {"type": "min_sources", "count": 1},
                ],
            }
        ]
    }


def test_valid_suite_passes() -> None:
    validate_eval_suite_body(_valid_suite())  # no raise


def test_p2611_workflow_and_agent_assertion_vocabulary_is_allowlisted() -> None:
    suite = _valid_suite()
    suite["cases"][0]["assertions"] = [
        {"type": "workflow_branch_completed", "value": "fan/left"},
        {"type": "workflow_join_completed", "value": "join"},
        {"type": "workflow_wait_created", "value": "approve"},
        {"type": "workflow_wait_resumed", "value": "approve"},
        {"type": "workflow_wait_expired", "value": "approve"},
        {"type": "workflow_retry_within", "count": 3},
        {"type": "workflow_compensation_executed", "value": "charge"},
        {"type": "workflow_compensation_skipped", "value": "charge"},
        {"type": "workflow_child_completed", "value": "review_call"},
        {"type": "agent_verified"},
        {"type": "agent_arguments_valid"},
        {"type": "agent_escalated"},
    ]
    validate_eval_suite_body(suite)  # no raise


def test_p2611_value_kind_rejects_missing_value() -> None:
    suite = _valid_suite()
    suite["cases"][0]["assertions"] = [{"type": "workflow_branch_completed"}]
    with pytest.raises(EvalSuiteError, match="requires a 'value'"):
        validate_eval_suite_body(suite)


def test_p2611_retry_within_requires_count() -> None:
    suite = _valid_suite()
    suite["cases"][0]["assertions"] = [{"type": "workflow_retry_within", "value": "x"}]
    with pytest.raises(EvalSuiteError):
        validate_eval_suite_body(suite)


def test_unknown_assertion_type_is_rejected() -> None:
    suite = _valid_suite()
    suite["cases"][0]["assertions"] = [{"type": "sql_injection", "value": "x"}]
    with pytest.raises(EvalSuiteError, match="unsupported assertion type"):
        validate_eval_suite_body(suite)


def test_value_assertion_requires_bounded_value() -> None:
    suite = _valid_suite()
    suite["cases"][0]["assertions"] = [{"type": "answer_contains", "value": ""}]
    with pytest.raises(EvalSuiteError, match="requires a 'value'"):
        validate_eval_suite_body(suite)


def test_min_sources_requires_positive_integer() -> None:
    suite = _valid_suite()
    suite["cases"][0]["assertions"] = [{"type": "min_sources", "count": 0}]
    with pytest.raises(EvalSuiteError, match="integer 'count'"):
        validate_eval_suite_body(suite)


def test_boolean_is_not_a_valid_count() -> None:
    suite = _valid_suite()
    suite["cases"][0]["assertions"] = [{"type": "min_sources", "count": True}]
    with pytest.raises(EvalSuiteError, match="integer 'count'"):
        validate_eval_suite_body(suite)


def test_duplicate_case_ids_are_rejected() -> None:
    suite = _valid_suite()
    suite["cases"].append(dict(suite["cases"][0]))
    with pytest.raises(EvalSuiteError, match="duplicate case id"):
        validate_eval_suite_body(suite)


def test_too_many_cases_is_rejected() -> None:
    suite = {
        "cases": [
            {"id": f"c{i}", "input": {"query": "q"}, "assertions": [{"type": "grounded"}]}
            for i in range(MAX_CASES + 1)
        ]
    }
    with pytest.raises(EvalSuiteError, match="exceeds"):
        validate_eval_suite_body(suite)


def test_oversized_input_is_rejected() -> None:
    suite = _valid_suite()
    suite["cases"][0]["input"] = {"query": "x" * 5000}
    with pytest.raises(EvalSuiteError, match="input exceeds"):
        validate_eval_suite_body(suite)


def test_unknown_top_level_key_is_rejected() -> None:
    suite = _valid_suite()
    suite["exec"] = "rm -rf"
    with pytest.raises(EvalSuiteError, match="unsupported eval suite keys"):
        validate_eval_suite_body(suite)


def test_validate_body_wraps_eval_suite_errors() -> None:
    suite = _valid_suite()
    suite["cases"][0]["assertions"] = [{"type": "nope"}]
    with pytest.raises(ArtifactValidationError, match="unsupported assertion type"):
        validate_body("eval_suite", suite)
