from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.catalog.models import Scenario, ScenarioAlias
from apps.catalog.services import create_authorized_console_scenario
from apps.identity.assignment_services import AssignmentError
from apps.identity.tests.test_delegated_assignments import _membership
from apps.identity.tests.test_delegated_assignments import assignment_fixture as assignment_fixture
from apps.identity.tests.test_inherited_assignment_management import _manager

pytestmark = pytest.mark.django_db


def test_creation_rechecks_actor_membership_manager_and_closed_mode(assignment_fixture):
    f = assignment_fixture
    assignment = _manager(f)
    for actor, mode, manager, error in (
        (f.editor, "inherit", None, "SCENARIO_CREATE_REQUIRED"),
        (f.project_admin, "legacy", None, "INVALID_ACCESS_MODE"),
        (
            f.project_admin,
            "private",
            _membership(f.outsider),
            "ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED",
        ),
        (f.project_admin, "inherit", _membership(f.editor), "INVALID_ACCESS_ASSIGNMENTS"),
    ):
        with pytest.raises(AssignmentError, match=error):
            create_authorized_console_scenario(
                project=f.project,
                name="Rejected",
                actor=actor,
                access_mode=mode,
                initial_manager=manager,
            )
    member = _membership(f.editor)
    type(member).objects.filter(pk=member.pk).update(
        status="revoked", revoked_at=timezone.now(), revoked_by=f.administrator
    )
    with pytest.raises(AssignmentError, match="ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED"):
        create_authorized_console_scenario(
            project=f.project,
            name="Rejected",
            actor=f.project_admin,
            access_mode="private",
            initial_manager=member,
        )
    type(assignment).objects.filter(pk=assignment.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(AssignmentError, match="SCENARIO_CREATE_REQUIRED"):
        create_authorized_console_scenario(
            project=f.project, name="Rejected", actor=f.project_admin, access_mode="inherit"
        )
    assert not Scenario.objects.filter(name="Rejected").exists()
    assert (
        AuditEvent.objects.filter(
            action="responsibility.scenario.access_created", outcome="deny"
        ).count()
        == 6
    )


def test_initial_access_and_alias_roll_back_with_audit_failure(assignment_fixture, monkeypatch):
    f = assignment_fixture
    _manager(f)
    before = (Scenario.objects.count(), ScenarioAlias.objects.count(), AuditEvent.objects.count())

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.audit.services.record_event", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create_authorized_console_scenario(
            project=f.project,
            name="Rollback",
            actor=f.project_admin,
            access_mode="private",
            initial_manager=_membership(f.editor),
        )
    assert before == (
        Scenario.objects.count(),
        ScenarioAlias.objects.count(),
        AuditEvent.objects.count(),
    )
