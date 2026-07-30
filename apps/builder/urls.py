"""Operator builder JSON API URLs (mounted under ``/console/api/builder/``)."""

from __future__ import annotations

from django.urls import path

from apps.builder import api

app_name = "builder_api"

urlpatterns = [
    path("node-schema/", api.node_schema, name="node_schema"),
    path("ai-candidates/", api.ai_candidates, name="ai_candidates"),
    path("ai-candidates/repair/", api.ai_candidate_repair, name="ai_candidate_repair"),
    path("ai-candidates/accept/", api.ai_candidate_accept, name="ai_candidate_accept"),
    path("transient-diagnostics/", api.transient_diagnostics, name="transient_diagnostics"),
    path(
        "scenarios/<uuid:public_id>/release-manifest/preflight/",
        api.release_manifest_preflight,
        name="release_manifest_preflight",
    ),
    path(
        "scenarios/<uuid:public_id>/release-manifest/requirements/",
        api.release_manifest_requirements,
        name="release_manifest_requirements",
    ),
    path(
        "scenarios/<uuid:public_id>/release-manifest/compile/",
        api.release_manifest_compile,
        name="release_manifest_compile",
    ),
    path("artifact-drafts/", api.artifact_drafts, name="artifact_drafts"),
    path(
        "artifact-drafts/<int:pk>/",
        api.artifact_draft_detail,
        name="artifact_draft_detail",
    ),
    path(
        "artifact-drafts/<int:pk>/diagnostics/",
        api.artifact_draft_diagnostics,
        name="artifact_draft_diagnostics",
    ),
    path("drafts/", api.drafts, name="drafts"),
    path("drafts/<int:pk>/", api.draft_detail, name="draft_detail"),
    path("drafts/<int:pk>/diagnostics/", api.draft_diagnostics, name="draft_diagnostics"),
    path("drafts/<int:pk>/publish/", api.draft_publish, name="draft_publish"),
]
