"""Operator builder JSON API URLs (mounted under ``/console/api/builder/``)."""

from __future__ import annotations

from django.urls import path

from apps.builder import api

app_name = "builder_api"

urlpatterns = [
    path("node-schema/", api.node_schema, name="node_schema"),
    path("drafts/", api.drafts, name="drafts"),
    path("drafts/<int:pk>/", api.draft_detail, name="draft_detail"),
    path("drafts/<int:pk>/diagnostics/", api.draft_diagnostics, name="draft_diagnostics"),
    path("drafts/<int:pk>/publish/", api.draft_publish, name="draft_publish"),
]
