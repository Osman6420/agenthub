"""Operator builder JSON API URLs (mounted under ``/console/api/builder/``)."""

from __future__ import annotations

from django.urls import path

from apps.builder import api

app_name = "builder_api"

urlpatterns = [
    path("node-schema/", api.node_schema, name="node_schema"),
    path("ai-candidates/", api.ai_candidates, name="ai_candidates"),
    path("ai-candidates/accept/", api.ai_candidate_accept, name="ai_candidate_accept"),
    path("drafts/", api.drafts, name="drafts"),
    path("drafts/<int:pk>/", api.draft_detail, name="draft_detail"),
    path("drafts/<int:pk>/diagnostics/", api.draft_diagnostics, name="draft_diagnostics"),
    path("drafts/<int:pk>/publish/", api.draft_publish, name="draft_publish"),
]
