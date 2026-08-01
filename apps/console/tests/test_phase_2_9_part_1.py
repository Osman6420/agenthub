from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.identity.models import (
    Consumer,
    ConsumerProtocol,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ResponsibilityStatus,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
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


def _member(username: str, organization: Organization) -> tuple[Any, OrganizationMembership]:
    user = User.objects.create_user(username=username, password=None)
    membership = OrganizationMembership.objects.create(organization=organization, user=user)
    return user, membership


def _run(organization: Organization, *, slug: str) -> Run:
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
        checksum=slug[0] * 64,
        created_by="test",
    )
    release = ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="runtime",
        manifest={"artifacts": {}},
        artifact_manifest_sha256="b" * 64,
        created_by="test",
    )
    workflow = WorkflowVersion.objects.create(
        organization=organization,
        scenario=scenario,
        source_artifact=artifact,
        compiled_graph={"nodes": {}},
        checksum="c" * 64,
        compiler_version="test",
        created_by="test",
    )
    consumer = Consumer.objects.create(
        organization=organization,
        subject=f"consumer-{slug}",
        name=f"Consumer {slug}",
        protocol=ConsumerProtocol.REST,
    )
    return Run.objects.create(
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
        status=RunStatus.RUNNING,
        deadline_at=timezone.now() + timedelta(hours=1),
    )


def _assign_scenario(
    *,
    user: Any,
    membership: OrganizationMembership,
    run: Run,
    responsibility: str,
    expires_at=None,
) -> ScenarioResponsibilityAssignment:
    return ScenarioResponsibilityAssignment.objects.create(
        organization=run.organization,
        membership=membership,
        scenario=run.scenario,
        responsibility=responsibility,
        assigned_by=user,
        expires_at=expires_at,
    )


def test_runtime_operator_run_surfaces_are_exact_scenario_scoped(client: Client) -> None:
    organization = Organization.objects.create(slug="exact-runs", name="Exact Runs")
    allowed_run = _run(organization, slug="allowed")
    hidden_run = _run(organization, slug="hidden")
    operator, membership = _member("exact-runtime-operator", organization)
    _assign_scenario(
        user=operator,
        membership=membership,
        run=allowed_run,
        responsibility=ScenarioResponsibility.RUNTIME_OPERATOR,
    )
    client.force_login(operator)

    unified = client.get(reverse("console:runs"), {"kind": "execution"})
    unified_body = unified.content.decode()
    assert unified.status_code == 200
    assert "Scenario allowed" in unified_body
    assert "Scenario hidden" not in unified_body

    compatibility = client.get(reverse("console:workflow_runs"))
    compatibility_body = compatibility.content.decode()
    assert compatibility.status_code == 200
    assert reverse("console:workflow_run_detail", args=[allowed_run.pk]) in compatibility_body
    assert reverse("console:workflow_run_detail", args=[hidden_run.pk]) not in compatibility_body

    assert (
        client.get(reverse("console:workflow_run_detail", args=[allowed_run.pk])).status_code == 200
    )
    hidden_detail = reverse("console:workflow_run_detail", args=[hidden_run.pk])
    assert client.get(hidden_detail).status_code == 404
    hidden_cancel = reverse("console:workflow_run_cancel", args=[hidden_run.pk])
    assert client.post(hidden_cancel).status_code == 404
    hidden_run.refresh_from_db()
    assert hidden_run.cancellation_state == RunCancellationState.NONE


@pytest.mark.parametrize(
    "responsibility",
    [
        ScenarioResponsibility.VIEWER,
        ScenarioResponsibility.EDITOR,
        ScenarioResponsibility.RELEASE_MANAGER,
        ScenarioResponsibility.APPROVER,
    ],
)
def test_neighboring_scenario_roles_do_not_gain_run_visibility(
    client: Client,
    responsibility: str,
) -> None:
    organization = Organization.objects.create(
        slug=f"neighbor-{responsibility}",
        name="Neighboring Role",
    )
    run = _run(organization, slug=responsibility.replace("scenario_", "")[:12])
    user, membership = _member(f"user-{responsibility}", organization)
    _assign_scenario(
        user=user,
        membership=membership,
        run=run,
        responsibility=responsibility,
    )
    client.force_login(user)

    body = client.get(reverse("console:runs"), {"kind": "execution"}).content.decode()
    assert "data-operation-id=" not in body
    assert client.get(reverse("console:workflow_run_detail", args=[run.pk])).status_code == 404


@pytest.mark.parametrize("assignment_state", ["expired", "revoked"])
def test_inactive_runtime_assignment_does_not_grant_run_visibility(
    client: Client,
    assignment_state: str,
) -> None:
    organization = Organization.objects.create(
        slug=f"inactive-{assignment_state}",
        name="Inactive Assignment",
    )
    run = _run(organization, slug=assignment_state)
    user, membership = _member(f"runtime-{assignment_state}", organization)
    expires_at = timezone.now() - timedelta(seconds=1) if assignment_state == "expired" else None
    assignment = _assign_scenario(
        user=user,
        membership=membership,
        run=run,
        responsibility=ScenarioResponsibility.RUNTIME_OPERATOR,
        expires_at=expires_at,
    )
    if assignment_state == "revoked":
        assignment.status = ResponsibilityStatus.REVOKED
        assignment.revoked_by = user
        assignment.revoked_at = timezone.now()
        assignment.save()
    client.force_login(user)

    assert client.get(reverse("console:workflow_run_detail", args=[run.pk])).status_code == 404


def test_organization_auditor_can_read_but_denied_cancel_is_redacted(client: Client) -> None:
    organization = Organization.objects.create(slug="audit-runs", name="Audit Runs")
    first = _run(organization, slug="first")
    _run(organization, slug="second")
    auditor, membership = _member("run-auditor", organization)
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=membership,
        responsibility=OrganizationResponsibility.AUDITOR,
        assigned_by=auditor,
    )
    client.force_login(auditor)

    body = client.get(reverse("console:runs"), {"kind": "execution"}).content.decode()
    assert "Scenario first" in body
    assert "Scenario second" in body
    assert client.get(reverse("console:workflow_run_detail", args=[first.pk])).status_code == 200

    denied = client.post(reverse("console:workflow_run_cancel", args=[first.pk]))
    assert denied.status_code == 403
    first.refresh_from_db()
    assert first.cancellation_state == RunCancellationState.NONE
    event = AuditEvent.objects.get(action="runtime.run_cancel", outcome="deny")
    evidence = f"{event.reason} {event.before} {event.after}"
    assert event.resource_id == str(first.pk)
    assert "Scenario first" not in evidence
    assert first.actor_id not in evidence


def test_cross_tenant_run_identifier_is_non_disclosing(client: Client) -> None:
    foreign = Organization.objects.create(slug="foreign-runs", name="Foreign Runs")
    foreign_run = _run(foreign, slug="foreign")
    own = Organization.objects.create(slug="own-runs", name="Own Runs")
    own_run = _run(own, slug="own")
    operator, membership = _member("own-runtime-operator", own)
    _assign_scenario(
        user=operator,
        membership=membership,
        run=own_run,
        responsibility=ScenarioResponsibility.RUNTIME_OPERATOR,
    )
    client.force_login(operator)

    assert (
        client.get(reverse("console:workflow_run_detail", args=[foreign_run.pk])).status_code == 404
    )
    foreign_cancel = reverse("console:workflow_run_cancel", args=[foreign_run.pk])
    assert client.post(foreign_cancel).status_code == 404
