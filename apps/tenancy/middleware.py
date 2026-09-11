from __future__ import annotations

from collections.abc import Callable

from django.db import connection, transaction
from django.http import HttpRequest, HttpResponse
from django.urls import Resolver404, resolve

from apps.tenancy.context import operator_transaction

_DURABLE_API_PREFIXES = (
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/runs/",
)


def durable_operator_view(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Mark a view which owns its short operator transactions around durable execution."""
    view.agenthub_durable_operator = True  # type: ignore[attr-defined]
    return view


class TenantContextMiddleware:
    """Install operator scope without enclosing durable API execution in one transaction."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path_info
        if (
            connection.vendor != "postgresql"
            or path.endswith("/health/live")
            or path.startswith(_DURABLE_API_PREFIXES)
        ):
            return self.get_response(request)
        try:
            match = resolve(path, urlconf=getattr(request, "urlconf", None))
        except Resolver404:
            match = None
        if match is not None and getattr(match.func, "agenthub_durable_operator", False):
            return self.get_response(request)
        with operator_transaction(getattr(request, "user", None)):
            response = self.get_response(request)
            if response.status_code >= 500:
                transaction.set_rollback(True)
            return response
