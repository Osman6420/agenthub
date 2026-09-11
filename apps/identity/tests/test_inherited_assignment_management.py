"""Delegated managers cannot widen scope, grant specialist roles, or remove the last manager."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity.assignment_services import (
    AssignmentError,
    grant_project_responsibility,
    grant_scenario_responsibility,
    remove_responsibility_assignment,
)
from apps.identity.authorization import Capability, authorize
from apps.identity.models import (
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.tests.test_delegated_assignments import _membership
from apps.identity.tests.test_delegated_assignments import assignment_fixture as assignment_fixture

pytestmark = pytest.mark.django_db


def _manager(fixture):
    return grant_project_responsibility(
        project=fixture.project,
        membership=_membership(fixture.project_admin),
        responsibility=ProjectResponsibility.MANAGER,
        actor=fixture.administrator,
    )


def test_project_manager_delegates_only_basic_roles_in_own_project(assignment_fixture):
    f = assignment_fixture
    original = _manager(f)
    other = grant_project_responsibility(
        project=f.project,
        membership=_membership(f.editor),
        responsibility=ProjectResponsibility.MANAGER,
        actor=f.project_admin,
    )
    with pytest.raises(AssignmentError):
        grant_project_responsibility(
            project=f.other_project,
            membership=_membership(f.editor),
            responsibility=ProjectResponsibility.MANAGER,
            actor=f.project_admin,
        )
    with pytest.raises(AssignmentError):
        grant_project_responsibility(
            project=f.project,
            membership=_membership(f.editor),
            responsibility=ProjectResponsibility.ADMINISTRATOR,
            actor=f.project_admin,
        )
    with pytest.raises(AssignmentError):
        grant_scenario_responsibility(
            scenario=f.scenario,
            membership=_membership(f.editor),
            responsibility=ScenarioResponsibility.APPROVER,
            actor=f.project_admin,
        )
    remove_responsibility_assignment(assignment=other, actor=f.project_admin)
    with pytest.raises(AssignmentError, match="LAST_PROJECT_MANAGER"):
        remove_responsibility_assignment(assignment=original, actor=f.administrator)
    assert ProjectResponsibilityAssignment.objects.get(pk=original.pk).status == "active"


def test_private_scenario_access_requires_explicit_assignment_and_retains_a_manager(
    assignment_fixture,
):
    f = assignment_fixture
    _manager(f)
    f.scenario.access_mode = "private"
    f.scenario.save(update_fields=["access_mode"])
    assert not authorize(
        user=f.project_admin, capability=Capability.SCENARIO_VIEW, scenario=f.scenario
    ).allowed
    assert authorize(
        user=f.project_admin, capability=Capability.SCENARIO_ACCESS_MANAGE, scenario=f.scenario
    ).allowed
    manager = grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.project_admin),
        responsibility=ScenarioResponsibility.MANAGER,
        actor=f.project_admin,
    )
    assert authorize(
        user=f.project_admin, capability=Capability.SCENARIO_VIEW, scenario=f.scenario
    ).allowed
    delegated = grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.editor),
        responsibility=ScenarioResponsibility.MANAGER,
        actor=f.project_admin,
    )
    with pytest.raises(AssignmentError):
        grant_project_responsibility(
            project=f.project,
            membership=_membership(f.editor),
            responsibility=ProjectResponsibility.MANAGER,
            actor=f.editor,
        )
    remove_responsibility_assignment(assignment=manager, actor=f.editor)
    with pytest.raises(AssignmentError, match="LAST_SCENARIO_MANAGER"):
        remove_responsibility_assignment(assignment=delegated, actor=f.administrator)
    assert ScenarioResponsibilityAssignment.objects.get(pk=delegated.pk).status == "active"
    assert AuditEvent.objects.filter(
        action="responsibility.scenario.create",
        actor_id=f.project_admin.username,
        outcome="success",
    ).exists()


def test_inherit_rejects_direct_basic_grants_and_first_manager_cannot_expire(assignment_fixture):
    f = assignment_fixture
    with pytest.raises(AssignmentError, match="LAST_PROJECT_MANAGER"):
        grant_project_responsibility(
            project=f.project,
            membership=_membership(f.project_admin),
            responsibility=ProjectResponsibility.MANAGER,
            actor=f.administrator,
            expires_at=timezone.now() + timedelta(days=1),
        )
    f.scenario.access_mode = "inherit"
    f.scenario.save(update_fields=["access_mode"])
    for role in (
        ScenarioResponsibility.VIEWER,
        ScenarioResponsibility.EDITOR,
        ScenarioResponsibility.MANAGER,
    ):
        with pytest.raises(AssignmentError, match="SCENARIO_INHERITS_PROJECT"):
            grant_scenario_responsibility(
                scenario=f.scenario,
                membership=_membership(f.editor),
                responsibility=role,
                actor=f.administrator,
            )
    grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.editor),
        responsibility=ScenarioResponsibility.RELEASE_MANAGER,
        actor=f.administrator,
    )
    assert authorize(
        user=f.editor, capability=Capability.SCENARIO_RELEASE, scenario=f.scenario
    ).allowed
    assert not authorize(
        user=f.editor, capability=Capability.SCENARIO_EDIT, scenario=f.scenario
    ).allowed


def test_revocation_rechecks_actor_under_the_same_lock_and_audit_failure_rolls_back(
    assignment_fixture, monkeypatch
):
    f = assignment_fixture
    manager = _manager(f)
    target = grant_project_responsibility(
        project=f.project,
        membership=_membership(f.editor),
        responsibility=ProjectResponsibility.EDITOR,
        actor=f.project_admin,
    )
    ProjectResponsibilityAssignment.objects.filter(pk=manager.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(AssignmentError):
        remove_responsibility_assignment(assignment=target, actor=f.project_admin)
    target.refresh_from_db()
    assert target.status == "active"

    def unavailable(**kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr("apps.identity.assignment_services.record_event", unavailable)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        remove_responsibility_assignment(assignment=target, actor=f.administrator)
    target.refresh_from_db()
    assert target.status == "active"


def test_membership_offboarding_remains_possible_and_org_admin_can_restore_management(
    assignment_fixture,
):
    from apps.tenancy.services import remove_organization_membership

    f = assignment_fixture
    manager = _manager(f)
    membership = _membership(f.project_admin)
    remove_organization_membership(membership=membership, actor=f.administrator)
    manager.refresh_from_db()
    assert manager.status == "revoked"
    assert not authorize(
        user=f.project_admin, capability=Capability.PROJECT_ACCESS_MANAGE, project=f.project
    ).allowed
    replacement = grant_project_responsibility(
        project=f.project,
        membership=_membership(f.editor),
        responsibility=ProjectResponsibility.MANAGER,
        actor=f.administrator,
    )
    assert replacement.status == "active"
