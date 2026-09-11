from __future__ import annotations

from django.urls import path

from apps.mcp.views import McpView

app_name = "mcp"

urlpatterns = [path("", McpView.as_view(), name="streamable-http")]
