from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet
from apps.identity.assignment_services import (
    AssignmentError,
    grant_scenario_responsibility,
)
from apps.identity.authorization import Capability, authorize
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    PlatformResponsibility,
    PlatformResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


def _user(name: str):
    return get_user_model().objects.create_user(username=name)


def _scope(slug: str):
    organization = Organization.objects.create(slug=slug, name=slug)
    project = AIProject.objects.create(
        organization=organization,
        slug="project",
        name="Project",
    )
    scenario = Scenario.objects.create(
        organization=organization,
        project=project,
        slug="scenario",
        name="Scenario",
    )
    sibling = Scenario.objects.create(
        organization=organization,
        project=project,
        slug="sibling",
        name="Sibling",
    )
    document_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="knowledge",
        name="Knowledge",
    )
    return organization, project, scenario, sibling, document_set


def _member(organization: Organization, name: str):
    user = _user(name)
    membership = OrganizationMembership.objects.create(
        organization=organization,
        user=user,
    )
    return user, membership


def test_membership_is_only_an_organization_shell() -> None:
    organization, project, scenario, _sibling, document_set = _scope("shell")
    user, _membership = _member(organization, "shell-user")

    assert authorize(
        user=user,
        capability=Capability.ORGANIZATION_VIEW,
        organization=organization,
    ).allowed
    assert not authorize(
        user=user,
        capability=Capability.SCENARIO_VIEW,
        organization=organization,
        project=project,
        scenario=scenario,
    ).allowed
    assert not authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_CONTENT_READ,
        organization=organization,
        document_set=document_set,
    ).allowed


def test_organization_admin_can_delegate_but_cannot_edit_approve_or_read_content() -> None:
    organization, project, scenario, _sibling, document_set = _scope("org-admin")
    user, membership = _member(organization, "org-admin-user")
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )

    assert authorize(
        user=user,
        capability=Capability.RESPONSIBILITY_MANAGE,
        organization=organization,
    ).allowed
    for capability, target in (
        (Capability.SCENARIO_EDIT, {"project": project, "scenario": scenario}),
        (
            Capability.SCENARIO_APPROVAL_DECIDE,
            {"project": project, "scenario": scenario},
        ),
        (Capability.DOCUMENT_SET_CONTENT_READ, {"document_set": document_set}),
    ):
        assert not authorize(
            user=user,
            capability=capability,
            organization=organization,
            **target,
        ).allowed


def test_global_administrator_does_not_implicitly_approve_or_read_content() -> None:
    organization, project, scenario, _sibling, document_set = _scope("global-admin")
    user = _user("global-admin-user")
    PlatformResponsibilityAssignment.objects.create(
        user=user,
        responsibility=PlatformResponsibility.GLOBAL_ADMINISTRATOR,
        assigned_by=user,
    )

    assert authorize(user=user, capability=Capability.PLATFORM_MANAGE).allowed
    assert not authorize(
        user=user,
        capability=Capability.SCENARIO_APPROVAL_DECIDE,
        organization=organization,
        project=project,
        scenario=scenario,
    ).allowed
    assert not authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_CONTENT_READ,
        organization=organization,
        document_set=document_set,
    ).allowed


def test_project_admin_creates_and_delegates_edit_but_cannot_self_grant_approval() -> None:
    organization, project, scenario, _sibling, _document_set = _scope("project-admin")
    organization_admin, admin_membership = _member(organization, "granting-admin")
    project_admin, project_membership = _member(organization, "project-admin-user")
    editor, editor_membership = _member(organization, "delegated-editor")
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=admin_membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=organization_admin,
    )
    ProjectResponsibilityAssignment.objects.create(
        organization=organization,
        project=project,
        membership=project_membership,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=organization_admin,
    )

    assert authorize(
        user=project_admin,
        capability=Capability.SCENARIO_CREATE,
        organization=organization,
        project=project,
    ).allowed
    assert not authorize(
        user=project_admin,
        capability=Capability.SCENARIO_EDIT,
        organization=organization,
        project=project,
        scenario=scenario,
    ).allowed
    grant_scenario_responsibility(
        scenario=scenario,
        membership=editor_membership,
        responsibility=ScenarioResponsibility.EDITOR,
        actor=project_admin,
    )
    with pytest.raises(AssignmentError):
        grant_scenario_responsibility(
            scenario=scenario,
            membership=project_membership,
            responsibility=ScenarioResponsibility.APPROVER,
            actor=project_admin,
        )
    assert authorize(
        user=editor,
        capability=Capability.SCENARIO_EDIT,
        organization=organization,
        project=project,
        scenario=scenario,
    ).allowed


def test_scenario_and_document_set_responsibilities_are_exact_and_expire() -> None:
    organization, project, scenario, sibling, document_set = _scope("exact")
    user, membership = _member(organization, "exact-user")
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        scenario=scenario,
        membership=membership,
        responsibility=ScenarioResponsibility.APPROVER,
        assigned_by=user,
    )
    DocumentSetResponsibilityAssignment.objects.create(
        organization=organization,
        document_set=document_set,
        membership=membership,
        responsibility=DocumentSetResponsibility.CONTENT_READER,
        assigned_by=user,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert authorize(
        user=user,
        capability=Capability.SCENARIO_APPROVAL_DECIDE,
        organization=organization,
        project=project,
        scenario=scenario,
    ).allowed
    assert not authorize(
        user=user,
        capability=Capability.SCENARIO_APPROVAL_DECIDE,
        organization=organization,
        project=project,
        scenario=sibling,
    ).allowed
    assert not authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_CONTENT_READ,
        organization=organization,
        document_set=document_set,
    ).allowed
