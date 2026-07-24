from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.roles import Role
from apps.tenancy.models import OrganizationMembership
from apps.workflows.models import (
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowVersion,
    WorkflowWait,
    WorkflowWaitStatus,
)
from apps.workflows.tests.conftest import WorkflowFixture
from apps.workflows.waits import (
    WorkflowWaitError,
    create_wait,
    decide_human_task,
    reconcile_due_waits,
    resume_event,
)


def _run(fx: WorkflowFixture, key: str = "wait-run") -> WorkflowRun:
    return WorkflowRun.objects.create(
        organization=fx.organization,
        scenario=fx.scenario,
        release=fx.release,
        workflow_version=WorkflowVersion.objects.get(scenario=fx.scenario),
        consumer=fx.consumer,
        idempotency_key=key,
        input_checksum="0" * 64,
        execution_context={},
        redacted_state={"input": {"request": 1}},
        status=WorkflowRunStatus.RUNNING,
        deadline_at=timezone.now() + timedelta(hours=1),
    )


def _event_node() -> dict:
    return {
        "id": "external",
        "type": "event_wait",
        "config": {
            "event_role": "evidence_ready",
            "payload_schema": {
                "type": "object",
                "properties": {"approved": {"type": "boolean"}},
                "required": ["approved"],
                "additionalProperties": False,
            },
            "timeout_seconds": 60,
        },
        "output_mapping": [{"from": "/payload/approved", "to": "/decisions/approved"}],
    }


@pytest.mark.django_db
def test_event_resume_is_one_time_schema_bound_and_redacted(
    workflow_fixture: WorkflowFixture,
) -> None:
    run = _run(workflow_fixture)
    wait, token = create_wait(run=run, node=_event_node(), state=run.redacted_state)
    assert len(token) == 36
    assert token == str(wait.public_id)
    assert wait.correlation_hash and wait.correlation_hash != token

    with pytest.raises(WorkflowWaitError, match="WAIT_PAYLOAD_INVALID"):
        resume_event(
            consumer=workflow_fixture.consumer,
            correlation=token,
            payload={"approved": True, "tenant": "forged"},
        )
    resumed = resume_event(
        consumer=workflow_fixture.consumer,
        correlation=token,
        payload={"approved": True},
    )
    assert resumed.status == WorkflowWaitStatus.RESUMED
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.QUEUED
    assert run.redacted_state["decisions"] == {"approved": True}
    with pytest.raises(WorkflowWaitError, match="WAIT_REPLAYED"):
        resume_event(
            consumer=workflow_fixture.consumer,
            correlation=token,
            payload={"approved": True},
        )
    audit_text = str(list(AuditEvent.objects.filter(resource_type="workflow_wait").values()))
    assert token not in audit_text
    assert "approved" not in audit_text
    assert AuditEvent.objects.filter(action="workflow.wait_resume", outcome="deny").exists()


@pytest.mark.django_db
def test_event_resume_denies_forgery_wrong_consumer_expiry_and_wrong_state(
    workflow_fixture: WorkflowFixture,
) -> None:
    run = _run(workflow_fixture, "wait-denials")
    wait, token = create_wait(run=run, node=_event_node(), state=run.redacted_state)
    with pytest.raises(WorkflowWaitError, match="WAIT_NOT_FOUND"):
        resume_event(
            consumer=workflow_fixture.consumer,
            correlation="00000000-0000-0000-0000-000000000000",
            payload={"approved": True},
        )
    other = Consumer.objects.create(
        organization=workflow_fixture.organization,
        subject="other-producer",
        name="Other producer",
        protocol=ConsumerProtocol.REST,
    )
    with pytest.raises(WorkflowWaitError, match="WAIT_NOT_FOUND"):
        resume_event(consumer=other, correlation=token, payload={"approved": True})

    wait.deadline_at = timezone.now() - timedelta(seconds=1)
    wait.save(update_fields=["deadline_at", "updated_at"])
    with pytest.raises(WorkflowWaitError, match="WAIT_EXPIRED"):
        resume_event(
            consumer=workflow_fixture.consumer,
            correlation=token,
            payload={"approved": True},
        )

    wait.status = WorkflowWaitStatus.PENDING
    wait.deadline_at = timezone.now() + timedelta(seconds=60)
    wait.save(update_fields=["status", "deadline_at", "updated_at"])
    run.status = WorkflowRunStatus.CANCELLED
    run.save(update_fields=["status", "updated_at"])
    with pytest.raises(WorkflowWaitError, match="WAIT_WRONG_STATE"):
        resume_event(
            consumer=workflow_fixture.consumer,
            correlation=token,
            payload={"approved": True},
        )


@pytest.mark.django_db
def test_due_timer_recovery_is_idempotent_and_cancel_wins(
    workflow_fixture: WorkflowFixture,
) -> None:
    run = _run(workflow_fixture, "timer")
    node = {"id": "pause", "type": "timer", "config": {"delay_seconds": 1}}
    wait, token = create_wait(run=run, node=node, state=run.redacted_state)
    assert token == ""
    WorkflowWait.objects.filter(pk=wait.pk).update(
        deadline_at=timezone.now() - timedelta(seconds=1)
    )
    assert reconcile_due_waits(limit=10) == [run.id]
    assert reconcile_due_waits(limit=10) == []
    wait.refresh_from_db()
    assert wait.status == WorkflowWaitStatus.RESUMED

    cancelled = _run(workflow_fixture, "timer-cancelled")
    cancelled_wait, _ = create_wait(run=cancelled, node=node, state=cancelled.redacted_state)
    WorkflowWait.objects.filter(pk=cancelled_wait.pk).update(
        deadline_at=timezone.now() - timedelta(seconds=1)
    )
    cancelled.status = WorkflowRunStatus.CANCELLED
    cancelled.save(update_fields=["status", "updated_at"])
    assert reconcile_due_waits(limit=10) == []
    cancelled.refresh_from_db()
    assert cancelled.status == WorkflowRunStatus.CANCELLED


