from __future__ import annotations

from collections.abc import Callable

from django.db import connection, transaction
from django.http import HttpRequest, HttpResponse

from apps.tenancy.context import set_tenant_scope
from apps.tenancy.models import Organization
from apps.tenancy.services import allowed_organization_ids


class TenantContextMiddleware:
    """Wrap each request in a transaction and install a trusted operator tenant scope."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if connection.vendor != "postgresql" or request.path.endswith("/health/live"):
            return self.get_response(request)
        with transaction.atomic():
            set_tenant_scope(())
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                allowed = allowed_organization_ids(user)
                if allowed is None:
                    allowed = set(Organization.objects.values_list("id", flat=True))
                set_tenant_scope(allowed)
            response = self.get_response(request)
            if response.status_code >= 500:
                transaction.set_rollback(True)
            return response
