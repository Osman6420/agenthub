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
]
