"""Operator console views (server-rendered, tenant-scoped, login required).

Authentication is handled by Django's auth backends — LDAP in production (ADR-0001)
or the local model backend when LDAP is disabled. Authorization scope for every
screen comes from :mod:`apps.console.scoping`.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.console import scoping
from apps.tenancy.services import is_platform_admin


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
        {"title": "Organizations", "headers": ["Slug", "Name", "Status"], "rows": rows},
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
        },
    )
