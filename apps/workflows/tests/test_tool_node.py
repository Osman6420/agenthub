"""End-to-end workflow tool node: auto-approve, pause/resume, and reject-fails-closed."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioType
from apps.gateway.execution_context import issue_execution_context
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerProtocol
from apps.releases.compiler import ArtifactRef, compile_release
from apps.tenancy.models import Organization
from apps.tools.approvals import decide_approval
from apps.tools.models import ApprovalRequest, ToolInvocation, ToolInvocationStatus
from apps.tools.services import register_tool_binding, register_tool_definition
from apps.workflows.background_claims import claim_background_run
from apps.workflows.models import (
    Run,
    RunAwaitingKind,
    RunExecutionMode,
    WorkflowRun,
    WorkflowRunStatus,
)
from apps.workflows.run_waits import RunWaitError, resume_run_for_approval
from apps.workflows.services import request_workflow_run, resolve_release_workflow
from apps.workflows.tasks import execute_workflow_run
from apps.workflows.transitions import transition_run
from apps.workflows.unified_executor import execute_claimed_bounded_run

ORG_SLUG = "tool-flow-org"


def _workflow_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "tool_flow.v1"},
        "spec": {
            "input_node": "req",
            "nodes": [
                {"id": "req", "type": "input"},
                {
                    "id": "call",
                    "type": "tool",
                    "config": {
                        "binding_role": "tool_binding.search",
                        "input_key": "input",
                        "output_key": "output",
                    },
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "req", "to": "call"},
                {"from": "call", "to": "done"},
            ],
        },
    }


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
                "approver_roles": ["approver"],
                "self_approval_allowed": False,
            },
        },
    }


def _mapped_workflow_body() -> dict:
    """A tool node that selects its input and routes its output via typed mappings only."""
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "tool_flow.v1"},
        "spec": {
            "input_node": "req",
            "nodes": [
                {"id": "req", "type": "input"},
                {
                    "id": "call",
                    "type": "tool",
                    "config": {"binding_role": "tool_binding.search"},
                    "input_mapping": [{"from": "/input/query", "to": "/query"}],
                    "output_mapping": [
                        {"from": "/status", "to": "/output/status"},
                        {"from": "/status", "to": "/evidence/tool_status"},
                    ],
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "req", "to": "call"},
                {"from": "call", "to": "done"},
            ],
        },
    }


def _release_fixture(
    *, risk: str, side_effecting: bool, required: bool, workflow_body: dict | None = None
) -> tuple[Any, Consumer, dict]:
    """Build a release pinning one governed tool binding, plus an authorized consumer context."""
    org = Organization.objects.create(slug=ORG_SLUG, name="Tool Flow Org")
    project = AIProject.objects.create(organization=org, slug="ops", name="Ops")
    scenario = Scenario.objects.create(
        project=project,
        slug="flow",
        name="Flow",
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
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
    # An object contract reused for the tool output and the workflow output.
    contract = create_artifact_version(
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
    register_tool_definition(
        artifact=create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.TOOL_DEFINITION,
            logical_id="search",
            body=_definition_body(risk=risk, side_effecting=side_effecting),
            created_by="platform",
        )
    )
    binding = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_BINDING,
        logical_id="search_binding",
        body=_binding_body(required=required),
        created_by="editor",
    )
    register_tool_binding(artifact=binding)
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="tool_flow",
        body=workflow_body if workflow_body is not None else _workflow_body(),
        created_by="editor",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("output_contract", contract.type, "tool_out", 1),
            ArtifactRef("workflow_definition", workflow.type, "tool_flow", 1),
            ArtifactRef("tool_binding.search", binding.type, "search_binding", 1),
        ],
        runtime_version="rt:9.0.0",
        created_by="editor",
    )
    consumer = Consumer.objects.create(
        organization=org, subject="c1", name="Client", protocol=ConsumerProtocol.REST
    )
    capabilities: list[str] = [
        Capability.WORKFLOW_RUN,
        Capability.TOOL_CALL,
        Capability.TOOL_CALL_SIDE_EFFECT,
    ]
    context = issue_execution_context(
        organization_id=org.id,
        project_id=scenario.project_id,
        scenario_id=scenario.id,
        scenario_alias="flow",
        consumer_id=consumer.id,
        capabilities=capabilities,
        release_id=release.id,
        request_id="req-1",
    )
    return release, consumer, context


def _setup(
    *, risk: str, side_effecting: bool, required: bool, workflow_body: dict | None = None
) -> tuple[WorkflowRun, Consumer]:
    release, consumer, context = _release_fixture(
        risk=risk,
        side_effecting=side_effecting,
        required=required,
        workflow_body=workflow_body,
    )
    run, _created = request_workflow_run(
        release=release,
        consumer=consumer,
        workflow_version=resolve_release_workflow(release),
        execution_context=context,
        input_payload={"query": "hi"},
        idempotency_key="wf-key-1",
    )
    return run, consumer


@pytest.mark.django_db
def test_low_risk_tool_completes_without_pause() -> None:
    run, _consumer = _setup(risk="low", side_effecting=False, required=False)
    execute_workflow_run(run.id)
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.COMPLETED
    assert run.redacted_state["output"]["status"] == "[redacted]"


@pytest.mark.django_db
def test_tool_node_typed_input_and_output_mappings() -> None:
    run, _consumer = _setup(
        risk="low", side_effecting=False, required=False, workflow_body=_mapped_workflow_body()
    )
    execute_workflow_run(run.id)
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.COMPLETED
    # The tool output is routed into business namespaces by output_mapping (no legacy
    # ``output_key`` write path was used).
    assert run.redacted_state["evidence"]["tool_status"] == "[redacted]"
    assert run.redacted_state["output"] == {"status": "[redacted]"}


@pytest.mark.django_db
def test_high_risk_tool_pauses_then_resumes_to_completion() -> None:
    run, consumer = _setup(risk="high", side_effecting=True, required=True)

    execute_workflow_run(run.id)
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.WAITING_APPROVAL
    assert run.awaiting_node == "call"
    invocation = ToolInvocation.objects.get(consumer=consumer)
    assert invocation.status == ToolInvocationStatus.PENDING_APPROVAL
    approval = ApprovalRequest.objects.get(invocation=invocation)

    decide_approval(
        approval_id=approval.pk,
        organization_id=consumer.organization_id,
        actor="operator-1",
        actor_roles=["approver"],
        approve=True,
    )

    # Resume (production does this automatically on the post-commit signal).
    execute_workflow_run(run.id)
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.COMPLETED
    assert run.awaiting_node == ""
    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.COMPLETED


@pytest.mark.django_db
def test_rejected_tool_fails_the_workflow() -> None:
    run, consumer = _setup(risk="high", side_effecting=True, required=True)
    execute_workflow_run(run.id)
    approval = ApprovalRequest.objects.get(invocation__consumer=consumer)
    decide_approval(
        approval_id=approval.pk,
        organization_id=consumer.organization_id,
        actor="operator-1",
        actor_roles=["approver"],
        approve=False,
    )
    execute_workflow_run(run.id)
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.FAILED
    assert run.error_code == "TOOL_REJECTED"


# --- Unified Run tool node (Phase 2.8 P3) ---------------------------------------------------------


def _unified_setup(
    *, risk: str, side_effecting: bool, required: bool, workflow_body: dict | None = None
) -> tuple[Run, Consumer]:
    """Build the same governed release as above, but drive it through the unified Run aggregate."""
    release, consumer, context = _release_fixture(
        risk=risk,
        side_effecting=side_effecting,
        required=required,
        workflow_body=workflow_body,
    )
    version = resolve_release_workflow(release)
    run = Run.objects.create(
        organization=consumer.organization,
        scenario=release.scenario,
        release=release,
        workflow_version=version,
        consumer=consumer,
        actor_id=consumer.subject,
        idempotency_key="unified-tool-1",
        compiled_checksum=version.checksum,
        compiler_version=version.compiler_version,
        execution_mode=RunExecutionMode.BACKGROUND,
        deadline_at=timezone.now() + timedelta(minutes=5),
        input_checksum="a" * 64,
        execution_context=context,
        redacted_state={"input": {"query": "hi"}},
    )
    transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=run.status,
        target_status="queued",
    )
    run.refresh_from_db()
    return run, consumer


def _defer_delivery(monkeypatch) -> list[tuple]:
    """Capture the redelivery instead of running it, so resume and execution are observed apart."""
    from apps.workflows import tasks

    sent: list[tuple] = []
    monkeypatch.setattr(
        tasks.execute_unified_background_run,
        "apply_async",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )
    return sent


def _execute_queued(run: Run):
    token = uuid4()
    claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
        lease_seconds=30,
    )
    return execute_claimed_bounded_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
    )


@pytest.mark.django_db
@override_settings(UNIFIED_BACKGROUND_EXECUTOR_ENABLED=True)
def test_unified_run_low_risk_tool_completes_and_projects_the_redacted_envelope() -> None:
    run, _consumer = _unified_setup(risk="low", side_effecting=False, required=False)

    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    # The node never sees raw tool output: the governed boundary redacts before projection.
    assert run.checkpoint["output"] == {"status": "[redacted]", "echo": {"query": "[redacted]"}}
    assert run.tool_call_count == 1
    assert "__resume_node" not in run.checkpoint


@pytest.mark.django_db
@override_settings(UNIFIED_BACKGROUND_EXECUTOR_ENABLED=True)
def test_unified_run_tool_node_honours_typed_input_and_output_mappings() -> None:
    run, _consumer = _unified_setup(
        risk="low", side_effecting=False, required=False, workflow_body=_mapped_workflow_body()
    )

    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    # Only the mapped destinations are written; ``echo`` is dropped because no mapping selects it.
    assert run.checkpoint["output"] == {"status": "[redacted]"}
    assert run.checkpoint["evidence"] == {"tool_status": "[redacted]"}


@pytest.mark.django_db
@override_settings(UNIFIED_BACKGROUND_EXECUTOR_ENABLED=True)
def test_unified_run_parks_on_approval_and_resumes_into_the_same_node(
    django_capture_on_commit_callbacks,
    monkeypatch,
) -> None:
    run, consumer = _unified_setup(risk="high", side_effecting=True, required=True)
    delivered = _defer_delivery(monkeypatch)

    paused = _execute_queued(run)
    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL
    invocation = ToolInvocation.objects.get(consumer=consumer)
    assert invocation.status == ToolInvocationStatus.PENDING_APPROVAL
    run.refresh_from_db()
    assert run.awaiting_kind == RunAwaitingKind.APPROVAL
    assert run.awaiting_reference == str(invocation.id)
    # The claim is released while parked, and the call is not billed until it actually runs.
    assert run.background_claim_token is None
    assert run.tool_call_count == 0
    # Re-entry targets the tool node itself, so the approved invocation replays by idempotency key.
    assert run.checkpoint["__resume_node"] == "call"

    with django_capture_on_commit_callbacks(execute=True):
        decide_approval(
            approval_id=ApprovalRequest.objects.get(invocation=invocation).pk,
            organization_id=consumer.organization_id,
            actor="operator-1",
            actor_roles=["approver"],
            approve=True,
        )
    # The post-commit receiver re-admits the parked Run without a resume token and redelivers it.
    run.refresh_from_db()
    assert run.status == "queued"
    assert run.awaiting_kind == ""
    assert len(delivered) == 1

    assert _execute_queued(run).status == WorkflowRunStatus.COMPLETED
    run.refresh_from_db()
    assert run.tool_call_count == 1
    assert run.checkpoint["output"]["status"] == "[redacted]"
    assert "__resume_node" not in run.checkpoint
    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.COMPLETED


@pytest.mark.django_db
@override_settings(UNIFIED_BACKGROUND_EXECUTOR_ENABLED=True)
def test_unified_run_fails_closed_when_the_tool_approval_is_rejected(
    django_capture_on_commit_callbacks,
    monkeypatch,
) -> None:
    run, consumer = _unified_setup(risk="high", side_effecting=True, required=True)
    _execute_queued(run)
    _defer_delivery(monkeypatch)

    with django_capture_on_commit_callbacks(execute=True):
        decide_approval(
            approval_id=ApprovalRequest.objects.get(invocation__consumer=consumer).pk,
            organization_id=consumer.organization_id,
            actor="operator-1",
            actor_roles=["approver"],
            approve=False,
        )
    run.refresh_from_db()
    assert run.status == "queued"

    assert _execute_queued(run).status == WorkflowRunStatus.FAILED
    run.refresh_from_db()
    assert run.error_code == "TOOL_REJECTED"
    assert run.tool_call_count == 0


@pytest.mark.django_db
@override_settings(UNIFIED_BACKGROUND_EXECUTOR_ENABLED=True)
def test_unified_run_approval_resume_requires_the_exact_parked_invocation() -> None:
    run, consumer = _unified_setup(risk="high", side_effecting=True, required=True)
    _execute_queued(run)
    invocation = ToolInvocation.objects.get(consumer=consumer)

    # A decision that does not correspond to the invocation this Run is parked on must not move it.
    with pytest.raises(RunWaitError, match="RUN_WAIT_NOT_FOUND"):
        resume_run_for_approval(
            organization_id=consumer.organization_id,
            run_id=run.id,
            invocation_id=invocation.id + 1,
        )
    # Nor may an undecided approval re-admit the Run.
    with pytest.raises(RunWaitError, match="RUN_WAIT_NOT_FOUND"):
        resume_run_for_approval(
            organization_id=consumer.organization_id,
            run_id=run.id,
            invocation_id=invocation.id,
        )
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.WAITING_APPROVAL
