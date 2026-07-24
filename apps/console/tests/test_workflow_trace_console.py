"""P2.6.11 authorized redacted workflow trace view.

Covers: authorized tenant read renders redacted metadata (statuses, reason codes, failure
classes, counts, truncated checksums); cross-tenant access is denied; and payload-bearing
columns (branch/join/wait state, execution context) never reach the operator screen.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioType
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.roles import Role
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.models import (
    WorkflowBranch,
    WorkflowBranchStatus,
    WorkflowChildLink,
    WorkflowCompensationEntry,
    WorkflowCompensationStatus,
    WorkflowJoin,
    WorkflowJoinStatus,
    WorkflowNodeAttempt,
    WorkflowNodeAttemptStatus,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStatus,
    WorkflowVersion,
    WorkflowWait,
    WorkflowWaitKind,
    WorkflowWaitStatus,
)

User = get_user_model()
pytestmark = pytest.mark.django_db

SECRET = "SUPER-SECRET-TENANT-PAYLOAD"  # noqa: S105  # redaction test marker, not a credential


def _workflow_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "trace.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "format", "type": "format_output", "config": {"template_ref": "ok"}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "format"},
                {"from": "format", "to": "done"},
            ],
        },
    }


def _build_run(org: Organization) -> WorkflowRun:
    project = AIProject.objects.create(organization=org, slug="ops", name="Ops")
    scenario = Scenario.objects.create(
        project=project,
        slug="flow",
        name="Flow",
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
    input_contract = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="wf_in",
        body={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
        created_by="editor",
    )
    output_contract = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="wf_out",
        body={
            "type": "object",
            "required": ["answer", "sources"],
            "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
            "additionalProperties": False,
        },
        created_by="editor",
    )
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="flow_def",
        body=_workflow_body(),
        created_by="editor",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("input_contract", input_contract.type, input_contract.logical_id, 1),
            ArtifactRef("output_contract", output_contract.type, output_contract.logical_id, 1),
            ArtifactRef("workflow_definition", workflow.type, workflow.logical_id, 1),
        ],
        runtime_version="workflow:1",
        created_by="editor",
    )
    promote_release(release)
    version = WorkflowVersion.objects.filter(scenario=scenario).first()
    if version is None:
        version = WorkflowVersion(
            organization=org,
            scenario=scenario,
            source_artifact=workflow,
            compiled_graph={"nodes": {}},
            checksum="c" * 64,
            compiler_version="workflow-compiler/v5",
            created_by="editor",
        )
        version.save()
    consumer = Consumer.objects.create(
        organization=org, subject="wf-client", name="WF", protocol=ConsumerProtocol.REST
    )
    run = WorkflowRun.objects.create(
        organization=org,
        scenario=scenario,
        release=release,
        workflow_version=version,
        consumer=consumer,
        idempotency_key="k1",
        input_checksum="d" * 64,
        execution_context={"secret": SECRET},
        redacted_state={"leak": SECRET},
        status=WorkflowRunStatus.FAILED,
        error_code="WORKFLOW_JOIN_POLICY_INVALID",
        deadline_at=timezone.now() + timedelta(hours=1),
    )
    WorkflowBranch.objects.create(
        organization=org,
        run=run,
        region_node_id="fan",
        branch_name="left",
        item_ordinal=0,
        workflow_checksum="e" * 64,
        transition_version="t1",
        status=WorkflowBranchStatus.SUCCEEDED,
        attempt_count=2,
        reason_code="branch_ok",
        result_checksum="f" * 64,
        input_state={"payload": SECRET},
        result_state={"payload": SECRET},
    )
    WorkflowJoin.objects.create(
        organization=org,
        run=run,
        region_node_id="fan",
        join_node_id="join",
        workflow_checksum="e" * 64,
        transition_version="t1",
        mode="all",
        required_count=1,
        branch_count=1,
        status=WorkflowJoinStatus.SUCCEEDED,
        merged_state={"payload": SECRET},
    )
    WorkflowWait.objects.create(
        organization=org,
        run=run,
        kind=WorkflowWaitKind.HUMAN,
        node_id="approve",
        status=WorkflowWaitStatus.RESUMED,
        correlation_hash="ab" * 16,
        pending_checksum="1" * 64,
        workflow_checksum="e" * 64,
        release_id_snapshot=release.pk,
        compiler_version="workflow-compiler/v5",
        redacted_payload={"payload": SECRET},
        deadline_at=timezone.now() + timedelta(hours=1),
    )
    WorkflowNodeAttempt.objects.create(
        organization=org,
        run=run,
        node_id="format",
        ordinal=1,
        status=WorkflowNodeAttemptStatus.FAILED,
        failure_class="transient",
        reason_code="attempt_failed",
    )
    WorkflowCompensationEntry.objects.create(
        organization=org,
        run=run,
        sequence=1,
        source_node_id="format",
        compensation_node_id="undo",
        status=WorkflowCompensationStatus.SUCCEEDED,
        input_checksum="9" * 64,
        reason_code="comp_done",
        attempt_count=1,
    )
    WorkflowChildLink.objects.create(
        organization=org,
        parent_run=run,
        call_site="child_call",
        child_kind="workflow",
        child_scenario=scenario,
        child_release=release,
        child_release_checksum="a" * 64,
        child_artifact_checksum="b" * 64,
        effective_capability_checksum="c" * 64,
        depth=1,
        status="completed",
        reason_code="child_ok",
    )
    WorkflowRunEvent.objects.create(
        organization=org, run=run, sequence=1, event_type="join_closed", node_id="join"
    )
    return run


def _member(username: str, org: Organization, role: str = Role.PROJECT_OWNER) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


def test_authorized_member_sees_redacted_trace(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="Org A")
    run = _build_run(org)
    client.force_login(_member("alice", org))

    response = client.get(reverse("console:workflow_run_detail", args=[run.pk]))
    assert response.status_code == 200
    text = response.content.decode()
    # Redacted metadata is present.
    assert "WORKFLOW_JOIN_POLICY_INVALID" in text
    assert "branch_ok" in text
    assert "join_closed" in text
    assert "comp_done" in text
    assert "transient" in text
    # No payload/state/execution-context content leaks onto the screen.
    assert SECRET not in text


def test_cross_tenant_trace_is_denied(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="Org A")
    run = _build_run(org_a)
    org_b = Organization.objects.create(slug="org-b", name="Org B")
    client.force_login(_member("mallory", org_b))

    response = client.get(reverse("console:workflow_run_detail", args=[run.pk]))
    assert response.status_code == 403


def test_workflow_runs_list_is_tenant_scoped(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="Org A")
    run = _build_run(org_a)
    org_b = Organization.objects.create(slug="org-b", name="Org B")
    client.force_login(_member("bob", org_b))

    body = client.get(reverse("console:workflow_runs")).content.decode()
    detail_url = reverse("console:workflow_run_detail", args=[run.pk])
    assert detail_url not in body
    assert "workflow çalıştırması yok" in body.casefold()
