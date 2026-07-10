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
    path("projects/", views.projects, name="projects"),
    path("scenarios/", views.scenarios, name="scenarios"),
    path("consumers/", views.consumers, name="consumers"),
    path("artifacts/", views.artifacts, name="artifacts"),
    path("releases/", views.releases, name="releases"),
]
