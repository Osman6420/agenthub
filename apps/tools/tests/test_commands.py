"""Operator management commands: decide/list/cancel with role authorization."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.identity.capabilities import Capability
from apps.identity.models import (
    Consumer,
    ConsumerProtocol,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.roles import Role
from apps.releases.compiler import ArtifactRef, compile_release
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tools.approvals import request_tool_invocation
from apps.tools.models import ApprovalRequest, ApprovalStatus, ToolInvocation, ToolInvocationStatus
from apps.tools.services import register_tool_binding, register_tool_definition
from apps.workflows.presets import empty_workflow

ORG_SLUG = "tool-org"
CAPS: list[str] = [Capability.TOOL_CALL_SIDE_EFFECT]


def _pending_approval() -> tuple[Organization, ApprovalRequest, ToolInvocation]:
    org = Organization.objects.create(slug=ORG_SLUG, name="Tool Org")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(project=project, slug="flow", name="Flow")
    for logical, atype, body in (
        (
            "tool_in",
            ArtifactType.INPUT_CONTRACT,
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        (
            "tool_out",
            ArtifactType.OUTPUT_CONTRACT,
            {"type": "object", "properties": {"status": {"type": "string"}}},
        ),
    ):
        create_artifact_version(
            organization=org, artifact_type=atype, logical_id=logical, body=body, created_by="e"
        )
    definition = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_DEFINITION,
        logical_id="search",
        body={
            "api_version": "agenthub/v1",
            "kind": "ToolDefinition",
            "metadata": {"id": "search.v1", "owner": "platform"},
            "spec": {
                "protocol": "http",
                "destination": {"scheme": "https", "host": "api.example.com"},
                "method": "POST",
                "input_contract_ref": "tool_in:v1",
                "output_contract_ref": "tool_out:v1",
                "risk": "high",
                "side_effecting": True,
                "timeout_seconds": 10,
                "max_response_bytes": 65536,
                "rate_limit_per_minute": 60,
                "allowed_organizations": [ORG_SLUG],
            },
        },
        created_by="platform",
    )
    register_tool_definition(artifact=definition)
    binding = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_BINDING,
        logical_id="search_binding",
        body={
            "api_version": "agenthub/v1",
            "kind": "ToolBinding",
            "metadata": {"id": "search-binding.v1", "owner": "editor"},
            "spec": {
                "tool_ref": "search:v1",
                "allowed_input_fields": ["query"],
                "allowed_output_fields": ["status", "echo"],
                "approval": {
                    "required": True,
                },
            },
        },
        created_by="editor",
    )
    register_tool_binding(artifact=binding)
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="tool_workflow",
        body=empty_workflow(logical_id="tool_workflow"),
        created_by="editor",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                "workflow_definition", workflow.type, workflow.logical_id, workflow.version
            ),
            ArtifactRef("tool_binding.search", binding.type, binding.logical_id, 1),
        ],
        runtime_version="rt:9.0.0",
        created_by="editor",
    )
    consumer = Consumer.objects.create(
        organization=org, subject="client-1", name="Client", protocol=ConsumerProtocol.REST
    )
    invocation = request_tool_invocation(
        release=release,
        consumer=consumer,
        role="tool_binding.search",
        tool_input={"query": "hi"},
        idempotency_key="k1",
        consumer_capabilities=CAPS,
    )
    approval = ApprovalRequest.objects.get(invocation=invocation)
    return org, approval, invocation


def _operator(org: Organization, username: str, role: str) -> None:
    user = get_user_model().objects.create_user(username=username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    if role == Role.APPROVER:
        for scenario in Scenario.objects.filter(project__organization=org):
            ScenarioResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                scenario=scenario,
                responsibility=ScenarioResponsibility.APPROVER,
                assigned_by=user,
            )
    elif role == "runtime_operator":
        for scenario in Scenario.objects.filter(project__organization=org):
            ScenarioResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                scenario=scenario,
                responsibility=ScenarioResponsibility.RUNTIME_OPERATOR,
                assigned_by=user,
            )


@pytest.mark.django_db
def test_decide_command_approves_for_approver() -> None:
    org, approval, _ = _pending_approval()
    _operator(org, "op", Role.APPROVER)
    call_command(
        "decide_tool_approval", "--approval", str(approval.pk), "--actor", "op", "--approve"
    )
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.APPROVED


@pytest.mark.django_db
def test_decide_command_denied_for_non_approver() -> None:
    org, approval, _ = _pending_approval()
    _operator(org, "aud", Role.AUDITOR)
    with pytest.raises(CommandError, match="APPROVER_NOT_AUTHORIZED"):
        call_command(
            "decide_tool_approval", "--approval", str(approval.pk), "--actor", "aud", "--approve"
        )
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING


@pytest.mark.django_db
def test_decide_command_unknown_actor() -> None:
    _org, approval, _ = _pending_approval()
    with pytest.raises(CommandError, match="UNKNOWN_ACTOR"):
        call_command(
            "decide_tool_approval", "--approval", str(approval.pk), "--actor", "ghost", "--approve"
        )


@pytest.mark.django_db
def test_list_command_shows_pending(capsys: pytest.CaptureFixture[str]) -> None:
    _org, approval, _ = _pending_approval()
    call_command("list_tool_approvals", "--organization", ORG_SLUG)
    out = capsys.readouterr().out
    assert f"approval id={approval.pk}" in out


@pytest.mark.django_db
def test_cancel_command_cancels_invocation() -> None:
    org, _approval, invocation = _pending_approval()
    _operator(org, "op", "runtime_operator")
    call_command("cancel_tool_invocation", "--invocation", str(invocation.pk), "--actor", "op")
    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.CANCELLED


@pytest.mark.django_db
def test_approval_decision_increments_bounded_metric() -> None:
    from apps.observability.metrics import render_metrics

    org, approval, _ = _pending_approval()
    _operator(org, "op", Role.APPROVER)
    call_command(
        "decide_tool_approval", "--approval", str(approval.pk), "--actor", "op", "--approve"
    )
    output = render_metrics().decode("utf-8")
    assert "agenthub_tool_approvals_total" in output
    assert 'decision="approved"' in output
