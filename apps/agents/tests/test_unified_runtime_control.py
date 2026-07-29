from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model

from apps.agents.models import (
    AgentRuntimeControl,
    RuntimeControlScope,
    RuntimeControlSource,
)
from apps.agents.services import (
    RuntimeControlError,
    change_runtime_control,
    runtime_suspended,
)
from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.identity.models import GlobalAdministrator, ProjectAdministratorAssignment
from apps.identity.roles import Role
from apps.observability.metrics import RUNTIME_CONTROL_CHANGES, RUNTIME_SUSPENSION_BLOCKS
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _user(username: str, organization: Organization, role: str) -> Any:
    user = User.objects.create_user(username=username, password=None)
    OrganizationMembership.objects.create(
        organization=organization,
        user=user,
        role=role,
    )
    return user


def _scope_fixture() -> tuple[
    Organization,
    AIProject,
    Scenario,
    AIProject,
    Scenario,
]:
    organization = Organization.objects.create(slug="runtime-org", name="Runtime Org")
    project = AIProject.objects.create(
        organization=organization,
        slug="project-a",
        name="Project A",
    )
    scenario = Scenario.objects.create(
        organization=organization,
        project=project,
        slug="scenario-a",
        name="Scenario A",
    )
    other_project = AIProject.objects.create(
        organization=organization,
        slug="project-b",
        name="Project B",
    )
    other_scenario = Scenario.objects.create(
        organization=organization,
        project=other_project,
        slug="scenario-b",
        name="Scenario B",
    )
    return organization, project, scenario, other_project, other_scenario


def test_hierarchy_and_exact_project_scope() -> None:
    organization, project, scenario, _other_project, other_scenario = _scope_fixture()
    administrator = _user("org-admin", organization, Role.ORGANIZATION_ADMIN)

    control = change_runtime_control(
        user=administrator,
        scope_type=RuntimeControlScope.PROJECT,
        suspended=True,
        reason_code="incident_response",
        reason="Incident boundary",
        organization=organization,
        project=project,
    )

    assert control.organization_id == organization.pk
    assert control.project_id == project.pk
    assert runtime_suspended(
        organization.pk,
        project_id=project.pk,
        scenario_id=scenario.pk,
    )
    assert not runtime_suspended(
        organization.pk,
        project_id=other_scenario.project_id,
        scenario_id=other_scenario.pk,
    )


def test_corrupt_project_lineage_cannot_suspend_another_tenant() -> None:
    organization, project, _scenario, _other_project, _other_scenario = _scope_fixture()
    foreign = Organization.objects.create(slug="foreign-runtime", name="Foreign Runtime")
    foreign_project = AIProject.objects.create(
        organization=foreign,
        slug="foreign-project",
        name="Foreign Project",
    )
    control = AgentRuntimeControl.objects.create(
        scope_type=RuntimeControlScope.PROJECT,
        organization=organization,
        project=project,
        suspended=True,
    )
    AgentRuntimeControl.objects.filter(pk=control.pk).update(project=foreign_project)

    assert not runtime_suspended(foreign.pk, project_id=foreign_project.pk)


def test_project_administrator_cannot_pause_or_resume() -> None:
    organization, project, scenario, _other_project, _other_scenario = _scope_fixture()
    organization_admin = _user("assigner", organization, Role.ORGANIZATION_ADMIN)
    project_admin = _user("project-admin", organization, Role.AUDITOR)
    ProjectAdministratorAssignment.objects.create(
        organization=organization,
        project=project,
        user=project_admin,
        assigned_by=organization_admin,
    )

    with pytest.raises(RuntimeControlError, match="RUNTIME_CONTROL_FORBIDDEN"):
        change_runtime_control(
            user=project_admin,
            scope_type=RuntimeControlScope.SCENARIO,
            suspended=True,
            reason_code="manual_safety_stop",
            reason="Attempted project stop",
            organization=organization,
            scenario=scenario,
        )

    assert not AgentRuntimeControl.objects.exists()
    assert AuditEvent.objects.filter(
        action="runtime.control.pause",
        outcome="deny",
        actor_id=str(project_admin.pk),
    ).exists()


def test_automatic_control_requires_global_resume_and_denial_is_audited() -> None:
    organization, _project, scenario, _other_project, _other_scenario = _scope_fixture()
    organization_admin = _user("org-admin", organization, Role.ORGANIZATION_ADMIN)
    global_user = User.objects.create_user(username="global-admin", password=None)
    GlobalAdministrator.objects.create(user=global_user)

    change_runtime_control(
        user=organization_admin,
        scope_type=RuntimeControlScope.SCENARIO,
        suspended=True,
        reason_code="policy_violation",
        reason="Automated policy stop",
        organization=organization,
        scenario=scenario,
        source=RuntimeControlSource.AUTOMATIC,
    )
    with pytest.raises(
        RuntimeControlError,
        match="RUNTIME_CONTROL_PRIVILEGED_RESUME_REQUIRED",
    ):
        change_runtime_control(
            user=organization_admin,
            scope_type=RuntimeControlScope.SCENARIO,
            suspended=False,
            reason_code="manual_safety_stop",
            reason="Review complete",
            organization=organization,
            scenario=scenario,
        )
    assert runtime_suspended(
        organization.pk,
        project_id=scenario.project_id,
        scenario_id=scenario.pk,
    )
    assert AuditEvent.objects.filter(
        action="runtime.control.resume",
        outcome="deny",
        reason__startswith="PRIVILEGED_RESUME_REQUIRED",
    ).exists()

    change_runtime_control(
        user=global_user,
        scope_type=RuntimeControlScope.SCENARIO,
        suspended=False,
        reason_code="manual_safety_stop",
        reason="Global review complete",
        organization=organization,
        scenario=scenario,
    )
    assert not runtime_suspended(
        organization.pk,
        project_id=scenario.project_id,
        scenario_id=scenario.pk,
    )


def test_platform_control_requires_global_administrator() -> None:
    organization, _project, _scenario, _other_project, _other_scenario = _scope_fixture()
    organization_admin = _user("org-admin", organization, Role.ORGANIZATION_ADMIN)
    global_user = User.objects.create_user(username="global-admin", password=None)
    GlobalAdministrator.objects.create(user=global_user)

    with pytest.raises(RuntimeControlError, match="RUNTIME_CONTROL_FORBIDDEN"):
        change_runtime_control(
            user=organization_admin,
            scope_type=RuntimeControlScope.PLATFORM,
            suspended=True,
            reason_code="maintenance",
            reason="Platform maintenance",
        )
    change_runtime_control(
        user=global_user,
        scope_type=RuntimeControlScope.PLATFORM,
        suspended=True,
        reason_code="maintenance",
        reason="Platform maintenance",
    )
    assert runtime_suspended(organization.pk)


def test_audit_failure_rolls_back_control(monkeypatch: pytest.MonkeyPatch) -> None:
    organization, project, _scenario, _other_project, _other_scenario = _scope_fixture()
    administrator = _user("org-admin", organization, Role.ORGANIZATION_ADMIN)

    def fail_audit(**_kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.agents.services.record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        change_runtime_control(
            user=administrator,
            scope_type=RuntimeControlScope.PROJECT,
            suspended=True,
            reason_code="dependency_outage",
            reason="Dependency unavailable",
            organization=organization,
            project=project,
        )
    assert not AgentRuntimeControl.objects.exists()


def test_runtime_control_metrics_have_only_bounded_labels() -> None:
    assert RUNTIME_CONTROL_CHANGES._labelnames == ("scope", "action", "outcome")
    assert RUNTIME_SUSPENSION_BLOCKS._labelnames == ("boundary",)
