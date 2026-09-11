"""Phase 2.8 Part 2 organization and access-management boundaries."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.console.context import SESSION_KEY
from apps.console.tests.access_fixtures import private_access_member
from apps.documents.models import DocumentSet
from apps.identity.assignment_services import remove_responsibility_assignment
from apps.identity.models import (
    Consumer,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
)
from apps.identity.roles import Role
from apps.tenancy.models import MembershipStatus, Organization, OrganizationMembership
from apps.tenancy.services import (
    MembershipManagementError,
    remove_organization_membership,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_workspace_defaults_deterministically_and_never_offers_cross_org_scope(
    client: Client,
) -> None:
    later = Organization.objects.create(slug="zulu", name="Zulu")
    first = Organization.objects.create(slug="alpha", name="Alpha")
    user = User.objects.create_user("operator", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=later, user=user)
    OrganizationMembership.objects.create(organization=first, user=user)
    client.force_login(user)

    response = client.get(reverse("console:dashboard"))

    assert response.context["active_organization"] == first
    assert client.session[SESSION_KEY] == first.pk
    assert "Tüm organizasyonlar" not in response.content.decode()


def test_stale_or_revoked_workspace_falls_back_without_widening_scope(client: Client) -> None:
    retained = Organization.objects.create(slug="retained", name="Retained")
    revoked = Organization.objects.create(slug="revoked", name="Revoked")
    user = User.objects.create_user("operator", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=retained, user=user)
    revoked_membership = OrganizationMembership.objects.create(organization=revoked, user=user)
    client.force_login(user)
    session = client.session
    session[SESSION_KEY] = revoked.pk
    session.save()
    revoked_membership.delete()

    response = client.get(reverse("console:dashboard"))

    assert response.context["active_organization"] == retained
    assert client.session[SESSION_KEY] == retained.pk
    assert "Revoked" not in response.content.decode()


def test_blank_workspace_switch_is_denied_and_keeps_current_selection(client: Client) -> None:
    organization = Organization.objects.create(slug="acme", name="Acme")
    user = User.objects.create_user("operator", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=organization, user=user)
    client.force_login(user)
    client.get(reverse("console:dashboard"))

    response = client.post(reverse("console:switch_organization"), {"organization_id": ""})

    assert response.status_code == 403
    assert client.session[SESSION_KEY] == organization.pk


def test_platform_admin_also_gets_one_deterministic_workspace(client: Client) -> None:
    second = Organization.objects.create(slug="second", name="Beta")
    first = Organization.objects.create(slug="first", name="Alpha")
    admin = User.objects.create_superuser(  # noqa: S106
        "root",
        password="x",  # noqa: S106
        email="root@example.test",  # noqa: S106
    )
    client.force_login(admin)

    response = client.get(reverse("console:dashboard"))

    assert response.context["active_organization"] == first
    assert client.session[SESSION_KEY] == first.pk
    assert second.name in response.content.decode()


def _member(org: Organization, username: str, role: str) -> tuple[Any, OrganizationMembership]:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    responsibilities: dict[str, str] = {
        Role.ORGANIZATION_ADMIN: OrganizationResponsibility.ADMINISTRATOR,
        Role.AUDITOR: OrganizationResponsibility.AUDITOR,
    }
    responsibility = responsibilities.get(role)
    if responsibility is not None:
        OrganizationResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            responsibility=responsibility,
            assigned_by=user,
        )
    return user, membership


def test_platform_organization_create_is_atomic_without_tenant_identity(client: Client) -> None:
    admin = User.objects.create_superuser("platform", password=None)
    client.force_login(admin)

    response = client.post(
        reverse("console:organization_create"), {"name": "New Tenant", "status": "active"}
    )

    organization = Organization.objects.get(name="New Tenant")
    assert response.status_code == 302
    assert not OrganizationMembership.objects.filter(organization=organization, user=admin).exists()
    assert AuditEvent.objects.filter(
        organization_id=organization.pk, action="console.organization.create"
    ).exists()
    assert client.session[SESSION_KEY] == organization.pk


def test_organization_create_rolls_back_when_required_audit_fails(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = User.objects.create_superuser("platform", password=None)
    client.force_login(admin)

    def fail_audit(**_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.console.views.record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        client.post(
            reverse("console:organization_create"),
            {"name": "Rollback Tenant", "status": "active"},
        )

    assert not Organization.objects.filter(name="Rollback Tenant").exists()


def test_membership_page_and_lifecycle_are_active_org_scoped(client: Client) -> None:
    org = Organization.objects.create(slug="managed", name="Managed")
    other = Organization.objects.create(slug="other", name="Other")
    admin, _admin_membership = _member(org, "admin", Role.ORGANIZATION_ADMIN)
    target = User.objects.create_user("target", password="x")  # noqa: S106
    foreign, foreign_membership = _member(other, "foreign", Role.AUDITOR)
    client.force_login(admin)

    page = client.get(reverse("console:organization_members"))
    assert page.status_code == 200
    assert "Kullanıcılar ve yetkiler" in page.content.decode()
    membership_rows = page.content.decode().split("Mevcut üyelikler", maxsplit=1)[1]
    assert foreign.get_username() not in membership_rows

    added = client.post(
        reverse("console:organization_member_add"),
        {"user": target.pk},
    )
    membership = OrganizationMembership.objects.get(organization=org, user=target)
    assert added.status_code == 302
    assert not OrganizationResponsibilityAssignment.objects.filter(membership=membership).exists()

    assert (
        client.post(
            reverse("console:organization_member_remove", args=[foreign_membership.pk])
        ).status_code
        == 404
    )
    removed = client.post(reverse("console:organization_member_remove", args=[membership.pk]))
    assert removed.status_code == 302
    membership.refresh_from_db()
    assert membership.status == MembershipStatus.REVOKED
    assert AuditEvent.objects.filter(
        organization_id=org.pk, action="organization_membership.create"
    ).exists()


def test_last_admin_responsibility_and_membership_cannot_be_removed() -> None:
    org = Organization.objects.create(slug="protected", name="Protected")
    admin, membership = _member(org, "admin", Role.ORGANIZATION_ADMIN)
    assignment = OrganizationResponsibilityAssignment.objects.get(
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
    )

    with pytest.raises(PermissionError, match="LAST_ORGANIZATION_ADMIN"):
        remove_responsibility_assignment(assignment=assignment, actor=admin)
    with pytest.raises(MembershipManagementError, match="LAST_ORGANIZATION_ADMIN"):
        remove_organization_membership(membership=membership, actor=admin)

    assignment.refresh_from_db()
    assert assignment.status == "active"


def test_responsibility_audit_failure_rolls_back_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = Organization.objects.create(slug="audit", name="Audit")
    admin, _ = _member(org, "admin", Role.ORGANIZATION_ADMIN)
    _second_admin, membership = _member(org, "second", Role.ORGANIZATION_ADMIN)
    assignment = OrganizationResponsibilityAssignment.objects.get(
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
    )

    def fail_audit(**_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.identity.assignment_services.record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        remove_responsibility_assignment(assignment=assignment, actor=admin)

    assignment.refresh_from_db()
    assert assignment.status == "active"


def test_unscoped_document_manager_cannot_create_set_or_non_document_objects(
    client: Client,
) -> None:
    org = Organization.objects.create(slug="docs", name="Docs")
    manager, _ = _member(org, "docs-manager", Role.DOCUMENT_MANAGER)
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    client.force_login(manager)

    created = client.post(reverse("console:document_set_create"), {"name": "Knowledge"})
    assert created.status_code == 403
    assert not DocumentSet.objects.filter(organization=org, name="Knowledge").exists()
    assert client.post(reverse("console:project_create"), {"name": "Denied"}).status_code == 403
    assert client.post(reverse("console:consumer_create"), {"name": "Denied"}).status_code == 403
    assert (
        client.post(
            reverse("console:project_scenario_create", args=[project.public_id]),
            {"name": "Denied"},
        ).status_code
        == 404
    )
    assert not Scenario.objects.filter(project=project, name="Denied").exists()
    assert not Consumer.objects.filter(organization=org, name="Denied").exists()


def test_contextual_creates_ignore_forged_parent_fields(client: Client) -> None:
    org = Organization.objects.create(slug="own", name="Own")
    foreign = Organization.objects.create(slug="foreign", name="Foreign")
    admin, owner_membership = _member(org, "admin", Role.ORGANIZATION_ADMIN)
    _foreign_admin, foreign_owner = _member(foreign, "foreign-admin", Role.ORGANIZATION_ADMIN)
    project = AIProject.objects.create(organization=org, slug="existing", name="Existing")
    ProjectResponsibilityAssignment.objects.create(
        organization=org,
        project=project,
        membership=owner_membership,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=admin,
    )
    foreign_project = AIProject.objects.create(
        organization=foreign, slug="foreign-project", name="Foreign Project"
    )
    client.force_login(admin)

    project_response = client.post(
        reverse("console:project_create"),
        {
            "organization": foreign.pk,
            "name": "Context Project",
            "owner_membership": owner_membership.pk,
            "risk_level": "low",
            "status": "active",
        },
    )
    assert project_response.status_code == 302
    assert AIProject.objects.get(name="Context Project").organization == org

    rejected_owner = client.post(
        reverse("console:project_create"),
        {
            "name": "Foreign Owner",
            "owner_membership": foreign_owner.pk,
            "risk_level": "low",
            "status": "active",
        },
    )
    assert rejected_owner.status_code == 302
    assert AIProject.objects.get(name="Foreign Owner").organization == org

    scenario_response = client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {
            "access_mode": "private",
            "initial_manager": private_access_member(org),
            "project": foreign_project.pk,
            "name": "Context Scenario",
            "preset": "document_answer",
            "logical_description": "Answers from governed documents",
        },
    )
    assert scenario_response.status_code == 302
    assert Scenario.objects.get(name="Context Scenario").project == project

    consumer_response = client.post(
        reverse("console:consumer_create"),
        {
            "organization": foreign.pk,
            "name": "Context Consumer",
            "protocol": "rest",
            "status": "active",
        },
    )
    assert consumer_response.status_code == 302
    assert Consumer.objects.get(name="Context Consumer").organization == org


def test_authorized_deep_link_aligns_workspace_only_after_object_authorization(
    client: Client,
) -> None:
    first = Organization.objects.create(slug="first-link", name="First")
    second = Organization.objects.create(slug="second-link", name="Second")
    foreign = Organization.objects.create(slug="foreign-link", name="Foreign")
    user, _ = _member(first, "link-user", Role.AUDITOR)
    second_membership = OrganizationMembership.objects.create(organization=second, user=user)
    second_project = AIProject.objects.create(
        organization=second, slug="second-project", name="Second Project"
    )
    ProjectResponsibilityAssignment.objects.create(
        organization=second,
        project=second_project,
        membership=second_membership,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    foreign_project = AIProject.objects.create(
        organization=foreign, slug="foreign-project", name="Foreign Project"
    )
    client.force_login(user)
    client.get(reverse("console:dashboard"))
    assert client.session[SESSION_KEY] == first.pk

    authorized = client.get(
        reverse("console:project_detail_public", args=[second_project.public_id])
    )
    assert authorized.status_code == 200
    assert client.session[SESSION_KEY] == second.pk

    denied = client.get(reverse("console:project_detail_public", args=[foreign_project.public_id]))
    assert denied.status_code == 404
    assert client.session[SESSION_KEY] == second.pk
