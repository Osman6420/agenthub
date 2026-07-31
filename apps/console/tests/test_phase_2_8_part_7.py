from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agents.models import AgentRuntimeControl, RuntimeControlScope
from apps.artifacts.models import ArtifactVersion
from apps.catalog.models import AIProject, Scenario
from apps.console.operations import parse_operation_filters, project_operations
from apps.identity.models import (
    Consumer,
    ConsumerProtocol,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.roles import Role
from apps.ingestion.models import ConnectorType, IngestionRun, Source
from apps.ingestion.models import RunStatus as IngestionStatus
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.models import (
    Run,
    RunCancellationState,
    RunStatus,
    WorkflowVersion,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member(username: str, organization: Organization, role: str = Role.AUDITOR) -> Any:
    user = User.objects.create_user(username=username, password=None)
    membership = OrganizationMembership.objects.create(
        organization=organization,
        user=user,
    )
    responsibility = {
        Role.ORGANIZATION_ADMIN: OrganizationResponsibility.ADMINISTRATOR,
        Role.AUDITOR: OrganizationResponsibility.AUDITOR,
    }.get(role)
    if responsibility is not None:
        OrganizationResponsibilityAssignment.objects.create(
            organization=organization,
            membership=membership,
            responsibility=responsibility,
            assigned_by=user,
        )
    return user


def _execution(
    organization: Organization,
    *,
    slug: str,
    status: str,
) -> tuple[Run, AIProject, Scenario]:
    project = AIProject.objects.create(
        organization=organization,
        slug=f"project-{slug}",
        name=f"Project {slug}",
    )
    scenario = Scenario.objects.create(
        organization=organization,
        project=project,
        slug=f"scenario-{slug}",
        name=f"Scenario {slug}",
    )
    artifact = ArtifactVersion.objects.create(
        organization=organization,
        type="workflow_definition",
        logical_id=f"workflow-{slug}",
        version=1,
        body={"nodes": {}},
        checksum=(slug[0] * 64),
        created_by="test",
    )
    release = ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="runtime",
        manifest={"artifacts": {}},
        artifact_manifest_sha256=("b" * 64),
        created_by="test",
    )
    workflow = WorkflowVersion.objects.create(
        organization=organization,
        scenario=scenario,
        source_artifact=artifact,
        compiled_graph={"nodes": {}},
        checksum=("c" * 64),
        compiler_version="test",
        created_by="test",
    )
    consumer = Consumer.objects.create(
        organization=organization,
        subject=f"consumer-{slug}",
        name=f"Consumer {slug}",
        protocol=ConsumerProtocol.REST,
    )
    run = Run.objects.create(
        organization=organization,
        scenario=scenario,
        release=release,
        workflow_version=workflow,
        consumer=consumer,
        actor_id=consumer.subject,
        response_id=f"resp_{slug.zfill(32)}",
        idempotency_key=slug,
        compiled_checksum=workflow.checksum,
        compiler_version=workflow.compiler_version,
        execution_mode="background",
        checkpoint={},
        input_checksum="d" * 64,
        execution_context={},
        redacted_state={},
        status=status,
        deadline_at=timezone.now() + timedelta(hours=1),
    )
    return run, project, scenario


def test_unified_operations_are_tenant_first_and_kind_filtered(client: Client) -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    foreign = Organization.objects.create(slug="foreign", name="Foreign")
    _execution(organization, slug="own", status=RunStatus.RUNNING)
    _execution(foreign, slug="foreign", status=RunStatus.FAILED)
    source = Source.objects.create(
        organization=organization,
        slug="source",
        name="Safe Source",
        connector_type=ConnectorType.HTTPS,
        connector_config={"url": "https://example.invalid/data"},
    )
    IngestionRun.objects.create(
        organization=organization,
        source=source,
        status=IngestionStatus.RUNNING,
    )
    client.force_login(_member("reader", organization))

    response = client.get(reverse("console:runs"))
    body = response.content.decode()
    assert response.status_code == 200
    assert body.count("data-operation-id=") == 2
    assert "Scenario own" in body
    assert "Safe Source" in body
    assert "Scenario foreign" not in body

    execution_only = client.get(reverse("console:runs"), {"kind": "execution"})
    assert execution_only.status_code == 200
    assert execution_only.content.decode().count("data-operation-id=") == 1
    assert "Safe Source" not in execution_only.content.decode()


def test_unified_projection_has_a_fixed_native_query_bound(
    django_assert_num_queries,
) -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    filters = parse_operation_filters({}, organization=organization)

    with django_assert_num_queries(7):
        page = project_operations(organization=organization, filters=filters)

    assert page.rows == ()


def test_dashboard_execution_buckets_match_native_status_contract(client: Client) -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    _execution(organization, slug="running", status=RunStatus.RUNNING)
    _execution(organization, slug="waiting", status=RunStatus.WAITING_HUMAN)
    _execution(organization, slug="done", status=RunStatus.COMPLETED)
    client.force_login(_member("reader", organization))

    active = client.get(
        reverse("console:runs"),
        {"kind": "execution", "bucket": "active", "days": "90"},
    )
    done = client.get(
        reverse("console:runs"),
        {"kind": "execution", "bucket": "done", "days": "1"},
    )

    assert active.status_code == 200
    assert active.content.decode().count("data-operation-id=") == 2
    assert "<strong>Scenario done</strong>" not in active.content.decode()
    assert done.status_code == 200
    assert done.content.decode().count("data-operation-id=") == 1
    assert "<strong>Scenario done</strong>" in done.content.decode()


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"kind": "unknown"}, "OPERATIONS_FILTER_INVALID"),
        ({"days": "91"}, "OPERATIONS_FILTER_OUT_OF_BOUNDS"),
        ({"page": "11"}, "OPERATIONS_FILTER_OUT_OF_BOUNDS"),
        ({"project": "not-a-uuid"}, "OPERATIONS_PROJECT_INVALID"),
    ],
)
def test_unified_operation_filters_fail_closed(
    client: Client,
    params: dict[str, str],
    code: str,
) -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    client.force_login(_member("reader", organization))

    response = client.get(reverse("console:runs"), params)

    assert response.status_code == 400
    assert code in response.content.decode()
    assert "data-operation-id=" not in response.content.decode()


