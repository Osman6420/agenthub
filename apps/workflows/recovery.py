"""Server-owned workflow failure classification and bounded recovery policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FailureClass = Literal["validation", "authorization", "permanent", "transient", "outcome_unknown"]

_OUTCOME_UNKNOWN_MARKERS = ("OUTCOME_UNKNOWN", "AMBIGUOUS")
_AUTHORIZATION_MARKERS = (
    "AUTH",
    "CAPABILITY_DENIED",
    "CROSS_TENANT",
    "POLICY_VIOLATION",
    "APPROVAL",
    "DISABLED",
    "NOT_ALLOWED",
    "NOT_PINNED",
)
_VALIDATION_MARKERS = (
    "INVALID",
    "VALIDATION",
    "CONTRACT_VIOLATION",
    "SCHEMA",
    "MAPPING",
    "PATH_",
    "OUTPUT_MISSING",
    "FIELD_NOT_ALLOWED",
    "STATE_TOO_LARGE",
    "RESPONSE_TOO_LARGE",
)
_TRANSIENT_CODES = frozenset(
    {
        "WORKFLOW_RETRIEVAL_FAILED",
        "WORKFLOW_GENERATION_FAILED",
        "WORKFLOW_NODE_TIMED_OUT",
        "TOOL_ADAPTER_UNAVAILABLE",
        "TOOL_CONNECTION_FAILED",
        "TOOL_RATE_LIMITED",
        "COMPOSITION_CHILD_TIMED_OUT",
    }
)


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    next_attempt: int
    countdown_seconds: int


def classify_failure(code: str) -> FailureClass:
    """Classify a stable code; unknown values fail closed as permanent."""
    canonical = str(code).upper()[:64]
    if any(marker in canonical for marker in _OUTCOME_UNKNOWN_MARKERS):
        return "outcome_unknown"
    if any(marker in canonical for marker in _AUTHORIZATION_MARKERS):
        return "authorization"
    if any(marker in canonical for marker in _VALIDATION_MARKERS):
        return "validation"
    if canonical in _TRANSIENT_CODES:
        return "transient"
    return "permanent"


def retry_decision(
    *, policy: dict[str, Any] | None, failure_class: FailureClass, completed_attempts: int
) -> RetryDecision:
    if policy is None or failure_class != "transient" or policy.get("idempotent") is not True:
        return RetryDecision(False, completed_attempts, 0)
    max_attempts = int(policy.get("max_attempts", 1))
    next_attempt = completed_attempts + 1
    if next_attempt > max_attempts:
        return RetryDecision(False, next_attempt, 0)
    base = int(policy.get("backoff_seconds", 0))
    # Deterministic capped exponential component. Deployment jitter is added by the broker layer;
    # keeping this helper deterministic makes replay and tests stable.
    countdown = min(base * (2 ** max(completed_attempts - 1, 0)), 300)
    return RetryDecision(True, next_attempt, countdown)


def select_error_route(
    *, edges: list[dict[str, Any]], node_id: str, failure_class: FailureClass
) -> str | None:
    exact = next(
        (
            edge["to"]
            for edge in edges
            if edge["from"] == node_id and edge.get("on_error") == failure_class
        ),
        None,
    )
    if exact is not None:
        return str(exact)
    fallback = next(
        (edge["to"] for edge in edges if edge["from"] == node_id and edge.get("on_error") == "any"),
        None,
    )
    return str(fallback) if fallback is not None else None
