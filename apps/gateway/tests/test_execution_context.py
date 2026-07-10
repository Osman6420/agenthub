"""ExecutionContext signing, verification, tampering, and expiry."""

from __future__ import annotations

import pytest

from apps.gateway.execution_context import (
    ExecutionContextInvalid,
    issue_execution_context,
    verify_execution_context,
)


def _issue(ttl_seconds: int = 300) -> dict:
    return issue_execution_context(
        organization_id=1,
        project_id=2,
        scenario_id=3,
        scenario_alias="customer-information",
        consumer_id=4,
        capabilities=["query"],
        release_id=5,
        request_id="req_test",
        ttl_seconds=ttl_seconds,
    )


def test_issue_and_verify_roundtrip() -> None:
    ctx = _issue()
    payload = verify_execution_context(ctx)
    assert payload["scenario_alias"] == "customer-information"
    assert payload["release_id"] == 5
    assert "signature" not in payload


def test_tampering_is_detected() -> None:
    ctx = _issue()
    ctx["release_id"] = 999  # escalate to a different release
    with pytest.raises(ExecutionContextInvalid, match="bad signature"):
        verify_execution_context(ctx)


def test_expired_context_is_rejected() -> None:
    ctx = _issue(ttl_seconds=-1)  # already expired
    with pytest.raises(ExecutionContextInvalid, match="expired"):
        verify_execution_context(ctx)


def test_missing_signature_is_rejected() -> None:
    with pytest.raises(ExecutionContextInvalid):
        verify_execution_context({"scenario_alias": "x"})
