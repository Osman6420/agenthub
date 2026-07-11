"""Structural validation for the ``eval_suite`` artifact type (Sprint 6).

An eval suite is *data, not code*: a bounded list of cases, each with a bounded input
and an allowlisted set of deterministic assertions over the governed runtime output.
The same allowlist drives execution in :mod:`apps.evaluations.assertions`, so an
author can never pin an assertion the engine cannot evaluate, and an eval can never run
arbitrary logic.

This module has no dependency on :mod:`apps.artifacts.validation` (which imports it),
so it raises a plain ``ValueError`` subclass that ``validate_body`` re-wraps.
"""

from __future__ import annotations

import json
from typing import Any

MAX_CASES = 100
MAX_ASSERTIONS_PER_CASE = 20
MAX_INPUT_BYTES = 4000
MAX_VALUE_LENGTH = 500
MAX_MIN_SOURCES = 100

# Assertions requiring a non-empty string ``value``.
_VALUE_ASSERTIONS = frozenset(
    {"answer_contains", "answer_not_contains", "node_executed", "agent_tool_invoked"}
)
# Assertions taking no parameters.
_NULLARY_ASSERTIONS = frozenset(
    {
        "grounded",
        "not_grounded",
        "citations_present",
        "workflow_completed",
        "agent_completed",
        "agent_no_tools",
    }
)
# Assertions requiring an integer ``count`` >= 1.
_COUNT_ASSERTIONS = frozenset({"min_sources", "agent_max_steps"})

ASSERTION_TYPES: frozenset[str] = _VALUE_ASSERTIONS | _NULLARY_ASSERTIONS | _COUNT_ASSERTIONS


class EvalSuiteError(ValueError):
    """Raised when an eval-suite body is malformed or exceeds its bounds."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvalSuiteError(message)


def _validate_assertion(assertion: Any, where: str) -> None:
    _require(isinstance(assertion, dict), f"{where}: assertion must be a mapping")
    kind = assertion.get("type")
    _require(kind in ASSERTION_TYPES, f"{where}: unsupported assertion type {kind!r}")
    extra = set(assertion) - {"type", "value", "count"}
    _require(not extra, f"{where}: unsupported assertion keys: {', '.join(sorted(extra))}")
    if kind in _VALUE_ASSERTIONS:
        value = assertion.get("value")
        _require(
            isinstance(value, str) and 0 < len(value) <= MAX_VALUE_LENGTH,
            f"{where}: {kind} requires a 'value' string (1..{MAX_VALUE_LENGTH} chars)",
        )
        _require("count" not in assertion, f"{where}: {kind} does not take 'count'")
    elif kind in _COUNT_ASSERTIONS:
        count = assertion.get("count")
        _require(
            isinstance(count, int)
            and not isinstance(count, bool)
            and 1 <= count <= MAX_MIN_SOURCES,
            f"{where}: {kind} requires an integer 'count' (1..{MAX_MIN_SOURCES})",
        )
        _require("value" not in assertion, f"{where}: {kind} does not take 'value'")
    else:  # nullary
        _require(
            "value" not in assertion and "count" not in assertion,
            f"{where}: {kind} takes no parameters",
        )


def validate_eval_suite_body(body: Any) -> None:
    """Validate the structure and bounds of an eval-suite artifact body.

    Raises :class:`EvalSuiteError` (a ``ValueError``) on the first problem found.
    """
    _require(isinstance(body, dict), "eval suite body must be a JSON object")
    extra_top = set(body) - {"cases"}
    _require(not extra_top, f"unsupported eval suite keys: {', '.join(sorted(extra_top))}")
    cases = body.get("cases")
    _require(
        isinstance(cases, list) and bool(cases), "eval suite must define a non-empty 'cases' list"
    )
    _require(len(cases) <= MAX_CASES, f"eval suite exceeds {MAX_CASES} cases")

    seen_ids: set[str] = set()
    for position, case in enumerate(cases):
        where = f"case[{position}]"
        _require(isinstance(case, dict), f"{where} must be a mapping")
        extra_case = set(case) - {"id", "input", "assertions"}
        _require(not extra_case, f"{where}: unsupported keys: {', '.join(sorted(extra_case))}")

        case_id = case.get("id")
        _require(
            isinstance(case_id, str) and bool(case_id), f"{where}: 'id' must be a non-empty string"
        )
        _require(case_id not in seen_ids, f"{where}: duplicate case id {case_id!r}")
        seen_ids.add(case_id)

        case_input = case.get("input")
        _require(isinstance(case_input, dict), f"{where}: 'input' must be a mapping")
        size = len(json.dumps(case_input, ensure_ascii=False).encode("utf-8"))
        _require(size <= MAX_INPUT_BYTES, f"{where}: input exceeds {MAX_INPUT_BYTES} bytes")

        assertions = case.get("assertions")
        _require(
            isinstance(assertions, list) and bool(assertions),
            f"{where}: 'assertions' must be a non-empty list",
        )
        _require(
            len(assertions) <= MAX_ASSERTIONS_PER_CASE,
            f"{where}: exceeds {MAX_ASSERTIONS_PER_CASE} assertions",
        )
        for a_pos, assertion in enumerate(assertions):
            _validate_assertion(assertion, f"{where}.assertions[{a_pos}]")
