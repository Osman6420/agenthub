"""Preview is read-only, scoped, stale-safe and committed with its audit receipt."""

from datetime import timedelta
from threading import Barrier, Thread

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity.access_transition import (
    AccessGrant,
    apply_scenario_access,
    preview_scenario_access,
)
from apps.identity.assignment_services import AssignmentError, grant_scenario_responsibility
from apps.identity.authorization import Capability, authorize
from apps.identity.models import (
    ProjectResponsibility,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.tests.test_delegated_assignments import _membership
from apps.identity.tests.test_delegated_assignments import assignment_fixture as assignment_fixture
from apps.identity.tests.test_inherited_assignment_management import _manager

pytestmark = pytest.mark.django_db


def _private(f):
    return preview_scenario_access(
        scenario=f.scenario,
        actor=f.project_admin,
        mode="private",
        grants=(AccessGrant(_membership(f.editor).pk, ScenarioResponsibility.MANAGER),),
    )


def test_preview_reports_lost_and_gained_access_without_mutation_then_applies_once(
    assignment_fixture,
):
    f = assignment_fixture
    _manager(f)
    specialist = grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.document_manager),
        responsibility=ScenarioResponsibility.RELEASE_MANAGER,
        actor=f.administrator,
    )
    before_audits = AuditEvent.objects.count()
    preview = _private(f)
    changes = {delta.membership_id: delta for delta in preview.changes}
    assert Capability.SCENARIO_VIEW in changes[_membership(f.project_admin).pk].lost
    assert Capability.SCENARIO_RELEASE in changes[_membership(f.editor).pk].gained
    f.scenario.refresh_from_db()
    assert f.scenario.access_mode == "legacy" and f.scenario.access_revision == 0
    assert AuditEvent.objects.count() == before_audits
    applied = apply_scenario_access(scenario=f.scenario, actor=f.project_admin, token=preview.token)
    assert (applied.access_mode, applied.access_revision) == ("private", 1)
    assert not authorize(
        user=f.project_admin, capability=Capability.SCENARIO_VIEW, scenario=applied
    ).allowed
    assert authorize(
        user=f.editor, capability=Capability.SCENARIO_RELEASE, scenario=applied
    ).allowed
    specialist.refresh_from_db()
    assert specialist.status == "active"
    replay = apply_scenario_access(scenario=applied, actor=f.project_admin, token=preview.token)
    assert replay.access_revision == 1
    event = AuditEvent.objects.get(action="responsibility.scenario.access_changed")
    assert isinstance(event.after, dict)
    assert event.after["mode"] == "private" and preview.token not in str(event.after)


def test_preview_rejects_wrong_actor_target_tampering_and_stale_assignments(assignment_fixture):
    f = assignment_fixture
    _manager(f)
    preview = _private(f)
    for target, actor, token in (
        (f.scenario, f.editor, preview.token),
        (f.other_scenario, f.project_admin, preview.token),
        (f.scenario, f.project_admin, preview.token + "x"),
    ):
        with pytest.raises(AssignmentError, match="ACCESS_PREVIEW_INVALID_OR_EXPIRED"):
            apply_scenario_access(scenario=target, actor=actor, token=token)
    grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.document_manager),
        responsibility=ScenarioResponsibility.APPROVER,
        actor=f.administrator,
    )
    with pytest.raises(AssignmentError, match="ACCESS_PREVIEW_STALE"):
        apply_scenario_access(scenario=f.scenario, actor=f.project_admin, token=preview.token)
    f.scenario.refresh_from_db()
    assert f.scenario.access_mode == "legacy"


