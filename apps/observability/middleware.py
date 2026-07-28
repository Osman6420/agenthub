"""Request traces and bounded metrics without payload or identity labels."""

from __future__ import annotations

import time
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from apps.observability.metrics import HTTP_DURATION, HTTP_REQUESTS
from apps.observability.tracing import configure_tracing, extract_context


class TelemetryMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        configure_tracing()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started = time.monotonic()
        transport, operation = _route_dimensions(request.path)
        context = extract_context(request.headers)
        tracer = trace.get_tracer("agenthub.http")
        with tracer.start_as_current_span(
            f"{transport}.{operation}",
            context=context,
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": request.method or "UNKNOWN",
                "http.route.group": operation,
                "agenthub.transport": transport,
            },
        ) as span:
            response = self.get_response(request)
            span.set_attribute("http.response.status_code", response.status_code)
            span_context = span.get_span_context()
            if span_context.is_valid:
                request.trace_id = f"{span_context.trace_id:032x}"  # type: ignore[attr-defined]
                response["Trace-ID"] = request.trace_id  # type: ignore[attr-defined]
        status = _status_class(response.status_code)
        HTTP_REQUESTS.labels(transport=transport, operation=operation, status=status).inc()
        HTTP_DURATION.labels(transport=transport, operation=operation).observe(
            time.monotonic() - started
        )
        return response


def _route_dimensions(path: str) -> tuple[str, str]:
    if path.startswith("/mcp"):
        return "mcp", "rpc"
    if path.startswith("/v1/responses"):
        return "rest", "responses"
    if path.startswith("/v1/chat/completions"):
        return "rest", "chat_completions"
    if path.startswith("/v1/runs"):
        return "rest", "run_status"
    if path.startswith("/v1/health"):
        return "internal", "health"
    if path.startswith("/internal/metrics"):
        return "internal", "metrics"
    return "web", "other"


def _status_class(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "success"
    if status_code in (401, 403):
        return "denied"
    if status_code == 429:
        return "rate_limited"
    if 400 <= status_code < 500:
        return "client_error"
    return "server_error"
