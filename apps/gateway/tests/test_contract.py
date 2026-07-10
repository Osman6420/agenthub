"""Contract snapshot: the stable set of gateway error codes.

A change here is a public API-contract change and must be intentional (update the
snapshot deliberately, note it in release docs).
"""

from __future__ import annotations

from apps.gateway.errors import ERROR_CODES

EXPECTED_ERROR_CODES = {
    "AUTHENTICATION_REQUIRED",
    "CONSUMER_DISABLED",
    "SCENARIO_NOT_ALLOWED",
    "CAPABILITY_DENIED",
    "IDEMPOTENCY_CONFLICT",
    "RATE_LIMITED",
    "INPUT_CONTRACT_VIOLATION",
    "EXECUTION_CONTEXT_INVALID",
    "RELEASE_NOT_AVAILABLE",
    "RUN_NOT_FOUND",
    "RUNTIME_NOT_AVAILABLE",
    "VALIDATION_ERROR",
    "INTERNAL_ERROR",
}


def test_error_code_set_is_stable() -> None:
    assert set(ERROR_CODES) == EXPECTED_ERROR_CODES
