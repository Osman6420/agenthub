"""Operator console views (server-rendered, tenant-scoped, login required).

Authentication is handled by Django's auth backends — LDAP in production (ADR-0001)
or the local model backend when LDAP is disabled. Authorization scope for every
screen comes from :mod:`apps.console.scoping`.
"""

from __future__ import annotations

from collections.abc import Callable

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.audit.services import record_event
from apps.catalog.models import ScenarioAlias
from apps.console import scoping
from apps.console.forms import (
    BindingForm,
    ConsumerForm,
    OrganizationForm,
    ProjectForm,
    ScenarioForm,
)
from apps.tenancy.services import (
    admin_organization_ids,
    author_organization_ids,
    can_admin_org,
    can_author_scenarios,
    can_create_organization,
    is_platform_admin,
)


def _audit_create(
    request: HttpRequest, resource_type: str, resource_id: str, org_id: int | None
) -> None:
    record_event(
        actor_type="user",
        actor_id=request.user.get_username(),
        action=f"console.{resource_type}.create",
        outcome="success",
        organization_id=org_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    user = request.user
    context = {
        "is_platform_admin": is_platform_admin(user),
        "counts": {
            "organizations": scoping.scoped_organizations(user).count(),
            "projects": scoping.scoped_projects(user).count(),
            "scenarios": scoping.scoped_scenarios(user).count(),
            "consumers": scoping.scoped_consumers(user).count(),
            "artifacts": scoping.scoped_artifacts(user).count(),
            "releases": scoping.scoped_releases(user).count(),
        },
    }
    return render(request, "console/dashboard.html", context)


@login_required
def organizations(request: HttpRequest) -> HttpResponse:
    rows = [
        {"cols": [o.slug, o.name, o.status]} for o in scoping.scoped_organizations(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Organizations",
            "headers": ["Slug", "Name", "Status"],
            "rows": rows,
            "create_links": (
                [{"url": "console:organization_create", "label": "New organization"}]
                if can_create_organization(request.user)
                else []
            ),
        },
    )


@login_required
def projects(request: HttpRequest) -> HttpResponse:
    rows = [
        {"cols": [p.organization.slug, p.slug, p.name, p.risk_level, p.status]}
        for p in scoping.scoped_projects(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "AI Projects",
            "headers": ["Organization", "Slug", "Name", "Risk", "Status"],
            "rows": rows,
            "create_links": (
                [{"url": "console:project_create", "label": "New project"}]
                if admin_organization_ids(request.user) != set()
                else []
            ),
        },
    )


@login_required
def scenarios(request: HttpRequest) -> HttpResponse:
    rows = [
        {
            "cols": [
                s.project.organization.slug,
                s.project.slug,
                s.slug,
                s.type,
                s.status,
            ]
        }
        for s in scoping.scoped_scenarios(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Scenarios",
            "headers": ["Organization", "Project", "Slug", "Type", "Status"],
            "rows": rows,
            "create_links": (
                [{"url": "console:scenario_create", "label": "New scenario"}]
                if author_organization_ids(request.user) != set()
                else []
            ),
        },
    )


@login_required
def consumers(request: HttpRequest) -> HttpResponse:
    rows = [
        {"cols": [c.organization.slug, c.name, c.subject, c.protocol, c.status]}
        for c in scoping.scoped_consumers(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Consumers",
            "headers": ["Organization", "Name", "Subject", "Protocol", "Status"],
            "rows": rows,
            "create_links": (
                [
                    {"url": "console:consumer_create", "label": "New consumer"},
                    {"url": "console:binding_create", "label": "New binding"},
                ]
                if admin_organization_ids(request.user) != set()
                else []
            ),
        },
    )


@login_required
def artifacts(request: HttpRequest) -> HttpResponse:
    rows = [
        {"cols": [a.organization.slug, a.type, a.logical_id, f"v{a.version}", a.checksum[:12]]}
        for a in scoping.scoped_artifacts(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Artifacts",
            "headers": ["Organization", "Type", "Logical ID", "Version", "Checksum"],
            "rows": rows,
        },
    )


@login_required
def releases(request: HttpRequest) -> HttpResponse:
    rows = [
        {
            "cols": [
                r.scenario.project.organization.slug,
                r.scenario.slug,
                r.status,
                r.runtime_version,
                r.artifact_manifest_sha256[:12],
            ]
        }
        for r in scoping.scoped_releases(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Releases",
            "headers": ["Organization", "Scenario", "Status", "Runtime", "Manifest SHA"],
            "rows": rows,
        },
    )


def _create(
    request: HttpRequest,
    *,
    form_class: type,
    title: str,
    resource_type: str,
    permission: Callable[[int | None], bool],
    success_url: str,
) -> HttpResponse:
    form = form_class(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        instance = form.save(commit=False)
        organization_id = getattr(instance, "organization_id", None)
        if resource_type == "project":
            organization_id = instance.organization_id
        elif resource_type == "scenario":
            organization_id = instance.project.organization_id
        elif resource_type == "binding":
            organization_id = instance.consumer.organization_id
        if not permission(organization_id):
            raise PermissionDenied
        with transaction.atomic():
            instance = form.save()
            if resource_type == "organization":
                organization_id = instance.pk
            if organization_id is None:
                raise PermissionDenied
            if resource_type == "scenario" and form.cleaned_data["alias"]:
                ScenarioAlias.objects.create(
                    organization_id=organization_id,
                    scenario=instance,
                    alias=form.cleaned_data["alias"],
                )
            _audit_create(request, resource_type, str(instance.pk), organization_id)
        return redirect(success_url)
    return render(request, "console/form.html", {"title": title, "form": form})


@login_required
def organization_create(request: HttpRequest) -> HttpResponse:
    if not can_create_organization(request.user):
        raise PermissionDenied
    return _create(
        request,
        form_class=OrganizationForm,
        title="New organization",
        resource_type="organization",
        permission=lambda _org_id: True,
        success_url="console:organizations",
    )


@login_required
def project_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=ProjectForm,
        title="New project",
        resource_type="project",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:projects",
    )


@login_required
def scenario_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=ScenarioForm,
        title="New scenario",
        resource_type="scenario",
        permission=lambda org_id: org_id is not None and can_author_scenarios(request.user, org_id),
        success_url="console:scenarios",
    )


@login_required
def consumer_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=ConsumerForm,
        title="New consumer",
        resource_type="consumer",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:consumers",
    )


@login_required
def binding_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=BindingForm,
        title="New consumer binding",
        resource_type="binding",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:consumers",
    )
