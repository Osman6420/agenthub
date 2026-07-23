from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario, ScenarioType
from apps.documents.models import DocumentSet
from apps.identity import assignment_services
from apps.identity.assignment_services import (
    AssignmentError,
    assign_document_set_manager,
    assign_project_administrator,
    assign_scenario_editor,
    remove_delegated_assignment,
)
from apps.identity.authorization import AuthoritySource, Capability, authorize
from apps.identity.models import (
    DocumentSetManagerAssignment,
    ProjectAdministratorAssignment,
)
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


@dataclass
class AssignmentFixture:
    organization: Organization
    foreign_organization: Organization
    administrator: object
    project_admin: object
    editor: object
    document_manager: object
    outsider: object
    project: AIProject
    other_project: AIProject
    scenario: Scenario
    other_scenario: Scenario
    document_set: DocumentSet


@pytest.fixture
def assignment_fixture() -> AssignmentFixture:
    user_model = get_user_model()
    organization = Organization.objects.create(slug="assignment-org", name="Assignment Org")
    foreign = Organization.objects.create(slug="foreign-org", name="Foreign Org")
    users = {
        name: user_model.objects.create_user(username=name, password=None)
        for name in ("administrator", "project-admin", "editor", "document-manager", "outsider")
    }
    for key in ("administrator", "project-admin", "editor", "document-manager"):
        OrganizationMembership.objects.create(
            organization=organization,
            user=users[key],
            role=Role.ORGANIZATION_ADMIN if key == "administrator" else Role.AUDITOR,
        )
    OrganizationMembership.objects.create(
        organization=foreign,
        user=users["outsider"],
        role=Role.AUDITOR,
    )
    project = AIProject.objects.create(
        organization=organization,
        slug="project",
        name="Project",
    )
    other_project = AIProject.objects.create(
        organization=organization,
        slug="other-project",
        name="Other Project",
    )
    scenario = Scenario.objects.create(
        organization=organization,
        project=project,
        slug="scenario",
        name="Scenario",
        type=ScenarioType.RAG,
    )
    other_scenario = Scenario.objects.create(
        organization=organization,
        project=other_project,
        slug="other-scenario",
        name="Other Scenario",
        type=ScenarioType.RAG,
    )
    document_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="documents",
        name="Documents",
    )
    return AssignmentFixture(
        organization=organization,
        foreign_organization=foreign,
        administrator=users["administrator"],
        project_admin=users["project-admin"],
        editor=users["editor"],
        document_manager=users["document-manager"],
        outsider=users["outsider"],
        project=project,
        other_project=other_project,
        scenario=scenario,
        other_scenario=other_scenario,
        document_set=document_set,
    )


def test_organization_admin_assigns_each_scope_and_capabilities_are_exact(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    assign_project_administrator(
        project=fixture.project,
        target_user=fixture.project_admin,
        actor=fixture.administrator,
    )
    assign_scenario_editor(
        scenario=fixture.scenario,
        target_user=fixture.editor,
        actor=fixture.administrator,
    )
    assign_document_set_manager(
        document_set=fixture.document_set,
        target_user=fixture.document_manager,
        actor=fixture.administrator,
    )

    project_decision = authorize(
        user=fixture.project_admin,
        capability=Capability.PROJECT_MANAGE,
        project=fixture.project,
    )
    editor_decision = authorize(
        user=fixture.editor,
        capability=Capability.SCENARIO_EDIT,
        scenario=fixture.scenario,
    )
    document_decision = authorize(
        user=fixture.document_manager,
        capability=Capability.DOCUMENT_SET_CONTENT_MANAGE,
        document_set=fixture.document_set,
    )

    assert project_decision.source == AuthoritySource.PROJECT_ADMINISTRATOR
    assert editor_decision.source == AuthoritySource.SCENARIO_EDITOR
    assert document_decision.source == AuthoritySource.DOCUMENT_SET_MANAGER
    assert not authorize(
        user=fixture.editor,
        capability=Capability.SCENARIO_RELEASE,
        scenario=fixture.scenario,
    ).allowed
    forged_lineage = authorize(
        user=fixture.project_admin,
        capability=Capability.SCENARIO_EDIT,
        project=fixture.project,
        scenario=fixture.other_scenario,
    )
    assert not forged_lineage.allowed
    assert forged_lineage.reason == "TARGET_SCOPE_MISMATCH"
    assert AuditEvent.objects.filter(
        action__startswith="delegated_assignment.",
        outcome="success",
    ).count() == 3


def test_project_admin_delegates_editor_only_inside_assigned_project(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    assign_project_administrator(
        project=fixture.project,
        target_user=fixture.project_admin,
        actor=fixture.administrator,
    )

    assignment = assign_scenario_editor(
        scenario=fixture.scenario,
        target_user=fixture.editor,
        actor=fixture.project_admin,
    )
    assert assignment.scenario_id == fixture.scenario.pk

    with pytest.raises(AssignmentError) as exc:
        assign_scenario_editor(
            scenario=fixture.other_scenario,
            target_user=fixture.editor,
            actor=fixture.project_admin,
        )
    assert exc.value.code == "SCENARIO_EDITOR_DELEGATION_DENIED"
    assert AuditEvent.objects.filter(
        action="delegated_assignment.scenario_editor.create",
        outcome="deny",
        reason="SCENARIO_EDITOR_DELEGATION_DENIED",
    ).exists()


def test_cross_tenant_or_ineligible_target_is_denied_and_audited(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture

    with pytest.raises(AssignmentError) as exc:
        assign_project_administrator(
            project=fixture.project,
            target_user=fixture.outsider,
            actor=fixture.administrator,
        )

    assert exc.value.code == "ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED"
    assert not ProjectAdministratorAssignment.objects.exists()
    assert AuditEvent.objects.filter(
        action="delegated_assignment.project_administrator.create",
        outcome="deny",
        reason="ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED",
    ).exists()


def test_model_rejects_cross_tenant_target_even_outside_service(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture

    with pytest.raises(ValidationError):
        ProjectAdministratorAssignment.objects.create(
            organization=fixture.foreign_organization,
            project=fixture.project,
            user=fixture.outsider,
            assigned_by=fixture.administrator,
        )


def test_required_audit_failure_rolls_back_assignment(
    assignment_fixture: AssignmentFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = assignment_fixture

    def fail_audit(**_kwargs) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(assignment_services, "record_event", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        assign_document_set_manager(
            document_set=fixture.document_set,
            target_user=fixture.document_manager,
            actor=fixture.administrator,
        )

    assert not DocumentSetManagerAssignment.objects.exists()


def test_project_admin_removes_scenario_editor_but_audit_failure_restores_row(
    assignment_fixture: AssignmentFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = assignment_fixture
    assign_project_administrator(
        project=fixture.project,
        target_user=fixture.project_admin,
        actor=fixture.administrator,
    )
    editor_assignment = assign_scenario_editor(
        scenario=fixture.scenario,
        target_user=fixture.editor,
        actor=fixture.administrator,
    )

    def fail_audit(**_kwargs) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(assignment_services, "record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        remove_delegated_assignment(
            assignment=editor_assignment,
            actor=fixture.project_admin,
        )
    assert type(editor_assignment).objects.filter(pk=editor_assignment.pk).exists()

    monkeypatch.undo()
    remove_delegated_assignment(
        assignment=editor_assignment,
        actor=fixture.project_admin,
    )
    assert not type(editor_assignment).objects.filter(pk=editor_assignment.pk).exists()
