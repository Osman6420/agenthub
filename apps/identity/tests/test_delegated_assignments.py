from dataclasses import dataclass
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet
from apps.identity import assignment_services
from apps.identity.assignment_services import (
    AssignmentError,
    grant_document_set_responsibility,
    grant_project_responsibility,
    grant_scenario_responsibility,
    remove_responsibility_assignment,
)
from apps.identity.authorization import AuthoritySource, Capability, authorize
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ResponsibilityStatus,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import MembershipStatus, Organization, OrganizationMembership
from apps.tenancy.services import remove_organization_membership

pytestmark = pytest.mark.django_db


@dataclass
class AssignmentFixture:
    organization: Organization
    foreign_organization: Organization
    administrator: Any
    project_admin: Any
    editor: Any
    document_manager: Any
    outsider: Any
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
    memberships = {}
    for key in ("administrator", "project-admin", "editor", "document-manager"):
        memberships[key] = OrganizationMembership.objects.create(
            organization=organization,
            user=users[key],
        )
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=memberships["administrator"],
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=users["administrator"],
    )
    OrganizationMembership.objects.create(
        organization=foreign,
        user=users["outsider"],
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
    )
    other_scenario = Scenario.objects.create(
        organization=organization,
        project=other_project,
        slug="other-scenario",
        name="Other Scenario",
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


def _membership(user: Any) -> OrganizationMembership:
    return OrganizationMembership.objects.get(user=user)


def test_organization_admin_assigns_each_scope_and_capabilities_are_exact(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    grant_project_responsibility(
        project=fixture.project,
        membership=_membership(fixture.project_admin),
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        actor=fixture.administrator,
    )
    grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.administrator,
    )
    grant_document_set_responsibility(
        document_set=fixture.document_set,
        membership=_membership(fixture.document_manager),
        responsibility=DocumentSetResponsibility.MANAGER,
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

    assert project_decision.source == AuthoritySource.PROJECT_RESPONSIBILITY
    assert editor_decision.source == AuthoritySource.SCENARIO_RESPONSIBILITY
    assert document_decision.source == AuthoritySource.DOCUMENT_SET_RESPONSIBILITY
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
    assert (
        AuditEvent.objects.filter(
            action__startswith="responsibility.",
            outcome="success",
        ).count()
        == 3
    )


def test_project_admin_delegates_editor_only_inside_assigned_project(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    grant_project_responsibility(
        project=fixture.project,
        membership=_membership(fixture.project_admin),
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        actor=fixture.administrator,
    )

    assignment = grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.project_admin,
    )
    assert assignment.scenario_id == fixture.scenario.pk

    with pytest.raises(AssignmentError) as exc:
        grant_scenario_responsibility(
            scenario=fixture.other_scenario,
            membership=_membership(fixture.editor),
            responsibility=ScenarioResponsibility.EDITOR,
            actor=fixture.project_admin,
        )
    assert exc.value.code == "SCENARIO_RESPONSIBILITY_DELEGATION_DENIED"
    assert AuditEvent.objects.filter(
        action="responsibility.scenario.create",
        outcome="deny",
        reason="SCENARIO_RESPONSIBILITY_DELEGATION_DENIED",
    ).exists()


def test_cross_tenant_or_ineligible_target_is_denied_and_audited(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture

    with pytest.raises(AssignmentError) as exc:
        grant_project_responsibility(
            project=fixture.project,
            membership=_membership(fixture.outsider),
            responsibility=ProjectResponsibility.ADMINISTRATOR,
            actor=fixture.administrator,
        )

    assert exc.value.code == "ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED"
    assert not ProjectResponsibilityAssignment.objects.exists()
    assert AuditEvent.objects.filter(
        action="responsibility.project.create",
        outcome="deny",
        reason="ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED",
    ).exists()


def test_model_rejects_cross_tenant_target_even_outside_service(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture

    with pytest.raises(ValidationError):
        ProjectResponsibilityAssignment.objects.create(
            organization=fixture.foreign_organization,
            project=fixture.project,
            membership=_membership(fixture.outsider),
            responsibility=ProjectResponsibility.ADMINISTRATOR,
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
        grant_document_set_responsibility(
            document_set=fixture.document_set,
            membership=_membership(fixture.document_manager),
            responsibility=DocumentSetResponsibility.MANAGER,
            actor=fixture.administrator,
        )

    assert not DocumentSetResponsibilityAssignment.objects.exists()


def test_project_admin_removes_scenario_editor_but_audit_failure_restores_row(
    assignment_fixture: AssignmentFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = assignment_fixture
    grant_project_responsibility(
        project=fixture.project,
        membership=_membership(fixture.project_admin),
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        actor=fixture.administrator,
    )
    editor_assignment = grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.administrator,
    )

    def fail_audit(**_kwargs) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(assignment_services, "record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        remove_responsibility_assignment(
            assignment=editor_assignment,
            actor=fixture.project_admin,
        )
    editor_assignment.refresh_from_db()
    assert editor_assignment.status == ResponsibilityStatus.ACTIVE
    assert editor_assignment.revoked_by_id is None
    assert editor_assignment.revoked_at is None

    monkeypatch.undo()
    remove_responsibility_assignment(
        assignment=editor_assignment,
        actor=fixture.project_admin,
    )
    editor_assignment.refresh_from_db()
    assert editor_assignment.status == ResponsibilityStatus.REVOKED
    assert editor_assignment.revoked_by_id == fixture.project_admin.pk
    assert editor_assignment.revoked_at is not None


def test_revoked_assignment_row_survives_but_grants_no_capability(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    assignment = grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.administrator,
    )
    assert authorize(
        user=fixture.editor,
        capability=Capability.SCENARIO_EDIT,
        scenario=fixture.scenario,
    ).allowed

    remove_responsibility_assignment(assignment=assignment, actor=fixture.administrator)

    assert ScenarioResponsibilityAssignment.objects.filter(pk=assignment.pk).exists()
    denied = authorize(
        user=fixture.editor,
        capability=Capability.SCENARIO_EDIT,
        scenario=fixture.scenario,
    )
    assert not denied.allowed
    assert denied.source == AuthoritySource.NONE
    assert denied.reason == "CAPABILITY_NOT_GRANTED"


def test_removing_an_already_revoked_assignment_is_denied(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    assignment = grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.administrator,
    )
    remove_responsibility_assignment(assignment=assignment, actor=fixture.administrator)

    with pytest.raises(AssignmentError) as exc:
        remove_responsibility_assignment(assignment=assignment, actor=fixture.administrator)
    assert exc.value.code == "ASSIGNMENT_NOT_ACTIVE"
    assert AuditEvent.objects.filter(
        action="responsibility.scenarioresponsibilityassignment.revoke",
        outcome="deny",
        reason="ASSIGNMENT_NOT_ACTIVE",
    ).exists()


def test_membership_revocation_revokes_target_authority_atomically(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    assignment = grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.administrator,
    )
    membership = _membership(fixture.editor)
    remove_organization_membership(membership=membership, actor=fixture.administrator)

    assignment.refresh_from_db()
    membership.refresh_from_db()
    assert membership.status == MembershipStatus.REVOKED
    assert assignment.status == ResponsibilityStatus.REVOKED
    assert assignment.revoked_by_id == fixture.administrator.pk


def test_reinstating_a_revoked_assignment_reuses_the_row_and_reproves_eligibility(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    original = grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.administrator,
    )
    remove_responsibility_assignment(assignment=original, actor=fixture.administrator)

    reinstated = grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.administrator,
    )

    assert reinstated.pk == original.pk
    assert reinstated.status == ResponsibilityStatus.ACTIVE
    assert reinstated.revoked_by_id is None
    assert reinstated.revoked_at is None
    assert ScenarioResponsibilityAssignment.objects.count() == 1
    assert authorize(
        user=fixture.editor,
        capability=Capability.SCENARIO_EDIT,
        scenario=fixture.scenario,
    ).allowed

    # A second grant while active must still be rejected, not silently reinstated again.
    with pytest.raises(AssignmentError) as exc:
        grant_scenario_responsibility(
            scenario=fixture.scenario,
            membership=_membership(fixture.editor),
            responsibility=ScenarioResponsibility.EDITOR,
            actor=fixture.administrator,
        )
    assert exc.value.code == "ASSIGNMENT_ALREADY_EXISTS"


def test_reinstatement_is_refused_after_the_target_leaves_the_organization(
    assignment_fixture: AssignmentFixture,
) -> None:
    fixture = assignment_fixture
    assignment = grant_scenario_responsibility(
        scenario=fixture.scenario,
        membership=_membership(fixture.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=fixture.administrator,
    )
    remove_responsibility_assignment(assignment=assignment, actor=fixture.administrator)
    membership = _membership(fixture.editor)
    remove_organization_membership(membership=membership, actor=fixture.administrator)

    with pytest.raises(AssignmentError) as exc:
        grant_scenario_responsibility(
            scenario=fixture.scenario,
            membership=_membership(fixture.editor),
            responsibility=ScenarioResponsibility.EDITOR,
            actor=fixture.administrator,
        )
    assert exc.value.code == "ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED"
    assignment.refresh_from_db()
    assert assignment.status == ResponsibilityStatus.REVOKED
