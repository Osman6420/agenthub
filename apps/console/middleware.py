"""Safe local guidance for authenticated console authorization/not-found responses."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.template.loader import get_template


class ConsoleErrorGuidanceMiddleware:
    """Replace technical console HTML 403/404 bodies without changing their status."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        content_type = response.headers.get("Content-Type", "")
        if (
            request.path.startswith("/console/")
            and response.status_code in {403, 404}
            and "text/html" in content_type
        ):
            body = get_template("console/error_guidance.html").render(
                {"status_code": response.status_code}
            )
            replacement = HttpResponse(body, status=response.status_code)
            replacement.headers["Cache-Control"] = "private, no-store"
            replacement.headers["X-Content-Type-Options"] = "nosniff"
            return replacement
        return response
