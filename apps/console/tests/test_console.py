"""Console access control: login required, tenant-scoped, no Django Admin."""

from __future__ import annotations

from threading import Barrier, Thread

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario, ScenarioAlias
from apps.console.tests.access_fixtures import private_access_member
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
)
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
    membership = OrganizationMembership.objects.create(organization=org_a, user=member)
    ProjectResponsibilityAssignment.objects.create(
        organization=org_a,
        membership=membership,
        project=AIProject.objects.get(organization=org_a, slug="alpha"),
        responsibility=ProjectResponsibility.VIEWER,
        assigned_by=member,
    )
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
    membership = OrganizationMembership.objects.create(organization=org_a, user=user)
    OrganizationResponsibilityAssignment.objects.create(
        organization=org_a,
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=user,
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
def test_project_create_does_not_couple_membership_to_an_owner_role(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    admin = User.objects.create_user("admin", password="x")  # noqa: S106
    owner_a = User.objects.create_user("owner-a", password="x")  # noqa: S106
    outsider = User.objects.create_user("outsider", password="x")  # noqa: S106
    admin_membership = OrganizationMembership.objects.create(organization=org_a, user=admin)
    OrganizationResponsibilityAssignment.objects.create(
        organization=org_a,
        membership=admin_membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=admin,
    )
    owner_membership = OrganizationMembership.objects.create(organization=org_a, user=owner_a)
    OrganizationMembership.objects.create(organization=org_b, user=outsider)
    client.force_login(admin)

    response = client.get(reverse("console:project_create"))
    body = response.content.decode()

    assert response.status_code == 200
    assert 'name="owner_membership"' not in body
    assert "owner-a" not in body
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
    assert project.owner == ""


@pytest.mark.django_db
def test_project_create_ignores_forged_legacy_owner_membership(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    admin = User.objects.create_user("admin", password="x")  # noqa: S106
    owner_b = User.objects.create_user("owner-b", password="x")  # noqa: S106
    for organization in (org_a, org_b):
        membership = OrganizationMembership.objects.create(organization=organization, user=admin)
        OrganizationResponsibilityAssignment.objects.create(
            organization=organization,
            membership=membership,
            responsibility=OrganizationResponsibility.ADMINISTRATOR,
            assigned_by=admin,
        )
    owner_membership = OrganizationMembership.objects.create(organization=org_b, user=owner_b)
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

    assert response.status_code == 302
    project = AIProject.objects.get(organization=org_a)
    assert project.slug.startswith("forbidden-owner-")
    assert project.owner == ""


@pytest.mark.django_db
def test_scenario_author_create_is_atomic_and_audited(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    project = AIProject.objects.create(organization=org, slug="alpha", name="Alpha")
    user = User.objects.create_user("editor", password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    ProjectResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        project=project,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    client.force_login(user)

    response = client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {
            "access_mode": "private",
            "initial_manager": private_access_member(org),
            "project": project.pk,
            "slug": "faq",
            "name": "FAQ",
            "preset": "empty_workflow",
            "logical_description": "Customer FAQ workflow",
        },
    )

    assert response.status_code == 302
    scenario = Scenario.objects.get(project=project)
    assert scenario.slug.startswith("faq-")
    assert scenario.workflow_drafts.get().logical_description == "Customer FAQ workflow"
    assert ScenarioAlias.objects.filter(scenario=scenario, alias__startswith="alpha-faq-").exists()
    assert AuditEvent.objects.filter(
        action="console.scenario.create",
        organization_id=org.pk,
        resource_id=str(scenario.pk),
    ).exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="concurrent writers need PostgreSQL")
@pytest.mark.django_db(transaction=True)
def test_scenario_create_rejects_a_truly_concurrent_duplicate_submit() -> None:
    """BUG-002: two simultaneous submits of the same project+user+name (the report's own
    `Promise.all` repro) must create only one Scenario, not one per request. SQLite serializes
    writers and raises spurious "database is locked" errors under real thread contention even
    when the application-level race is handled correctly, so this is PostgreSQL-only -- the
    same constraint the existing `test_concurrent_promotions_serialize_to_one_coherent_served_pair`
    (apps/ingestion/tests/test_promotion.py) already lives under."""
    org = Organization.objects.create(slug="org-race", name="Race")
    project = AIProject.objects.create(organization=org, slug="race", name="Race")
    user = User.objects.create_user("editor-race", password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    ProjectResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        project=project,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    url = reverse("console:project_scenario_create", args=[project.public_id])
    payload = {
        "access_mode": "private",
        "initial_manager": private_access_member(org),
        "project": project.pk,
        "slug": "dup",
        "name": "Dup",
        "preset": "empty_workflow",
        "logical_description": "Duplicate submit guard",
    }
    # Log in both clients sequentially first -- SQLite serializes writers, so racing
    # `force_login`'s own session-table write (not the behavior under test) would flake here.
    clients = [Client(), Client()]
    for local_client in clients:
        local_client.force_login(user)
    barrier = Barrier(2)
    results: list[int] = []
    errors: list[BaseException] = []

    def attempt(local_client: Client) -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            results.append(local_client.post(url, payload).status_code)
        except BaseException as exc:  # pragma: no cover - asserted by parent thread
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=attempt, args=(local_client,)) for local_client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert sorted(results) == [200, 302]
    assert Scenario.objects.filter(project=project, name="Dup").count() == 1
