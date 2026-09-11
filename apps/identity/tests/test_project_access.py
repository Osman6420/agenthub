"""Project role previews match effective access and fail closed at apply."""

from datetime import timedelta
from threading import Barrier, Thread

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.catalog.models import Scenario
from apps.identity.access_transition import AccessGrant
from apps.identity.assignment_services import (
    AssignmentError,
    grant_project_responsibility,
    grant_scenario_responsibility,
)
from apps.identity.authorization import Capability, authorize
from apps.identity.models import ProjectResponsibility as P
from apps.identity.models import ScenarioResponsibility as S
from apps.identity.project_access import apply_project_access, preview_project_access
from apps.identity.tests.test_delegated_assignments import _membership
from apps.identity.tests.test_delegated_assignments import assignment_fixture as assignment_fixture
from apps.identity.tests.test_inherited_assignment_management import _manager

pytestmark = pytest.mark.django_db


def _grants(f, extra=()):
    return (AccessGrant(_membership(f.project_admin).pk, P.MANAGER), *extra)


def test_project_preview_matches_three_modes_preserves_legacy_and_specialists(assignment_fixture):
    f = assignment_fixture
    _manager(f)
    old = grant_project_responsibility(
        project=f.project,
        membership=_membership(f.document_manager),
        responsibility=P.ADMINISTRATOR,
        actor=f.administrator,
    )
    specialist = grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.document_manager),
        responsibility=S.APPROVER,
        actor=f.administrator,
    )
    inherited = Scenario.objects.create(
        project=f.project,
        organization=f.organization,
        name="Inherited",
        slug="inherited",
        access_mode="inherit",
    )
    private = Scenario.objects.create(
        project=f.project,
        organization=f.organization,
        name="Private",
        slug="private",
        access_mode="private",
    )
    grants = _grants(f, (AccessGrant(_membership(f.editor).pk, P.MANAGER),))
    before = AuditEvent.objects.count()
    preview = preview_project_access(project=f.project, actor=f.project_admin, grants=grants)
    assert AuditEvent.objects.count() == before
    delta = {row.scope: row for row in preview.changes if row.username == "editor"}
    assert Capability.SCENARIO_RELEASE in delta[inherited.name].gained
    assert delta[private.name].gained == (Capability.SCENARIO_ACCESS_MANAGE,)
    assert Capability.SCENARIO_RELEASE not in delta[f.scenario.name].gained
    result = apply_project_access(project=f.project, actor=f.project_admin, token=preview.token)
    assert result.access_revision == 1
    for scenario in (f.scenario, inherited, private):
        for cap in delta[scenario.name].gained:
            assert authorize(user=f.editor, capability=Capability(cap), scenario=scenario).allowed
    assert not authorize(
        user=f.editor, capability=Capability.SCENARIO_VIEW, scenario=private
    ).allowed
    old.refresh_from_db()
    specialist.refresh_from_db()
    assert old.status == specialist.status == "active"
    replay = apply_project_access(project=f.project, actor=f.project_admin, token=preview.token)
    assert replay.access_revision == 1
    assert AuditEvent.objects.filter(action="responsibility.project.access_changed").count() == 1


def test_project_preview_rejects_bad_scope_role_expiry_or_last_manager(assignment_fixture):
    f = assignment_fixture
    _manager(f)
    for grants, code in (
        ((), "LAST_PROJECT_MANAGER"),
        (
            (AccessGrant(_membership(f.editor).pk, P.MANAGER, timezone.now() + timedelta(days=1)),),
            "LAST_PROJECT_MANAGER",
        ),
        (
            _grants(f, (AccessGrant(_membership(f.outsider).pk, P.EDITOR),)),
            "ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED",
        ),
        (
            _grants(f, (AccessGrant(_membership(f.editor).pk, P.ADMINISTRATOR),)),
            "INVALID_ACCESS_ASSIGNMENTS",
        ),
    ):
        with pytest.raises(AssignmentError, match=code):
            preview_project_access(project=f.project, actor=f.project_admin, grants=grants)
    for actor, project in ((f.editor, f.project), (f.project_admin, f.other_project)):
        with pytest.raises(AssignmentError, match="PROJECT_ACCESS_MANAGEMENT_REQUIRED"):
            preview_project_access(project=project, actor=actor, grants=_grants(f))


def test_project_apply_rejects_tampered_actor_target_stale_and_expired(
    assignment_fixture, monkeypatch
):
    f = assignment_fixture
    _manager(f)
    preview = preview_project_access(project=f.project, actor=f.project_admin, grants=_grants(f))
    for actor, project, token in (
        (f.editor, f.project, preview.token),
        (f.project_admin, f.other_project, preview.token),
        (f.project_admin, f.project, preview.token + "x"),
    ):
        with pytest.raises(AssignmentError, match="ACCESS_PREVIEW_INVALID_OR_EXPIRED"):
            apply_project_access(project=project, actor=actor, token=token)
    with monkeypatch.context() as patch:
        import time

        now = time.time()
        patch.setattr("django.core.signing.time.time", lambda: now + 601)
        with pytest.raises(AssignmentError, match="ACCESS_PREVIEW_INVALID_OR_EXPIRED"):
            apply_project_access(project=f.project, actor=f.project_admin, token=preview.token)
    f.scenario.access_mode = "inherit"
    f.scenario.save(update_fields=["access_mode"])
    with pytest.raises(AssignmentError, match="ACCESS_PREVIEW_STALE"):
        apply_project_access(project=f.project, actor=f.project_admin, token=preview.token)


def test_project_apply_reauthorizes_and_audit_failure_rolls_back(assignment_fixture, monkeypatch):
    f = assignment_fixture
    role = _manager(f)
    preview = preview_project_access(
        project=f.project,
        actor=f.project_admin,
        grants=_grants(f, (AccessGrant(_membership(f.editor).pk, P.EDITOR),)),
    )

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("apps.identity.project_access.record_event", unavailable)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            apply_project_access(project=f.project, actor=f.project_admin, token=preview.token)
    f.project.refresh_from_db()
    assert f.project.access_revision == 0
    assert not authorize(
        user=f.editor, capability=Capability.SCENARIO_CREATE, project=f.project
    ).allowed
    type(role).objects.filter(pk=role.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(AssignmentError, match="PROJECT_ACCESS_MANAGEMENT_REQUIRED"):
        apply_project_access(project=f.project, actor=f.project_admin, token=preview.token)


@pytest.mark.django_db(transaction=True)
def test_concurrent_project_previews_cannot_overwrite_each_other(assignment_fixture):
    if connection.vendor != "postgresql":
        pytest.skip("Real row-lock concurrency requires PostgreSQL")
    f = assignment_fixture
    _manager(f)
    previews = [
        preview_project_access(
            project=f.project,
            actor=f.project_admin,
            grants=_grants(f, (AccessGrant(_membership(f.editor).pk, role),)),
        )
        for role in (P.VIEWER, P.EDITOR)
    ]
    barrier = Barrier(2)
    outcomes = []

    def apply(preview):
        close_old_connections()
        try:
            barrier.wait()
            apply_project_access(project=f.project, actor=f.project_admin, token=preview.token)
            outcomes.append("success")
        except AssignmentError as exc:
            outcomes.append(exc.code)
        finally:
            close_old_connections()

    threads = [Thread(target=apply, args=(preview,)) for preview in previews]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["ACCESS_PREVIEW_STALE", "success"]
