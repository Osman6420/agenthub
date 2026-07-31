"""Approval lifecycle: request, decision (SoD/expiry/authz), and idempotent resume."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

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
from apps.releases.compiler import ArtifactRef, compile_release
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tools.adapters import ToolAdapterRequest, ToolAdapterResponse, ToolAdapterUncertain
from apps.tools.approvals import (
    ToolApprovalError,
    cancel_invocation,
    decide_approval,
    execute_invocation,
    request_tool_invocation,
)
from apps.tools.models import (
    ApprovalRequest,
    ApprovalStatus,
    ToolInvocation,
    ToolInvocationStatus,
)
from apps.tools.services import register_tool_binding, register_tool_definition
from apps.workflows.presets import empty_workflow

ORG_SLUG = "tool-org"
PUBLIC_IP = "93.184.216.34"
CAPS: list[str] = [Capability.TOOL_CALL, Capability.TOOL_CALL_SIDE_EFFECT]


def _public_resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    return [(2, 1, 6, "", (PUBLIC_IP, port))]


class _RecordingAdapter:
    def __init__(self, response: ToolAdapterResponse | None = None, *, uncertain: bool = False):
        self.calls: list[ToolAdapterRequest] = []
        self._response = response
        self._uncertain = uncertain

    def call(self, request: ToolAdapterRequest) -> ToolAdapterResponse:
        self.calls.append(request)
        if self._uncertain:
            raise ToolAdapterUncertain()
        return self._response or ToolAdapterResponse(200, {"status": "ok"})


def _definition_body(*, risk: str, side_effecting: bool) -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolDefinition",
        "metadata": {"id": "search.v1", "owner": "platform"},
        "spec": {
            "protocol": "http",
            "destination": {"scheme": "https", "host": "api.example.com"},
            "method": "POST",
            "input_contract_ref": "tool_in:v1",
            "output_contract_ref": "tool_out:v1",
            "risk": risk,
            "side_effecting": side_effecting,
            "timeout_seconds": 10,
            "max_response_bytes": 65536,
            "rate_limit_per_minute": 60,
            "allowed_organizations": [ORG_SLUG],
        },
    }


def _binding_body(*, required: bool) -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolBinding",
        "metadata": {"id": "search-binding.v1", "owner": "editor"},
        "spec": {
            "tool_ref": "search:v1",
            "allowed_input_fields": ["query"],
            "allowed_output_fields": ["status", "echo"],
            "approval": {
                "required": required,
            },
        },
    }


def _setup(*, risk: str, side_effecting: bool, required: bool):
    org = Organization.objects.create(slug=ORG_SLUG, name="Tool Org")
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
        created_by="editor",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="tool_out",
        body={
            "type": "object",
            "properties": {"status": {"type": "string"}, "echo": {"type": "object"}},
            "required": ["status"],
            "additionalProperties": True,
        },
        created_by="editor",
    )
    definition_artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_DEFINITION,
        logical_id="search",
        body=_definition_body(risk=risk, side_effecting=side_effecting),
        created_by="platform",
    )
    register_tool_definition(artifact=definition_artifact)
    binding_artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_BINDING,
        logical_id="search_binding",
        body=_binding_body(required=required),
        created_by="editor",
    )
    register_tool_binding(artifact=binding_artifact)
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
            ArtifactRef(
                "tool_binding.search", binding_artifact.type, binding_artifact.logical_id, 1
            ),
        ],
        runtime_version="rt:9.0.0",
        created_by="editor",
    )
    consumer = Consumer.objects.create(
        organization=org, subject="client-1", name="Client", protocol=ConsumerProtocol.REST
    )
    return release, consumer


def _operator(release, username: str = "operator-1", *, authorized: bool = True):
    user = get_user_model().objects.create_user(username=username)
    membership = OrganizationMembership.objects.create(
        organization=release.scenario.organization,
        user=user,
    )
    if authorized:
        ScenarioResponsibilityAssignment.objects.create(
            organization=release.scenario.organization,
            scenario=release.scenario,
            membership=membership,
            responsibility=ScenarioResponsibility.APPROVER,
            assigned_by=user,
        )
    return user


def _request(release, consumer, *, key="k1", tool_input=None, initiated_by_user=None):
    return request_tool_invocation(
        release=release,
        consumer=consumer,
        role="tool_binding.search",
        tool_input=tool_input or {"query": "hi"},
        idempotency_key=key,
        consumer_capabilities=CAPS,
        initiated_by_user=initiated_by_user,
    )


@pytest.mark.django_db
def test_low_risk_auto_approves_and_executes() -> None:
    release, consumer = _setup(risk="low", side_effecting=False, required=False)
    invocation = _request(release, consumer)
    assert invocation.status == ToolInvocationStatus.APPROVED
    assert not ApprovalRequest.objects.filter(invocation=invocation).exists()
    done = execute_invocation(
        invocation_id=invocation.pk,
        tool_input={"query": "hi"},
        consumer_capabilities=CAPS,
        dns_resolver=_public_resolver,
    )
    assert done.status == ToolInvocationStatus.COMPLETED
    assert done.redacted_output == {"status": "[redacted]", "echo": {"query": "[redacted]"}}


@pytest.mark.django_db
def test_high_risk_requires_approval_then_resumes() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    invocation = _request(release, consumer)
    assert invocation.status == ToolInvocationStatus.PENDING_APPROVAL
    approval = ApprovalRequest.objects.get(invocation=invocation)
    assert approval.status == ApprovalStatus.PENDING
    actor = _operator(release)

    decide_approval(
        approval_id=approval.pk,
        organization_id=consumer.organization_id,
        actor=actor,
        approve=True,
    )
    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.APPROVED
    done = execute_invocation(
        invocation_id=invocation.pk,
        tool_input={"query": "hi"},
        consumer_capabilities=CAPS,
        dns_resolver=_public_resolver,
    )
    assert done.status == ToolInvocationStatus.COMPLETED


@pytest.mark.django_db
def test_self_approval_is_forbidden() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    actor = _operator(release, consumer.subject)
    invocation = _request(release, consumer, initiated_by_user=actor)
    approval = ApprovalRequest.objects.get(invocation=invocation)
    with pytest.raises(ToolApprovalError, match="SELF_APPROVAL_FORBIDDEN"):
        decide_approval(
            approval_id=approval.pk,
            organization_id=consumer.organization_id,
            actor=actor,
            approve=True,
        )


@pytest.mark.django_db
def test_unauthorized_approver_is_denied() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    invocation = _request(release, consumer)
    approval = ApprovalRequest.objects.get(invocation=invocation)
    actor = _operator(release, authorized=False)
    with pytest.raises(ToolApprovalError, match="APPROVER_NOT_AUTHORIZED"):
        decide_approval(
            approval_id=approval.pk,
            organization_id=consumer.organization_id,
            actor=actor,
            approve=True,
        )


@pytest.mark.django_db
def test_expired_approval_is_denied_and_invocation_expires() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    invocation = _request(release, consumer)
    approval = ApprovalRequest.objects.get(invocation=invocation)
    approval.expires_at = timezone.now() - timedelta(seconds=1)
    approval.save(update_fields=["expires_at"])
    actor = _operator(release)
    with pytest.raises(ToolApprovalError, match="APPROVAL_EXPIRED"):
        decide_approval(
            approval_id=approval.pk,
            organization_id=consumer.organization_id,
            actor=actor,
            approve=True,
        )
    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.EXPIRED


@pytest.mark.django_db
def test_cross_tenant_decision_is_not_found() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    invocation = _request(release, consumer)
    approval = ApprovalRequest.objects.get(invocation=invocation)
    other = Organization.objects.create(slug="other", name="Other")
    actor = _operator(release)
    with pytest.raises(ToolApprovalError, match="APPROVAL_NOT_FOUND"):
        decide_approval(
            approval_id=approval.pk,
            organization_id=other.pk,
            actor=actor,
            approve=True,
        )


@pytest.mark.django_db
def test_idempotent_request_and_conflict() -> None:
    release, consumer = _setup(risk="low", side_effecting=False, required=False)
    first = _request(release, consumer, key="same")
    again = _request(release, consumer, key="same")
    assert first.pk == again.pk
    with pytest.raises(ToolApprovalError, match="IDEMPOTENCY_CONFLICT"):
        _request(release, consumer, key="same", tool_input={"query": "different"})


@pytest.mark.django_db
def test_input_swap_after_approval_is_denied() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    invocation = _request(release, consumer)
    approval = ApprovalRequest.objects.get(invocation=invocation)
    actor = _operator(release)
    decide_approval(
        approval_id=approval.pk,
        organization_id=consumer.organization_id,
        actor=actor,
        approve=True,
    )
    with pytest.raises(ToolApprovalError, match="REQUEST_CHECKSUM_MISMATCH"):
        execute_invocation(
            invocation_id=invocation.pk,
            tool_input={"query": "SWAPPED"},
            consumer_capabilities=CAPS,
            dns_resolver=_public_resolver,
        )
    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.FAILED


@pytest.mark.django_db
def test_execute_is_idempotent_and_never_reexecutes() -> None:
    release, consumer = _setup(risk="low", side_effecting=False, required=False)
    invocation = _request(release, consumer)
    adapter = _RecordingAdapter(ToolAdapterResponse(200, {"status": "ok"}))
    first = execute_invocation(
        invocation_id=invocation.pk,
        tool_input={"query": "hi"},
        consumer_capabilities=CAPS,
        adapter=adapter,
        dns_resolver=_public_resolver,
    )
    assert first.status == ToolInvocationStatus.COMPLETED
    second = execute_invocation(
        invocation_id=invocation.pk,
        tool_input={"query": "hi"},
        consumer_capabilities=CAPS,
        adapter=adapter,
        dns_resolver=_public_resolver,
    )
    assert second.status == ToolInvocationStatus.COMPLETED
    assert len(adapter.calls) == 1  # not re-executed


@pytest.mark.django_db
def test_uncertain_outcome_is_recorded_and_not_retried() -> None:
    release, consumer = _setup(risk="low", side_effecting=False, required=False)
    invocation = _request(release, consumer)
    adapter = _RecordingAdapter(uncertain=True)
    result = execute_invocation(
        invocation_id=invocation.pk,
        tool_input={"query": "hi"},
        consumer_capabilities=CAPS,
        adapter=adapter,
        dns_resolver=_public_resolver,
    )
    assert result.status == ToolInvocationStatus.OUTCOME_UNKNOWN
    retry = execute_invocation(
        invocation_id=invocation.pk,
        tool_input={"query": "hi"},
        consumer_capabilities=CAPS,
        adapter=adapter,
        dns_resolver=_public_resolver,
    )
    assert retry.status == ToolInvocationStatus.OUTCOME_UNKNOWN
    assert len(adapter.calls) == 1  # never retried


@pytest.mark.django_db
def test_rejected_invocation_does_not_execute() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    invocation = _request(release, consumer)
    approval = ApprovalRequest.objects.get(invocation=invocation)
    actor = _operator(release)
    decide_approval(
        approval_id=approval.pk,
        organization_id=consumer.organization_id,
        actor=actor,
        approve=False,
    )
    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.REJECTED
    adapter = _RecordingAdapter()
    result = execute_invocation(
        invocation_id=invocation.pk,
        tool_input={"query": "hi"},
        consumer_capabilities=CAPS,
        adapter=adapter,
        dns_resolver=_public_resolver,
    )
    assert result.status == ToolInvocationStatus.REJECTED
    assert adapter.calls == []


@pytest.mark.django_db
def test_capability_denied_at_request() -> None:
    release, consumer = _setup(risk="low", side_effecting=False, required=False)
    with pytest.raises(ToolApprovalError, match="CAPABILITY_DENIED"):
        request_tool_invocation(
            release=release,
            consumer=consumer,
            role="tool_binding.search",
            tool_input={"query": "hi"},
            idempotency_key="k1",
            consumer_capabilities=[],
        )
    assert ToolInvocation.objects.count() == 0


@pytest.mark.django_db
def test_cancel_pending_invocation() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    invocation = _request(release, consumer)
    actor = _operator(release)
    cancelled = cancel_invocation(
        invocation_id=invocation.pk,
        organization_id=consumer.organization_id,
        actor=actor,
    )
    assert cancelled.status == ToolInvocationStatus.CANCELLED
    approval = ApprovalRequest.objects.get(invocation=invocation)
    assert approval.status == ApprovalStatus.CANCELLED
