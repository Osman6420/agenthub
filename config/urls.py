"""Root URL configuration.

The operator console (`/console/`) is the management surface (ADR-0001). Django
Admin is routed only when ``ENABLE_DJANGO_ADMIN`` is set (local dev), never in
production. Unauthenticated operational health probes live under `/v1/health/`.
The authenticated public product API (`/v1/invoke` ...) is added with the gateway
in Sprint 3.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView

from apps.observability.views import metrics

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="console:dashboard", permanent=False)),
    path("console/api/builder/", include("apps.builder.urls")),
    path("console/", include("apps.console.urls")),
    path("v1/", include("apps.gateway.urls")),
    path("mcp/", include("apps.mcp.urls")),
    path("internal/metrics", metrics, name="metrics"),
]

if getattr(settings, "ENABLE_DJANGO_ADMIN", False):
    from django.contrib import admin

    urlpatterns.append(path("admin/", admin.site.urls))
