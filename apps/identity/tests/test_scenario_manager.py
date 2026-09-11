"""The explicitly assigned manager combines operations without broadening old roles."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.console.context import can_view_runs_surface
from apps.console.forms import DelegatedAssignmentForm
from apps.console.scoping import scoped_scenarios
from apps.identity.assignment_services import AssignmentError, grant_scenario_responsibility
from apps.identity.authorization import Capability, authorize
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.tests.test_responsibility_authorization import _member, _scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager_scope():
    org, project, scenario, sibling, document_set = _scope("manager")
    admin, admin_member = _member(org, "manager-admin")
    manager, membership = _member(org, "manager-user")
    OrganizationResponsibilityAssignment.objects.create(
        organization=org,
        membership=admin_member,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=admin,
    )
    assignment = grant_scenario_responsibility(
        scenario=scenario,
        membership=membership,
        responsibility=ScenarioResponsibility.MANAGER,
        actor=admin,
        request_id="manager-test",
    )
    return org, project, scenario, sibling, document_set, manager, membership, assignment


@pytest.mark.parametrize(
    "capability",
    [
        Capability.SCENARIO_VIEW,
        Capability.SCENARIO_EDIT,
        Capability.SCENARIO_TEST,
        Capability.SCENARIO_RELEASE,
        Capability.RUNTIME_VIEW,
        Capability.RUNTIME_CANCEL,
        Capability.RUNTIME_PAUSE,
        Capability.RUNTIME_RESUME,
    ],
)
def test_manager_combines_exact_scenario_actions_and_expiry(manager_scope, capability):
    org, project, scenario, sibling, _, manager, _, assignment = manager_scope
    assert authorize(user=manager, capability=capability, scenario=scenario).allowed
    assert not authorize(user=manager, capability=capability, scenario=sibling).allowed
    assert not authorize(user=manager, capability=capability, project=project).allowed
    assert not authorize(user=manager, capability=capability, organization=org).allowed
    assignment.expires_at = timezone.now() - timedelta(seconds=1)
    assignment.save()
    assert not authorize(user=manager, capability=capability, scenario=scenario).allowed


def test_manager_does_not_gain_content_approval_or_administration(manager_scope):
    org, project, scenario, _, document_set, manager, membership, _ = manager_scope
    for capability in (
        Capability.DOCUMENT_SET_CONTENT_READ,
        Capability.DOCUMENT_SET_CONTENT_MANAGE,
        Capability.DOCUMENT_SET_RETRIEVE_GRANT,
        Capability.SCENARIO_APPROVAL_DECIDE,
        Capability.SCENARIO_APPROVAL_VIEW,
        Capability.PROJECT_MANAGE,
        Capability.RESPONSIBILITY_MANAGE,
        Capability.ORGANIZATION_MANAGE,
        Capability.PLATFORM_MANAGE,
    ):
        assert not authorize(
            user=manager,
            capability=capability,
            organization=org,
            project=project,
            scenario=scenario,
            document_set=document_set,
        ).allowed
    with pytest.raises(AssignmentError):
        grant_scenario_responsibility(
            scenario=scenario,
            membership=membership,
            responsibility=ScenarioResponsibility.APPROVER,
            actor=manager,
        )
    assert AuditEvent.objects.filter(
        action="responsibility.scenario.create", outcome="success", request_id="manager-test"
    ).exists()
    assert AuditEvent.objects.filter(
        action="responsibility.scenario.create", outcome="deny"
    ).exists()


@pytest.mark.parametrize(
    ("responsibility", "denied"),
    [
        (ScenarioResponsibility.EDITOR, Capability.SCENARIO_RELEASE),
        (ScenarioResponsibility.RELEASE_MANAGER, Capability.SCENARIO_EDIT),
        (ScenarioResponsibility.RUNTIME_OPERATOR, Capability.SCENARIO_RELEASE),
    ],
)
def test_existing_specialist_roles_stay_narrow(responsibility, denied):
    org, _, scenario, _, _ = _scope("old-role")
    user, membership = _member(org, "old-user")
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        scenario=scenario,
        membership=membership,
        responsibility=responsibility,
        assigned_by=user,
    )
    assert not authorize(user=user, capability=denied, scenario=scenario).allowed


def test_assignment_form_requires_the_exact_scenario(manager_scope):
    org, _, scenario, _, _, _, membership, _ = manager_scope
    body = {"responsibility": ScenarioResponsibility.MANAGER, "member": membership.pk}
    missing = DelegatedAssignmentForm(data=body, organization=org)
    assert not missing.is_valid()
    assert "scenario" in missing.errors
    valid = DelegatedAssignmentForm(data={**body, "scenario": scenario.pk}, organization=org)
    assert valid.is_valid(), valid.errors
    assert valid.cleaned_data["target"] == scenario


def test_manager_navigation_and_list_scopes_follow_live_assignment(manager_scope):
    org, _, scenario, _, _, manager, _, assignment = manager_scope
    assert can_view_runs_surface(manager, org)
    assert list(scoped_scenarios(manager).values_list("pk", flat=True)) == [scenario.pk]
    assignment.expires_at = timezone.now() - timedelta(seconds=1)
    assignment.save()
    assert not can_view_runs_surface(manager, org)
    assert not scoped_scenarios(manager).exists()
