"""Operator console URLs (all under ``/console/``)."""

from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.urls import path

from apps.console import views

app_name = "console"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="console/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("organizations/", views.organizations, name="organizations"),
    path("organizations/new/", views.organization_create, name="organization_create"),
    path("projects/", views.projects, name="projects"),
    path("projects/new/", views.project_create, name="project_create"),
    path("scenarios/", views.scenarios, name="scenarios"),
    path("scenarios/new/", views.scenario_create, name="scenario_create"),
    path("consumers/", views.consumers, name="consumers"),
    path("consumers/new/", views.consumer_create, name="consumer_create"),
    path("bindings/new/", views.binding_create, name="binding_create"),
    path("artifacts/", views.artifacts, name="artifacts"),
    path("releases/", views.releases, name="releases"),
    path("releases/<int:release_id>/eval/", views.release_run_eval, name="release_run_eval"),
    path("releases/<int:release_id>/promote/", views.release_promote, name="release_promote"),
    path("releases/<int:release_id>/rollback/", views.release_rollback, name="release_rollback"),
    path("releases/<int:release_id>/canary/", views.canary_start, name="canary_start"),
    path("canaries/<int:canary_id>/stop/", views.canary_stop, name="canary_stop"),
    path("builder/", views.builder, name="builder"),
    path("documents/", views.documents, name="documents"),
    path("documents/upload/", views.document_upload, name="document_upload"),
    path(
        "documents/<int:pk>/soft-delete/",
        views.document_soft_delete,
        name="document_soft_delete",
    ),
    path("document-sets/new/", views.document_set_create, name="document_set_create"),
    path("document-sets/<int:pk>/", views.document_set_detail, name="document_set_detail"),
    path(
        "document-sets/<int:pk>/versions/new/",
        views.document_set_version_create,
        name="document_set_version_create",
    ),
    path(
        "document-set-versions/<int:version_pk>/add-member/",
        views.document_set_add_member,
        name="document_set_add_member",
    ),
    path(
        "document-set-versions/<int:version_pk>/publish/",
        views.document_set_version_publish,
        name="document_set_version_publish",
    ),
    path("agent-runs/", views.agent_runs, name="agent_runs"),
    path("agent-runs/<str:public_id>/", views.agent_run_detail, name="agent_run_detail"),
    path(
        "agent-runs/<str:public_id>/cancel/",
        views.agent_run_cancel,
        name="agent_run_cancel",
    ),
    path("tool-approvals/", views.tool_approvals, name="tool_approvals"),
    path(
        "tool-approvals/<int:approval_id>/decide/",
        views.tool_approval_decide,
        name="tool_approval_decide",
    ),
    path(
        "tool-invocations/<int:invocation_id>/cancel/",
        views.tool_invocation_cancel,
        name="tool_invocation_cancel",
    ),
]
