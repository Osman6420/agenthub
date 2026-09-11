import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents import access_services
from apps.documents.access_services import (
    ScenarioDocumentSetAccessError,
    approve_scenario_document_set_access,
    bind_authorized_scenario_document_set,
    grant_scenario_document_set_access_if_authorized,
    has_live_scenario_document_set_grant,
    request_scenario_document_set_access,
    revoke_scenario_document_set_grant,
)
from apps.documents.models import (
    DocumentSet,
    DocumentSetGrant,
    GrantPrincipalType,
    ScenarioDocumentSetAccessRequest,
    ScenarioDocumentSetBinding,
    ScenarioDocumentSetGrant,
)
from apps.identity.assignment_services import (
    grant_document_set_responsibility,
    grant_project_responsibility,
    grant_scenario_responsibility,
)
from apps.identity.models import (
    DocumentSetResponsibility,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ScenarioResponsibility,
)
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def access_fixture():
    user_model = get_user_model()
    organization = Organization.objects.create(slug="access-org", name="Access Org")
    foreign = Organization.objects.create(slug="access-foreign", name="Foreign")
    users = {
        name: user_model.objects.create_user(username=f"access-{name}", password=None)
        for name in ("admin", "project", "manager", "outsider")
    }
    memberships = {}
    for name in ("admin", "project", "manager"):
        memberships[name] = OrganizationMembership.objects.create(
            organization=organization,
            user=users[name],
        )
    OrganizationMembership.objects.create(
        organization=foreign,
        user=users["outsider"],
    )
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=memberships["admin"],
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=users["admin"],
    )
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
    document_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="set",
        name="Set",
    )
    foreign_set = DocumentSet.objects.create(
        organization=foreign,
        logical_id="foreign",
        name="Foreign",
    )
    grant_project_responsibility(
        project=project,
        membership=memberships["project"],
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        actor=users["admin"],
    )
    grant_scenario_responsibility(
        scenario=scenario,
        membership=memberships["project"],
        responsibility=ScenarioResponsibility.EDITOR,
        actor=users["project"],
    )
    grant_document_set_responsibility(
        document_set=document_set,
        membership=memberships["manager"],
        responsibility=DocumentSetResponsibility.MANAGER,
        actor=users["admin"],
    )
    return {
        "organization": organization,
        "admin": users["admin"],
        "project_admin": users["project"],
        "manager": users["manager"],
        "scenario": scenario,
        "document_set": document_set,
        "foreign_set": foreign_set,
    }


def test_request_approve_bind_and_revoke_lifecycle(access_fixture) -> None:
    fixture = access_fixture
    access_request = request_scenario_document_set_access(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        purpose="Ground support answers",
        actor=fixture["project_admin"],
    )
    grant = approve_scenario_document_set_access(
        access_request=access_request,
        actor=fixture["manager"],
    )
    binding = bind_authorized_scenario_document_set(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        actor=fixture["project_admin"],
    )

    assert binding.pk is not None
    assert has_live_scenario_document_set_grant(
        scenario_id=fixture["scenario"].pk,
        document_set_id=fixture["document_set"].pk,
    )

    revoke_scenario_document_set_grant(grant=grant, actor=fixture["manager"])

    assert not has_live_scenario_document_set_grant(
        scenario_id=fixture["scenario"].pk,
        document_set_id=fixture["document_set"].pk,
    )
    assert ScenarioDocumentSetBinding.objects.filter(pk=binding.pk).exists()
    assert AuditEvent.objects.filter(
        action="scenario_document_set_access.revoke",
        outcome="success",
    ).exists()


def test_superadmin_can_revoke_grant_as_alerted_recovery_action(access_fixture) -> None:
    fixture = access_fixture
    access_request = request_scenario_document_set_access(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        purpose="Emergency revocation proof",
        actor=fixture["project_admin"],
    )
    grant = approve_scenario_document_set_access(
        access_request=access_request,
        actor=fixture["manager"],
    )
    superadmin = get_user_model().objects.create_superuser(
        username="recovery-admin",
        password=None,
    )

    revoke_scenario_document_set_grant(grant=grant, actor=superadmin)

    assert not has_live_scenario_document_set_grant(
        scenario_id=fixture["scenario"].pk,
        document_set_id=fixture["document_set"].pk,
    )
    assert AuditEvent.objects.filter(
        action="superadmin.scenario_document_set_access_revoke",
        outcome="success",
        actor_id=superadmin.get_username(),
    ).exists()


def test_bind_requires_live_grant(access_fixture) -> None:
    fixture = access_fixture

    with pytest.raises(ScenarioDocumentSetAccessError) as exc:
        bind_authorized_scenario_document_set(
            scenario=fixture["scenario"],
            document_set=fixture["document_set"],
            actor=fixture["project_admin"],
        )

    assert exc.value.code == "LIVE_RETRIEVE_GRANT_REQUIRED"
    assert not ScenarioDocumentSetBinding.objects.exists()


