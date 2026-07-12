"""Operator document-plane JSON API URLs (mounted under ``/console/api/documents/``)."""

from __future__ import annotations

from django.urls import path

from apps.documents import api

app_name = "documents_api"

urlpatterns = [
    path("documents/", api.documents, name="documents"),
    path("documents/<int:pk>/", api.document_detail, name="document_detail"),
    path("documents/<int:pk>/purge/", api.document_purge, name="document_purge"),
    path("document-sets/", api.document_sets, name="document_sets"),
    path(
        "document-sets/<int:pk>/versions/", api.document_set_versions, name="document_set_versions"
    ),
    path(
        "document-set-versions/<int:pk>/members/",
        api.set_version_members,
        name="set_version_members",
    ),
    path(
        "document-set-versions/<int:pk>/publish/",
        api.set_version_publish,
        name="set_version_publish",
    ),
]