def test_private_transition_requires_explicit_eligible_permanent_manager(assignment_fixture):
    f = assignment_fixture
    _manager(f)
    for grants, error in (
        ((), "LAST_SCENARIO_MANAGER"),
        (
            (
                AccessGrant(
                    _membership(f.editor).pk,
                    ScenarioResponsibility.MANAGER,
                    timezone.now() + timedelta(days=1),
                ),
            ),
            "LAST_SCENARIO_MANAGER",
        ),
        (
            (AccessGrant(_membership(f.outsider).pk, ScenarioResponsibility.MANAGER),),
            "ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED",
        ),
        (
            (AccessGrant(_membership(f.editor).pk, ScenarioResponsibility.APPROVER),),
            "INVALID_ACCESS_ASSIGNMENTS",
        ),
    ):
        with pytest.raises(AssignmentError, match=error):
            preview_scenario_access(
                scenario=f.scenario, actor=f.project_admin, mode="private", grants=grants
            )


def test_transition_replaces_only_explicit_basic_roles_and_audit_failure_rolls_back(
    assignment_fixture, monkeypatch
):
    f = assignment_fixture
    _manager(f)
    prior = grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.document_manager),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=f.administrator,
    )
    preview = _private(f)

    def unavailable(**kwargs):
        raise RuntimeError("synthetic audit failure")

    with monkeypatch.context() as patch:
        patch.setattr("apps.identity.access_transition.record_event", unavailable)
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            apply_scenario_access(scenario=f.scenario, actor=f.project_admin, token=preview.token)
    f.scenario.refresh_from_db()
    prior.refresh_from_db()
    assert f.scenario.access_mode == "legacy" and prior.status == "active"
    assert not ScenarioResponsibilityAssignment.objects.filter(
        scenario=f.scenario,
        membership=_membership(f.editor),
        responsibility=ScenarioResponsibility.MANAGER,
    ).exists()
    applied = apply_scenario_access(scenario=f.scenario, actor=f.project_admin, token=preview.token)
    prior.refresh_from_db()
    assert prior.status == "revoked" and applied.access_mode == "private"


def test_inherit_transition_preserves_specialists_and_never_upgrades_old_project_administrator(
    assignment_fixture,
):
    from apps.identity.assignment_services import grant_project_responsibility

    f = assignment_fixture
    _manager(f)
    grant_project_responsibility(
        project=f.project,
        membership=_membership(f.editor),
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        actor=f.administrator,
    )
    preview = preview_scenario_access(scenario=f.scenario, actor=f.project_admin, mode="inherit")
    applied = apply_scenario_access(scenario=f.scenario, actor=f.project_admin, token=preview.token)
    assert authorize(
        user=f.project_admin, capability=Capability.SCENARIO_RELEASE, scenario=applied
    ).allowed
    assert not authorize(
        user=f.editor, capability=Capability.SCENARIO_RELEASE, scenario=applied
    ).allowed


def test_expired_preview_is_rejected(assignment_fixture, monkeypatch):
    f = assignment_fixture
    _manager(f)
    preview = _private(f)
    import time

    now = time.time()
    monkeypatch.setattr("django.core.signing.time.time", lambda: now + 601)
    with pytest.raises(AssignmentError, match="ACCESS_PREVIEW_INVALID_OR_EXPIRED"):
        apply_scenario_access(scenario=f.scenario, actor=f.project_admin, token=preview.token)


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="real row-lock serialization")
def test_two_competing_previews_cannot_both_change_access(assignment_fixture):
    f = assignment_fixture
    _manager(f)
    private = _private(f)
    inherited = preview_scenario_access(scenario=f.scenario, actor=f.project_admin, mode="inherit")
    barrier = Barrier(2)
    outcomes = []

    def change(token):
        close_old_connections()
        try:
            barrier.wait(10)
            applied = apply_scenario_access(scenario=f.scenario, actor=f.project_admin, token=token)
            outcomes.append(applied.access_mode)
        except AssignmentError as exc:
            outcomes.append(exc.code)
        except Exception as exc:
            outcomes.append(type(exc).__name__)
        finally:
            close_old_connections()

    workers = [Thread(target=change, args=(preview.token,)) for preview in (private, inherited)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
    assert not any(worker.is_alive() for worker in workers)
    assert outcomes.count("ACCESS_PREVIEW_STALE") == 1
    assert len(set(outcomes) & {"private", "inherit"}) == 1
    f.scenario.refresh_from_db()
    assert f.scenario.access_revision == 1
