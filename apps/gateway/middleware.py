"""Attach a stable request id to every request and echo it back.

Honors an inbound ``X-Request-ID`` (trusted at the edge) or generates one. The id
flows into the error envelope, audit, and usage events for correlation.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

_HEADER = "HTTP_X_REQUEST_ID"
_MAX_LEN = 64


class RequestIDMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        inbound = request.META.get(_HEADER, "")
        request_id = inbound[:_MAX_LEN] if inbound else f"req_{uuid.uuid4().hex}"
        request.request_id = request_id  # type: ignore[attr-defined]
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response
