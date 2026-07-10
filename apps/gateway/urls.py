"""Gateway URLs. Sprint 0 exposes only health probes under ``/v1/health/``."""

from __future__ import annotations

from django.urls import path

from apps.gateway import health

app_name = "gateway"

urlpatterns = [
    path("live", health.live, name="health-live"),
    path("ready", health.ready, name="health-ready"),
]
