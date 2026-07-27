from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents.services import create_document_set
from apps.identity.models import (
    DocumentSetManagerAssignment,
    ProjectAdministratorAssignment,
    ScenarioEditorAssignment,
)
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db
User = get_user_model()


def _member(organization: Organization, username: str, role: str):
    user = User.objects.create_user(username=username, password=None)
    OrganizationMembership.objects.create(
        organization=organization,
        user=user,
        role=role,
    )
    return user


def test_access_page_assigns_and_removes_exact_delegated_responsibilities(
    client: Client,
) -> None:
    organization = Organization.objects.create(slug="access", name="Access")
    foreign = Organization.objects.create(slug="foreign-access", name="Foreign")
    admin = _member(organization, "admin", Role.ORGANIZATION_ADMIN)
    target = _member(organization, "target", Role.AUDITOR)
    project = AIProject.objects.create(organization=organization, slug="project", name="Project")
    scenario = Scenario.objects.create(project=project, slug="scenario", name="Scenario")
    document_set = create_document_set(
        organization=organization,
        logical_id="knowledge",
        name="Knowledge",
        actor="seed",
    )
    foreign_project = AIProject.objects.create(
        organization=foreign,
        slug="foreign",
        name="Foreign Project",
    )
    client.force_login(admin)

    page = client.get(reverse("console:organization_members"))
    body = page.content.decode()
    assert page.status_code == 200
    assert 'value="release_manager"' not in body
    assert 'value="document_manager"' not in body
    assert "Sorumluluk ata" in body

    project_response = client.post(
        reverse("console:delegated_assignment_add"),
        {
            "responsibility": "project_administrator",
            "member": OrganizationMembership.objects.get(organization=organization, user=target).pk,
            "project": project.pk,
        },
    )
    project_assignment = ProjectAdministratorAssignment.objects.get(
        organization=organization,
        user=target,
        project=project,
    )
    assert project_response.status_code == 302

    scenario_response = client.post(
        reverse("console:delegated_assignment_add"),
        {
            "responsibility": "scenario_editor",
            "member": OrganizationMembership.objects.get(organization=organization, user=target).pk,
            "scenario": scenario.pk,
        },
    )
    document_set_response = client.post(
        reverse("console:delegated_assignment_add"),
        {
            "responsibility": "document_set_manager",
            "member": OrganizationMembership.objects.get(organization=organization, user=target).pk,
            "document_set": document_set.pk,
        },
    )
    assert scenario_response.status_code == 302
    assert document_set_response.status_code == 302
    assert ScenarioEditorAssignment.objects.filter(
        organization=organization, user=target, scenario=scenario
    ).exists()
    assert DocumentSetManagerAssignment.objects.filter(
        organization=organization, user=target, document_set=document_set
    ).exists()

    forged = client.post(
        reverse("console:delegated_assignment_add"),
        {
            "responsibility": "project_administrator",
            "member": OrganizationMembership.objects.get(organization=organization, user=target).pk,
            "project": foreign_project.pk,
        },
    )
    assert forged.status_code == 302
    assert not ProjectAdministratorAssignment.objects.filter(project=foreign_project).exists()

    refreshed_response = client.get(reverse("console:organization_members"))
    refreshed = refreshed_response.content.decode()
    target_row = next(
        membership
        for membership in refreshed_response.context["memberships"]
        if membership.user_id == target.pk
    )
    assert target_row.delegated_counts == {
        "projects": 1,
        "scenarios": 1,
        "document_sets": 1,
    }
    assert "Knowledge" in refreshed
    assert "ham içerik yetkisi vermez" in refreshed

    removed = client.post(
        reverse(
            "console:delegated_assignment_remove",
            args=["project_administrator", project_assignment.pk],
        )
    )
    assert removed.status_code == 302
    assert not ProjectAdministratorAssignment.objects.filter(pk=project_assignment.pk).exists()
    assert AuditEvent.objects.filter(
        action="delegated_assignment.project_administrator.delete",
        outcome="success",
    ).exists()


def test_access_assignment_remove_is_tenant_scoped(client: Client) -> None:
    organization = Organization.objects.create(slug="own-access", name="Own")
    foreign = Organization.objects.create(slug="other-access", name="Other")
    admin = _member(organization, "admin", Role.ORGANIZATION_ADMIN)
    foreign_admin = _member(foreign, "foreign-admin", Role.ORGANIZATION_ADMIN)
    foreign_target = _member(foreign, "foreign-target", Role.AUDITOR)
    foreign_project = AIProject.objects.create(
        organization=foreign,
        slug="foreign-project",
        name="Foreign Project",
    )
    assignment = ProjectAdministratorAssignment.objects.create(
        organization=foreign,
        project=foreign_project,
        user=foreign_target,
        assigned_by=foreign_admin,
    )
    client.force_login(admin)

    response = client.post(
        reverse(
            "console:delegated_assignment_remove",
            args=["project_administrator", assignment.pk],
        )
    )

    assert response.status_code == 404
    assert ProjectAdministratorAssignment.objects.filter(pk=assignment.pk).exists()


def test_object_details_show_exact_assignments_without_foreign_members(client: Client) -> None:
    organization = Organization.objects.create(slug="detail-access", name="Detail")
    foreign = Organization.objects.create(slug="detail-foreign", name="Foreign")
    admin = _member(organization, "detail-admin", Role.ORGANIZATION_ADMIN)
    target = _member(organization, "detail-target", Role.AUDITOR)
    _member(foreign, "foreign-target-detail", Role.AUDITOR)
    project = AIProject.objects.create(organization=organization, slug="project", name="Project")
    scenario = Scenario.objects.create(project=project, slug="scenario", name="Scenario")
    document_set = create_document_set(
        organization=organization,
        logical_id="detail-set",
        name="Detail Set",
        actor="seed",
    )
    ProjectAdministratorAssignment.objects.create(
        organization=organization, project=project, user=target, assigned_by=admin
    )
    ScenarioEditorAssignment.objects.create(
        organization=organization, scenario=scenario, user=target, assigned_by=admin
    )
    DocumentSetManagerAssignment.objects.create(
        organization=organization, document_set=document_set, user=target, assigned_by=admin
    )
    client.force_login(admin)

    for url in (
        reverse("console:project_detail_public", args=[project.public_id]),
        reverse("console:scenario_detail_public", args=[scenario.public_id]),
        reverse("console:document_set_detail_public", args=[document_set.public_id]),
    ):
        response = client.get(url)
        body = response.content.decode()
        assert response.status_code == 200
        assert "detail-target" in body
        assert "foreign-target-detail" not in body
        assert 'href="#access"' in body


def test_superadmin_console_use_is_audited_before_view(client: Client) -> None:
    superadmin = User.objects.create_superuser(username="recovery-admin", password=None)
    client.force_login(superadmin)

    response = client.get(reverse("console:dashboard"))

    assert response.status_code == 200
    assert AuditEvent.objects.filter(
        action="superadmin.login", actor_id=str(superadmin.pk), outcome="success"
    ).exists()
    event = AuditEvent.objects.filter(action="superadmin.console_access").latest("occurred_at")
    assert event.actor_id == str(superadmin.pk)
    assert event.resource_type == "route"
    assert event.resource_id == "console:dashboard"
    assert event.reason == "read"


def test_superadmin_console_request_fails_closed_when_audit_write_fails(client: Client) -> None:
    superadmin = User.objects.create_superuser(username="recovery-audit-failure", password=None)
    client.force_login(superadmin)

    with patch(
        "apps.identity.superadmin_middleware.record_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            client.get(reverse("console:dashboard"))
