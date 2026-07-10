from __future__ import annotations

import secrets

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound

from apps.observability.metrics import render_metrics


def metrics(request: HttpRequest) -> HttpResponse:
    """Authenticated scrape endpoint; network policy remains defense in depth."""
    expected = settings.METRICS_BEARER_TOKEN
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    supplied = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
    if (
        not settings.METRICS_ENABLED
        or not expected
        or not supplied
        or not secrets.compare_digest(supplied, expected)
    ):
        return HttpResponseNotFound()
    return HttpResponse(render_metrics(), content_type="text/plain; version=0.0.4; charset=utf-8")
