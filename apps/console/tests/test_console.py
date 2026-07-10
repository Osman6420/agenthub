"""Console access control: login required, tenant-scoped, no Django Admin."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import AIProject
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


@pytest.mark.django_db
def test_dashboard_requires_authentication(client: Client) -> None:
    response = client.get(reverse("console:dashboard"))
    assert response.status_code == 302
    assert "/console/login/" in response["Location"]


@pytest.mark.django_db
def test_django_admin_route_follows_setting(client: Client) -> None:
    # ADR-0001: Django Admin is not routed unless explicitly enabled (dev only).
    from django.conf import settings

    response = client.get("/admin/")
    if getattr(settings, "ENABLE_DJANGO_ADMIN", False):
        assert response.status_code in (200, 302)  # dev opt-in: routed to admin login
    else:
        assert response.status_code == 404  # production default: not routed


@pytest.mark.django_db
def test_local_account_can_sign_in(client: Client) -> None:
    User.objects.create_user("operator", password="pw-local")  # noqa: S106
    response = client.post(
        reverse("console:login"),
        {"username": "operator", "password": "pw-local"},
    )
    assert response.status_code == 302  # authenticated -> redirect to dashboard


@pytest.mark.django_db
def test_projects_list_is_tenant_scoped(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    AIProject.objects.create(organization=org_a, slug="alpha", name="Alpha")
    AIProject.objects.create(organization=org_b, slug="beta", name="Beta")

    member = User.objects.create_user("alice", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org_a, user=member, role=Role.PROJECT_OWNER)
    client.force_login(member)

    body = client.get(reverse("console:projects")).content.decode()
    assert "alpha" in body
    assert "beta" not in body  # org B is outside the member's scope


@pytest.mark.django_db
def test_platform_admin_sees_all_projects(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    AIProject.objects.create(organization=org_a, slug="alpha", name="Alpha")
    AIProject.objects.create(organization=org_b, slug="beta", name="Beta")

    root = User.objects.create_superuser("root", "root@example.com", "x")  # noqa: S106
    client.force_login(root)

    body = client.get(reverse("console:projects")).content.decode()
    assert "alpha" in body
    assert "beta" in body