def test_runtime_operator_can_pause_exact_scenario_via_csrf_post(client: Client) -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    _run, _project, _scenario = _execution(
        organization,
        slug="own",
        status=RunStatus.RUNNING,
    )
    operator = _member("runtime-operator", organization)
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        membership=OrganizationMembership.objects.get(organization=organization, user=operator),
        scenario=_scenario,
        responsibility=ScenarioResponsibility.RUNTIME_OPERATOR,
        assigned_by=operator,
    )
    client.force_login(operator)

    response = client.post(
        reverse("console:runtime_control_change"),
        {
            "scope_type": "scenario",
            "target": str(_scenario.public_id),
            "action": "pause",
            "reason_code": "incident_response",
            "reason": "Incident isolation",
        },
    )

    assert response.status_code == 302
    control = AgentRuntimeControl.objects.get(
        scope_type=RuntimeControlScope.SCENARIO,
        scenario=_scenario,
    )
    assert control.suspended is True
    assert control.organization_id == organization.pk
    assert client.get(reverse("console:runtime_control_change")).status_code == 405


def test_runtime_control_post_requires_csrf() -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    administrator = _member("org-admin", organization, Role.ORGANIZATION_ADMIN)
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(administrator)

    response = csrf_client.post(
        reverse("console:runtime_control_change"),
        {
            "scope_type": "organization",
            "action": "pause",
            "reason_code": "incident_response",
            "reason": "Missing CSRF token",
        },
    )

    assert response.status_code == 403
    assert not AgentRuntimeControl.objects.exists()


def test_native_run_cancel_reauthorizes_exact_action(client: Client) -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    run, _project, _scenario = _execution(
        organization,
        slug="own",
        status=RunStatus.RUNNING,
    )
    auditor = _member("auditor", organization)
    client.force_login(auditor)
    denied = client.post(reverse("console:workflow_run_cancel", args=[run.pk]))
    assert denied.status_code == 403
    run.refresh_from_db()
    assert run.cancellation_state == RunCancellationState.NONE

    operator = _member("runtime-operator", organization)
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        membership=OrganizationMembership.objects.get(organization=organization, user=operator),
        scenario=run.scenario,
        responsibility=ScenarioResponsibility.RUNTIME_OPERATOR,
        assigned_by=operator,
    )
    client.force_login(operator)
    allowed = client.post(reverse("console:workflow_run_cancel", args=[run.pk]))
    assert allowed.status_code == 302
    run.refresh_from_db()
    assert run.cancellation_state == RunCancellationState.REQUESTED


def test_dashboard_kpi_links_use_exact_execution_projection(client: Client) -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    client.force_login(_member("reader", organization))

    body = client.get(reverse("console:dashboard")).content.decode()

    assert f"{reverse('console:runs')}?kind=execution&amp;bucket=active" in body
    assert f"{reverse('console:runs')}?kind=execution&amp;bucket=done" in body
