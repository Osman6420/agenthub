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
    # Unreachable: suite validation rejects unknown assertion types before storage.
    return False, "unsupported_assertion"
