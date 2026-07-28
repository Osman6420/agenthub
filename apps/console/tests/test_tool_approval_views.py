"""Console tool-approval views: role-gated, tenant-scoped, POST-only for decisions."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.roles import Role
from apps.releases.compiler import ArtifactRef, compile_release
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tools.approvals import request_tool_invocation
from apps.tools.models import ApprovalRequest, ApprovalStatus
from apps.tools.services import register_tool_binding, register_tool_definition
from apps.workflows.presets import empty_workflow

User = get_user_model()
CAPS: list[str] = [Capability.TOOL_CALL_SIDE_EFFECT]


def _pending_approval(org_slug: str = "tool-org") -> tuple[Organization, ApprovalRequest]:
    org = Organization.objects.create(slug=org_slug, name=org_slug)
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(project=project, slug="flow", name="Flow")
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="tool_in",
        body={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        created_by="e",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="tool_out",
        body={"type": "object", "properties": {"status": {"type": "string"}}},
        created_by="e",
    )
    register_tool_definition(
        artifact=create_artifact_version(
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
                    "allowed_organizations": [org_slug],
                },
            },
            created_by="platform",
        )
    )
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
                "allowed_output_fields": ["status"],
                "approval": {
                    "required": True,
                    "approver_roles": ["approver"],
                    "self_approval_allowed": False,
                },
            },
        },
        created_by="editor",
    )
    register_tool_binding(artifact=binding)
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="flow",
        body=empty_workflow(logical_id="flow"),
        created_by="editor",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("workflow_definition", ArtifactType.WORKFLOW_DEFINITION, "flow", 1),
            ArtifactRef("tool_binding.search", binding.type, binding.logical_id, 1),
        ],
        runtime_version="rt:9.0.0",
        created_by="editor",
    )
    consumer = Consumer.objects.create(
        organization=org, subject="c1", name="Client", protocol=ConsumerProtocol.REST
    )
    invocation = request_tool_invocation(
        release=release,
        consumer=consumer,
        role="tool_binding.search",
        tool_input={"query": "hi"},
        idempotency_key="k1",
        consumer_capabilities=CAPS,
        requested_by=consumer.subject,
    )
    return org, ApprovalRequest.objects.get(invocation=invocation)


def _login(client: Client, org: Organization, role: str, username: str = "op") -> None:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    client.force_login(user)


@pytest.mark.django_db
def test_approver_can_approve(client: Client) -> None:
    org, approval = _pending_approval()
    _login(client, org, Role.APPROVER)
    response = client.post(
        reverse("console:tool_approval_decide", args=[approval.pk]), {"decision": "approve"}
    )
    assert response.status_code == 302
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.APPROVED


@pytest.mark.django_db
def test_non_approver_is_denied_gracefully(client: Client) -> None:
    org, approval = _pending_approval()
    _login(client, org, Role.AUDITOR)
    response = client.post(
        reverse("console:tool_approval_decide", args=[approval.pk]), {"decision": "approve"}
    )
    assert response.status_code == 302  # denial surfaced as a message
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING


@pytest.mark.django_db
def test_cross_tenant_operator_forbidden(client: Client) -> None:
    org, approval = _pending_approval()
    other = Organization.objects.create(slug="other", name="Other")
    _login(client, other, Role.APPROVER, username="stranger")
    response = client.post(
        reverse("console:tool_approval_decide", args=[approval.pk]), {"decision": "approve"}
    )
    assert response.status_code == 403
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING


@pytest.mark.django_db
def test_decide_is_post_only(client: Client) -> None:
    org, approval = _pending_approval()
    _login(client, org, Role.APPROVER)
    response = client.get(reverse("console:tool_approval_decide", args=[approval.pk]))
    assert response.status_code == 405


@pytest.mark.django_db
def test_list_shows_pending_for_scope(client: Client) -> None:
    org, approval = _pending_approval()
    _login(client, org, Role.APPROVER)
    response = client.get(reverse("console:tool_approvals"))
    assert response.status_code == 200
    assert str(approval.pk) in response.content.decode("utf-8")
