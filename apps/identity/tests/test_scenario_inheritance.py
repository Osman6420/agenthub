"""Explicit role inheritance without changing legacy assignments or private access."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import AIProject, Scenario, ScenarioAccessMode
from apps.console.context import can_view_runs_surface
from apps.console.scoping import scoped_scenarios
from apps.identity.authorization import Capability, authorize, authorized_scenarios
from apps.identity.models import (
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.tests.test_responsibility_authorization import _member, _scope

pytestmark = pytest.mark.django_db

VIEW = {Capability.SCENARIO_VIEW}
EDIT = VIEW | {Capability.SCENARIO_EDIT, Capability.SCENARIO_TEST}
MANAGE = EDIT | {
    Capability.SCENARIO_RELEASE,
    Capability.RUNTIME_VIEW,
    Capability.RUNTIME_CANCEL,
    Capability.RUNTIME_PAUSE,
    Capability.RUNTIME_RESUME,
    Capability.SCENARIO_ACCESS_MANAGE,
}
SCENARIO_CAPS = MANAGE | {
    Capability.SCENARIO_APPROVAL_VIEW,
    Capability.SCENARIO_APPROVAL_DECIDE,
    Capability.DOCUMENT_SET_CONTENT_READ,
    Capability.RESPONSIBILITY_MANAGE,
}


@pytest.mark.parametrize("role", ProjectResponsibility.values)
@pytest.mark.parametrize("mode", ScenarioAccessMode.values)
def test_project_role_mode_matrix_and_list_detail_parity(role, mode):
    org, project, scenario, sibling, _ = _scope("inheritance")
    user, membership = _member(org, "project-operator")
    scenario.access_mode = mode
    scenario.save(update_fields=["access_mode"])
    ProjectResponsibilityAssignment.objects.create(
        organization=org,
        project=project,
        membership=membership,
        responsibility=role,
        assigned_by=user,
    )
    expected = set()
    if mode != ScenarioAccessMode.PRIVATE:
        expected |= VIEW
        if mode == ScenarioAccessMode.INHERIT:
            if role == ProjectResponsibility.EDITOR:
                expected |= EDIT
            elif role == ProjectResponsibility.MANAGER:
                expected |= MANAGE
    if role == ProjectResponsibility.MANAGER:
        expected.add(Capability.SCENARIO_ACCESS_MANAGE)
    for capability in SCENARIO_CAPS:
        decision = authorize(user=user, capability=capability, scenario=scenario)
        assert decision.allowed == (capability in expected), (role, mode, capability)
        assert (
            authorized_scenarios(user, capability).filter(pk=scenario.pk).exists()
            == decision.allowed
        )
    assert scoped_scenarios(user).filter(pk=scenario.pk).exists() == (
        Capability.SCENARIO_VIEW in expected
    )
    assert can_view_runs_surface(user, org) == (Capability.RUNTIME_VIEW in expected)
    assert authorize(user=user, capability=Capability.SCENARIO_VIEW, scenario=sibling).allowed


@pytest.mark.parametrize("role", ScenarioResponsibility.values)
def test_direct_basic_roles_require_private_or_legacy_but_specialists_remain_independent(role):
    org, _, scenario, sibling, _ = _scope("direct")
    user, membership = _member(org, "direct-operator")
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        scenario=scenario,
        membership=membership,
        responsibility=role,
        assigned_by=user,
    )
    for mode in ScenarioAccessMode.values:
        scenario.access_mode = mode
        scenario.save(update_fields=["access_mode"])
        expected = mode != ScenarioAccessMode.INHERIT or role in {
            ScenarioResponsibility.APPROVER,
            ScenarioResponsibility.RELEASE_MANAGER,
            ScenarioResponsibility.RUNTIME_OPERATOR,
        }
        assert (
            authorize(user=user, capability=Capability.SCENARIO_VIEW, scenario=scenario).allowed
            == expected
        )
        assert scoped_scenarios(user).filter(pk=scenario.pk).exists() == expected
        assert not scoped_scenarios(user).filter(pk=sibling.pk).exists()


def test_manager_inheritance_never_crosses_project_or_tenant_and_expires_live():
    org, project, scenario, _, document_set = _scope("manager-inherit")
    user, membership = _member(org, "manager-operator")
    assignment = ProjectResponsibilityAssignment.objects.create(
        organization=org,
        project=project,
        membership=membership,
        responsibility=ProjectResponsibility.MANAGER,
        assigned_by=user,
    )
    scenario.access_mode = ScenarioAccessMode.INHERIT
    scenario.save(update_fields=["access_mode"])
    other_project = AIProject.objects.create(organization=org, slug="other", name="Other")
    same_tenant = Scenario.objects.create(
        organization=org, project=other_project, slug="other", name="Other", access_mode="inherit"
    )
    _, _, cross_tenant, _, _ = _scope("foreign")
    for target in (same_tenant, cross_tenant):
        assert not authorize(
            user=user, capability=Capability.SCENARIO_VIEW, scenario=target
        ).allowed
        assert not scoped_scenarios(user).filter(pk=target.pk).exists()
    assert not authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_CONTENT_READ,
        scenario=scenario,
        document_set=document_set,
    ).allowed
    for state in ("expired", "inactive_member", "inactive_user", "inactive_org"):
        assignment.expires_at = (
            timezone.now() - timedelta(seconds=1) if state == "expired" else None
        )
        ProjectResponsibilityAssignment.objects.filter(pk=assignment.pk).update(
            expires_at=assignment.expires_at
        )
        membership.status = "revoked" if state == "inactive_member" else "active"
        membership.revoked_by = user if state == "inactive_member" else None
        membership.revoked_at = timezone.now() if state == "inactive_member" else None
        membership.save(update_fields=["status", "revoked_by", "revoked_at"])
        user.is_active = state != "inactive_user"
        user.save(update_fields=["is_active"])
        org.status = "disabled" if state == "inactive_org" else "active"
        org.save(update_fields=["status"])
        scenario.organization = org
        assert not authorize(
            user=user, capability=Capability.SCENARIO_EDIT, scenario=scenario
        ).allowed
        assert not authorized_scenarios(user, Capability.SCENARIO_EDIT).exists()


def test_private_scenario_grants_only_the_parent_navigation_shell():
    org, project, scenario, sibling, _ = _scope("parent")
    user, membership = _member(org, "single-scenario")
    scenario.access_mode = "private"
    scenario.save(update_fields=["access_mode"])
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        scenario=scenario,
        membership=membership,
        responsibility=ScenarioResponsibility.VIEWER,
        assigned_by=user,
    )
    assert authorize(user=user, capability=Capability.PROJECT_VIEW, project=project).allowed
    assert not authorize(user=user, capability=Capability.PROJECT_MANAGE, project=project).allowed
    assert not authorize(user=user, capability=Capability.SCENARIO_VIEW, scenario=sibling).allowed
    assert list(scoped_scenarios(user).values_list("pk", flat=True)) == [scenario.pk]


def test_unknown_access_mode_fails_closed_in_policy_and_database():
    org, _, scenario, _, _ = _scope("invalid")
    user, _ = _member(org, "invalid-operator")
    scenario.access_mode = "unknown"
    assert (
        authorize(user=user, capability=Capability.SCENARIO_VIEW, scenario=scenario).reason
        == "SCENARIO_ACCESS_MODE_INVALID"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Scenario.objects.filter(pk=scenario.pk).update(access_mode="unknown")
