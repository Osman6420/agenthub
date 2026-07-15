from __future__ import annotations

import pytest
from django.conf import settings
from django.test import Client

from apps.observability.middleware import _route_dimensions, _status_class
from apps.observability.tracing import _is_endpoint_allowed, extract_context

pytestmark = pytest.mark.django_db


def test_metrics_endpoint_has_bounded_labels_and_no_sensitive_dimensions() -> None:
    client = Client()
    client.get("/v1/health/live")
    response = client.get(
        "/internal/metrics",
        HTTP_AUTHORIZATION=f"Bearer {settings.METRICS_BEARER_TOKEN}",
    )
    assert response.status_code == 200
    text = response.content.decode()
    assert "agenthub_gateway_requests_total" in text
    assert "transport=" in text
    assert "operation=" in text
    assert "status=" in text
    assert "consumer=" not in text
    assert "organization=" not in text
    assert "token=" not in text


def test_metrics_endpoint_hides_existence_without_valid_scrape_token() -> None:
    client = Client()
    assert client.get("/internal/metrics").status_code == 404
    assert client.get("/internal/metrics", HTTP_AUTHORIZATION="Bearer wrong").status_code == 404


def test_invalid_trace_headers_are_untrusted_and_do_not_fail_request() -> None:
    context = extract_context(
        {
            "traceparent": "invalid\r\nAuthorization: Bearer leaked",
            "tracestate": "tenant=other",
            "baggage": "organization_id=999,role=admin",
        }
    )
    assert context is not None
    response = Client().get(
        "/v1/health/live",
        HTTP_TRACEPARENT="invalid",
        HTTP_BAGGAGE="organization_id=999,role=admin",
    )
    assert response.status_code == 200


def test_metric_dimensions_are_fixed() -> None:
    assert _route_dimensions("/mcp/") == ("mcp", "rpc")
    assert _route_dimensions("/v1/query") == ("rest", "query")
    assert _route_dimensions("/unknown/tenant-123") == ("web", "other")
    assert {_status_class(code) for code in (200, 401, 403, 404, 429, 500)} == {
        "success",
        "denied",
        "client_error",
        "rate_limited",
        "server_error",
    }


def test_otlp_endpoint_requires_exact_approved_host_and_http_scheme() -> None:
    assert _is_endpoint_allowed("https://otel.internal/v1/traces", ["otel.internal"])
    assert not _is_endpoint_allowed("https://attacker.example/v1/traces", ["otel.internal"])
    assert not _is_endpoint_allowed("file:///etc/passwd", ["otel.internal"])
    assert not _is_endpoint_allowed("https://otel.internal.attacker.example", ["otel.internal"])
