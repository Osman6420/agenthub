from __future__ import annotations

import pytest

from apps.audit.services import record_event
from apps.observability.metrics import REGISTRY
from apps.observability.models import UsageEvent


@pytest.mark.django_db
def test_canonical_usage_and_release_audit_increment_bounded_metrics() -> None:
    UsageEvent.objects.create(
        request_id="safe-id",
        operation="query",
        status="completed",
        input_tokens=3,
        output_tokens=5,
    )
    record_event(
        actor_type="system",
        actor_id="worker",
        action="release.promote",
        outcome="allow",
        resource_type="release",
        resource_id="1",
    )
    names = {metric.name for metric in REGISTRY.collect()}
    assert "agenthub_runtime_requests" in names
    assert "agenthub_tokens" in names
    assert "agenthub_release_lifecycle" in names
