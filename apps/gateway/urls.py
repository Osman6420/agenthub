"""Gateway URLs, mounted under ``/v1/`` (v3 plan §11.3).

Health probes are unauthenticated; invoke/query/runs require an authenticated
consumer (enforced by the DRF permission).
"""

from __future__ import annotations

from django.urls import path

from apps.gateway import health, views

app_name = "gateway"

urlpatterns = [
    path("health/live", health.live, name="health-live"),
    path("health/ready", health.ready, name="health-ready"),
    path("invoke", views.InvokeView.as_view(), name="invoke"),
    path("query", views.QueryView.as_view(), name="query"),
    path("chat/completions", views.ChatCompletionsView.as_view(), name="chat-completions"),
    path("responses", views.ResponsesView.as_view(), name="responses"),
    path("runs/<str:run_id>", views.RunStatusView.as_view(), name="run-status"),
]
