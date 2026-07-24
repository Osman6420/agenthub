"""OpenTelemetry configuration and safe W3C trace-context helpers."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

logger = logging.getLogger(__name__)
_configured = False


def configure_tracing() -> None:
    """Configure tracing once; an empty endpoint keeps local/test export disabled."""
    global _configured
    if _configured:
        return
    _configured = True
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    if not endpoint:
        return
    if not _is_endpoint_allowed(endpoint, settings.OTEL_EXPORTER_OTLP_ALLOWED_HOSTS):
        logger.error("OTLP endpoint is not in the approved host allowlist")
        return
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.OTEL_SERVICE_NAME}),
        sampler=ParentBased(TraceIdRatioBased(settings.OTEL_TRACE_SAMPLE_RATIO)),
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint, timeout=2),
            max_queue_size=512,
            max_export_batch_size=128,
            schedule_delay_millis=1000,
            export_timeout_millis=2000,
        )
    )
    trace.set_tracer_provider(provider)


def _is_endpoint_allowed(endpoint: str, allowed_hosts: list[str]) -> bool:
    parsed = urlparse(endpoint)
    return parsed.scheme in {"http", "https"} and parsed.hostname in set(allowed_hosts)


def extract_context(headers: Any) -> Any:
    """Extract only standard propagation fields; baggage never drives auth context."""
    carrier = {
        "traceparent": headers.get("traceparent", "")[:128],
        "tracestate": headers.get("tracestate", "")[:512],
    }
    return propagate.extract(carrier=carrier)


def inject_context(headers: dict[str, str]) -> dict[str, str]:
    propagate.inject(carrier=headers)
    return headers


def current_trace_id() -> str:
    """Return the active span trace ID without creating identity-bearing attributes."""
    span_context = trace.get_current_span().get_span_context()
    return f"{span_context.trace_id:032x}" if span_context.is_valid else ""
