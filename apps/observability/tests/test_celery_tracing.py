from __future__ import annotations

from types import SimpleNamespace

from apps.observability.celery_tracing import (
    _ACTIVE,
    finish_task_span,
    inject_trace_headers,
    start_task_span,
)


def test_celery_trace_handlers_ignore_missing_and_invalid_context() -> None:
    headers: dict[str, str] = {}
    inject_trace_headers(headers=headers)
    assert set(headers) <= {"traceparent", "tracestate"}

    task = SimpleNamespace(
        request=SimpleNamespace(
            headers={"traceparent": "invalid", "baggage": "organization_id=other"}
        )
    )
    start_task_span(task_id="task-safe", task=task)
    assert "task-safe" in _ACTIVE
    finish_task_span(task_id="task-safe", state="SUCCESS")
    assert "task-safe" not in _ACTIVE
