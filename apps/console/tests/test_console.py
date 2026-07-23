"""Console access control: login required, tenant-scoped, no Django Admin."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario, ScenarioAlias
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
def test_platform_admin_sees_projects_in_one_selected_workspace(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    AIProject.objects.create(organization=org_a, slug="alpha", name="Alpha")
    AIProject.objects.create(organization=org_b, slug="beta", name="Beta")

    root = User.objects.create_superuser("root", "root@example.com", "x")  # noqa: S106
    client.force_login(root)

    body = client.get(reverse("console:projects")).content.decode()
    assert "alpha" in body
    assert "beta" not in body
    client.post(reverse("console:switch_organization"), {"organization_id": org_b.pk})
    switched = client.get(reverse("console:projects")).content.decode()
    assert "alpha" not in switched
    assert "beta" in switched


@pytest.mark.django_db
def test_non_admin_cannot_create_organization(client: Client) -> None:
    user = User.objects.create_user("member", password="x")  # noqa: S106
    client.force_login(user)

    response = client.post(
        reverse("console:organization_create"),
        {"slug": "forbidden", "name": "Forbidden", "status": "active"},
    )

    assert response.status_code == 403
    assert not Organization.objects.filter(slug="forbidden").exists()


@pytest.mark.django_db
def test_platform_admin_can_open_organization_create_form(client: Client) -> None:
    root = User.objects.create_superuser("root", "root@example.com", "x")  # noqa: S106
    client.force_login(root)

    response = client.get(reverse("console:organization_create"))

    assert response.status_code == 200
    assert 'name="slug"' not in response.content.decode()


@pytest.mark.django_db
def test_org_admin_cannot_create_project_in_another_org(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    user = User.objects.create_user("admin-a", password="x")  # noqa: S106
    OrganizationMembership.objects.create(
        organization=org_a, user=user, role=Role.ORGANIZATION_ADMIN
    )
    owner_membership = OrganizationMembership.objects.get(organization=org_a, user=user)
    client.force_login(user)

    response = client.post(
        reverse("console:project_create"),
        {
            "organization": org_b.pk,
            "slug": "forbidden",
            "name": "Forbidden",
            "owner_membership": owner_membership.pk,
            "risk_level": "medium",
            "status": "active",
        },
    )

    assert response.status_code == 302
    project = AIProject.objects.get(name="Forbidden")
    assert project.organization == org_a
    assert not AIProject.objects.filter(organization=org_b, name="Forbidden").exists()


@pytest.mark.django_db
def test_project_owner_is_selected_from_members_in_admin_scope(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    admin = User.objects.create_user("admin", password="x")  # noqa: S106
    owner_a = User.objects.create_user("owner-a", password="x")  # noqa: S106
    outsider = User.objects.create_user("outsider", password="x")  # noqa: S106
    OrganizationMembership.objects.create(
        organization=org_a, user=admin, role=Role.ORGANIZATION_ADMIN
    )
    owner_membership = OrganizationMembership.objects.create(
        organization=org_a, user=owner_a, role=Role.PROJECT_OWNER
    )
    OrganizationMembership.objects.create(
        organization=org_b, user=outsider, role=Role.PROJECT_OWNER
    )
    client.force_login(admin)

    response = client.get(reverse("console:project_create"))
    body = response.content.decode()

    assert response.status_code == 200
    assert 'name="owner_membership"' in body
    assert "owner-a" in body
    assert "outsider" not in body

    response = client.post(
        reverse("console:project_create"),
        {
            "organization": org_a.pk,
            "slug": "alpha",
            "name": "Alpha",
            "owner_membership": owner_membership.pk,
            "risk_level": "medium",
            "status": "active",
        },
    )
    assert response.status_code == 302
    project = AIProject.objects.get(organization=org_a)
    assert project.slug.startswith("alpha-")
    assert project.owner == "owner-a"
    assert project.owner_membership == owner_membership


@pytest.mark.django_db
def test_project_owner_must_belong_to_selected_organization(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    admin = User.objects.create_user("admin", password="x")  # noqa: S106
    owner_b = User.objects.create_user("owner-b", password="x")  # noqa: S106
    for organization in (org_a, org_b):
        OrganizationMembership.objects.create(
            organization=organization, user=admin, role=Role.ORGANIZATION_ADMIN
        )
    owner_membership = OrganizationMembership.objects.create(
        organization=org_b, user=owner_b, role=Role.PROJECT_OWNER
    )
    client.force_login(admin)

    response = client.post(
        reverse("console:project_create"),
        {
            "organization": org_a.pk,
            "slug": "forbidden-owner",
            "name": "Forbidden owner",
            "owner_membership": owner_membership.pk,
            "risk_level": "medium",
            "status": "active",
        },
    )

    assert response.status_code == 200
    assert "Select a valid choice" in response.content.decode()
    assert not AIProject.objects.filter(slug="forbidden-owner").exists()


@pytest.mark.django_db
def test_scenario_author_create_is_atomic_and_audited(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    project = AIProject.objects.create(organization=org, slug="alpha", name="Alpha")
    user = User.objects.create_user("editor", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=Role.SCENARIO_EDITOR)
    client.force_login(user)

    response = client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {
            "project": project.pk,
            "slug": "faq",
            "name": "FAQ",
            "type": "rag",
            "visibility": "internal",
            "risk_level": "medium",
            "status": "draft",
            "alias": "customer-faq",
        },
    )

    assert response.status_code == 302
    scenario = Scenario.objects.get(project=project)
    assert scenario.slug.startswith("faq-")
    assert ScenarioAlias.objects.filter(scenario=scenario, alias__startswith="alpha-faq-").exists()
    assert AuditEvent.objects.filter(
        action="console.scenario.create",
        organization_id=org.pk,
        resource_id=str(scenario.pk),
    ).exists()