@pytest.mark.django_db
def test_human_task_uses_server_roles_and_enforces_separation_of_duties(
    workflow_fixture: WorkflowFixture,
) -> None:
    run = _run(workflow_fixture, "human")
    node = {
        "id": "review",
        "type": "human_task",
        "config": {
            "allowed_decision_roles": [Role.APPROVER],
            "decision_schema": {
                "type": "object",
                "properties": {"result": {"type": "string", "enum": ["approve", "reject"]}},
                "required": ["result"],
                "additionalProperties": False,
            },
            "timeout_seconds": 60,
            "deny_self_decision": True,
            "escalation_role": Role.ORGANIZATION_ADMIN,
            "escalation_timeout_seconds": 120,
        },
        "output_mapping": [{"from": "/payload/result", "to": "/decisions/result"}],
    }
    wait, _ = create_wait(run=run, node=node, state=run.redacted_state)
    user_model = get_user_model()
    wrong = user_model.objects.create_user(username="auditor")
    OrganizationMembership.objects.create(
        organization=workflow_fixture.organization, user=wrong, role=Role.AUDITOR
    )
    with pytest.raises(WorkflowWaitError, match="WAIT_ROLE_DENIED"):
        decide_human_task(
            user_id=wrong.pk,
            organization_id=workflow_fixture.organization.pk,
            wait_id=str(wait.public_id),
            decision={"result": "approve"},
        )
    WorkflowWait.objects.filter(pk=wait.pk).update(
        deadline_at=timezone.now() - timedelta(seconds=1)
    )
    assert reconcile_due_waits(limit=10) == []
    wait.refresh_from_db()
    assert wait.status == WorkflowWaitStatus.PENDING
    assert wait.allowed_roles == [Role.ORGANIZATION_ADMIN]
    assert wait.escalated_at is not None
    # Reset the test fixture to prove the original approver happy path independently.
    wait.allowed_roles = [Role.APPROVER]
    wait.deadline_at = timezone.now() + timedelta(seconds=60)
    wait.save(update_fields=["allowed_roles", "deadline_at", "updated_at"])
    approver = user_model.objects.create_user(username="approver")
    OrganizationMembership.objects.create(
        organization=workflow_fixture.organization, user=approver, role=Role.APPROVER
    )
    decided = decide_human_task(
        user_id=approver.pk,
        organization_id=workflow_fixture.organization.pk,
        wait_id=str(wait.public_id),
        decision={"result": "approve"},
    )
    assert decided.status == WorkflowWaitStatus.RESUMED

    self_run = _run(workflow_fixture, "human-self")
    workflow_fixture.consumer.subject = "approver"
    workflow_fixture.consumer.save(update_fields=["subject", "updated_at"])
    self_wait, _ = create_wait(run=self_run, node=node, state=self_run.redacted_state)
    with pytest.raises(WorkflowWaitError, match="WAIT_SELF_DECISION_DENIED"):
        decide_human_task(
            user_id=approver.pk,
            organization_id=workflow_fixture.organization.pk,
            wait_id=str(self_wait.public_id),
            decision={"result": "approve"},
        )


@pytest.mark.django_db
def test_event_resume_endpoint_requires_auth_exact_envelope_and_owner(
    workflow_fixture: WorkflowFixture,
) -> None:
    run = _run(workflow_fixture, "gateway-event")
    _, token = create_wait(run=run, node=_event_node(), state=run.redacted_state)
    path = f"/v1/workflow-waits/{token}/resume"
    assert APIClient().post(path, {"payload": {"approved": True}}, format="json").status_code == 401
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {workflow_fixture.token}")
    status = client.get(f"/v1/runs/{run.id}")
    assert status.status_code == 200
    assert status.json()["event_correlation_id"] == token
    assert (
        client.post(path, {"payload": {"approved": True}, "tenant": 1}, format="json").status_code
        == 400
    )

    from apps.identity.tokens import create_token

    other = Consumer.objects.create(
        organization=workflow_fixture.organization,
        subject="foreign-caller",
        name="Foreign caller",
        protocol=ConsumerProtocol.REST,
    )
    _, other_token = create_token(consumer=other, name="other")
    foreign = APIClient()
    foreign.credentials(HTTP_AUTHORIZATION=f"Bearer {other_token}")
    assert foreign.post(path, {"payload": {"approved": True}}, format="json").status_code == 404


def test_compiler_accepts_wait_contracts_and_rejects_open_payload_schema() -> None:
    from apps.workflows.compiler import WorkflowCompileError, compile_workflow

    body: dict[str, Any] = {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "wait_flow.v1"},
        "spec": {
            "input_node": "start",
            "nodes": [
                {"id": "start", "type": "input"},
                _event_node(),
                {"id": "delay", "type": "timer", "config": {"delay_seconds": 5}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "start", "to": "external"},
                {"from": "external", "to": "delay"},
                {"from": "delay", "to": "done"},
            ],
        },
    }
    assert compile_workflow(body).graph["api_version"].endswith("/v5")
    body["spec"]["nodes"][1]["config"]["payload_schema"]["additionalProperties"] = True
    with pytest.raises(WorkflowCompileError, match="deny additionalProperties"):
        compile_workflow(body)