def test_only_document_set_manager_can_approve(access_fixture) -> None:
    fixture = access_fixture
    access_request = request_scenario_document_set_access(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        purpose="Approved purpose",
        actor=fixture["project_admin"],
    )

    with pytest.raises(ScenarioDocumentSetAccessError) as exc:
        approve_scenario_document_set_access(
            access_request=access_request,
            actor=fixture["admin"],
        )

    assert exc.value.code == "DOCUMENT_SET_MANAGER_REQUIRED"
    assert not ScenarioDocumentSetGrant.objects.exists()
    assert AuditEvent.objects.filter(
        action="scenario_document_set_access.approve",
        outcome="deny",
    ).exists()


def test_organization_admin_cannot_revoke_document_manager_grant(access_fixture) -> None:
    fixture = access_fixture
    access_request = request_scenario_document_set_access(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        purpose="Revocation authority",
        actor=fixture["project_admin"],
    )
    grant = approve_scenario_document_set_access(
        access_request=access_request,
        actor=fixture["manager"],
    )

    with pytest.raises(ScenarioDocumentSetAccessError) as exc:
        revoke_scenario_document_set_grant(
            grant=grant,
            actor=fixture["admin"],
        )

    assert exc.value.code == "DOCUMENT_SET_MANAGER_REQUIRED"
    grant.refresh_from_db()
    assert grant.is_active
    assert AuditEvent.objects.filter(
        action="scenario_document_set_access.revoke",
        outcome="deny",
    ).exists()


def test_cross_tenant_request_fails_closed(access_fixture) -> None:
    fixture = access_fixture

    with pytest.raises(ScenarioDocumentSetAccessError) as exc:
        request_scenario_document_set_access(
            scenario=fixture["scenario"],
            document_set=fixture["foreign_set"],
            purpose="Must fail",
            actor=fixture["project_admin"],
        )

    assert exc.value.code == "SCENARIO_ACCESS_REQUEST_DENIED"
    assert not ScenarioDocumentSetAccessRequest.objects.exists()


def test_approval_audit_failure_rolls_back_request_and_grant(
    access_fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = access_fixture
    access_request = request_scenario_document_set_access(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        purpose="Audit rollback",
        actor=fixture["project_admin"],
    )

    def fail_audit(**_kwargs) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(access_services, "record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        approve_scenario_document_set_access(
            access_request=access_request,
            actor=fixture["manager"],
        )

    access_request.refresh_from_db()
    assert access_request.status == "pending"
    assert not ScenarioDocumentSetGrant.objects.exists()


def test_bind_grants_when_actor_is_document_set_manager(access_fixture) -> None:
    """BUG-003/BUG-015 option (a): a document-set manager granting on bind also unblocks the
    shared evaluation consumer, so "Sor"/eval retrieval works without a separate hidden step."""
    fixture = access_fixture

    grant = grant_scenario_document_set_access_if_authorized(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        actor=fixture["manager"],
    )

    assert grant is not None
    assert has_live_scenario_document_set_grant(
        scenario_id=fixture["scenario"].pk,
        document_set_id=fixture["document_set"].pk,
    )
    assert AuditEvent.objects.filter(
        action="scenario_document_set_access.grant_on_bind",
        outcome="success",
    ).exists()
    assert DocumentSetGrant.objects.filter(
        document_set=fixture["document_set"],
        principal_type=GrantPrincipalType.CONSUMER,
        permission="retrieve",
    ).exists()


def test_bind_grant_is_noop_without_document_set_manager_authority(access_fixture) -> None:
    """A scenario editor without document-set-manager authority cannot self-grant; binding
    must still succeed elsewhere (this function alone doesn't bind), and no grant is created."""
    fixture = access_fixture

    grant = grant_scenario_document_set_access_if_authorized(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        actor=fixture["project_admin"],
    )

    assert grant is None
    assert not has_live_scenario_document_set_grant(
        scenario_id=fixture["scenario"].pk,
        document_set_id=fixture["document_set"].pk,
    )
    assert not DocumentSetGrant.objects.filter(document_set=fixture["document_set"]).exists()


def test_bind_grant_is_idempotent_for_evaluation_consumer(access_fixture) -> None:
    fixture = access_fixture

    first = grant_scenario_document_set_access_if_authorized(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        actor=fixture["manager"],
    )
    second = grant_scenario_document_set_access_if_authorized(
        scenario=fixture["scenario"],
        document_set=fixture["document_set"],
        actor=fixture["manager"],
    )

    assert first is not None
    assert second is not None
    assert first.pk == second.pk
    assert (
        DocumentSetGrant.objects.filter(
            document_set=fixture["document_set"],
            principal_type=GrantPrincipalType.CONSUMER,
        ).count()
        == 1
    )
