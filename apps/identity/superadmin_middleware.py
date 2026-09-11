"""Fail-closed audit boundary for exceptional superadmin console use."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.urls import Resolver404, resolve

from apps.audit.services import record_event
from apps.observability.tracing import current_trace_id

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class SuperadminAuditMiddleware:
    """Persist an audit event before any authenticated superadmin console action."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if (
            request.path_info.startswith("/console/")
            and getattr(user, "is_authenticated", False)
            and getattr(user, "is_superuser", False)
        ):
            try:
                match = resolve(request.path_info)
                route_name = match.view_name or "console:unknown"
            except Resolver404:
                route_name = "console:not_found"
            organization_id = request.session.get("active_organization_id")
            if not isinstance(organization_id, int):
                organization_id = None
            record_event(
                actor_type="user",
                actor_id=str(getattr(user, "pk", "")),
                action="superadmin.console_access",
                outcome="allow",
                organization_id=organization_id,
                resource_type="route",
                resource_id=route_name[:255],
                reason="read" if request.method in _SAFE_METHODS else "mutation",
                request_id=str(getattr(request, "request_id", ""))[:64],
                trace_id=current_trace_id(),
            )
        return self.get_response(request)
