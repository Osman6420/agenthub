"""Propagate W3C trace context through Celery message headers."""

from __future__ import annotations

from typing import Any

from celery.signals import before_task_publish, task_postrun, task_prerun
from opentelemetry import context, propagate, trace
from opentelemetry.trace import SpanKind

_ACTIVE: dict[str, tuple[Any, Any]] = {}


@before_task_publish.connect
def inject_trace_headers(headers: dict[str, Any] | None = None, **kwargs: Any) -> None:
    if headers is None:
        return
    carrier: dict[str, str] = {}
    propagate.inject(carrier=carrier)
    for key in ("traceparent", "tracestate"):
        value = carrier.get(key)
        if value:
            headers[key] = value[:512]


@task_prerun.connect
def start_task_span(task_id: str | None = None, task: Any = None, **kwargs: Any) -> None:
    if not task_id:
        return
    request_headers = getattr(getattr(task, "request", None), "headers", None) or {}
    carrier = {
        "traceparent": str(request_headers.get("traceparent", ""))[:128],
        "tracestate": str(request_headers.get("tracestate", ""))[:512],
    }
    parent = propagate.extract(carrier=carrier)
    token = context.attach(parent)
    span = trace.get_tracer("agenthub.celery").start_span(
        "celery.task",
        kind=SpanKind.CONSUMER,
        attributes={"messaging.system": "celery"},
    )
    _ACTIVE[task_id] = (span, token)


@task_postrun.connect
def finish_task_span(task_id: str | None = None, state: str | None = None, **kwargs: Any) -> None:
    if not task_id:
        return
    active = _ACTIVE.pop(task_id, None)
    if active is None:
        return
    span, token = active
    if state:
        span.set_attribute("celery.state", state)
    span.end()
    context.detach(token)
