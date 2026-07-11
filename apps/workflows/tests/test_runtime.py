from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.workflows.models import WorkflowRun, WorkflowRunEvent, WorkflowRunStatus
from apps.workflows.runtime import (
    WorkflowRuntimeError,
    _validate_output_policy,
    run_workflow_candidate,
)
from apps.workflows.tasks import execute_workflow_run
from apps.workflows.tests.conftest import WorkflowFixture


def _client(token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db(transaction=True)
def test_async_gateway_run_status_redelivery_and_idempotency(
    workflow_fixture: WorkflowFixture,
) -> None:
    client = _client(workflow_fixture.token)
    body = {"scenario_alias": workflow_fixture.alias, "input": {"query": "private text"}}
    response = client.post("/v1/invoke", body, format="json", HTTP_IDEMPOTENCY_KEY="flow-1")
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    run = WorkflowRun.objects.get(pk=run_id)
    assert run.status in {WorkflowRunStatus.QUEUED, WorkflowRunStatus.COMPLETED}
    assert "private text" not in str(run.redacted_state)

    assert execute_workflow_run(int(run_id)) == WorkflowRunStatus.COMPLETED
    assert execute_workflow_run(int(run_id)) == WorkflowRunStatus.COMPLETED
    status = client.get(f"/v1/runs/{run_id}")
    assert status.status_code == 200
    assert status.json()["status"] == WorkflowRunStatus.COMPLETED
    assert status.json()["output"] == {"answer": "ok", "sources": []}
    assert WorkflowRunEvent.objects.filter(run_id=run_id, event_type="run_completed").count() == 1
    assert WorkflowRunEvent.objects.filter(run_id=run_id, event_type="node_completed").count() == 3

    replay = client.post("/v1/invoke", body, format="json", HTTP_IDEMPOTENCY_KEY="flow-1")
    assert replay.status_code == 202
    assert replay.json()["run_id"] == run_id
    assert WorkflowRun.objects.count() == 1

    conflict = client.post(
        "/v1/invoke",
        {"scenario_alias": workflow_fixture.alias, "input": {"query": "different"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="flow-1",
    )
    assert conflict.status_code == 409


@pytest.mark.django_db
def test_workflow_requires_capability_and_idempotency_key(
    workflow_fixture: WorkflowFixture,
) -> None:
    client = _client(workflow_fixture.token)
    missing = client.post(
        "/v1/invoke",
        {"scenario_alias": workflow_fixture.alias, "input": {"query": "x"}},
        format="json",
    )
    assert missing.status_code == 400
    workflow_fixture.consumer.bindings.update(capabilities=["query"])
    denied = client.post(
        "/v1/invoke",
        {"scenario_alias": workflow_fixture.alias, "input": {"query": "x"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="flow-2",
    )
    assert denied.status_code == 403


@pytest.mark.django_db
def test_status_and_cancel_are_consumer_scoped(workflow_fixture: WorkflowFixture) -> None:
    client = _client(workflow_fixture.token)
    response = client.post(
        "/v1/invoke",
        {"scenario_alias": workflow_fixture.alias, "input": {"query": "x"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="flow-cancel",
    )
    run_id = response.json()["run_id"]
    cancelled = client.delete(f"/v1/runs/{run_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == WorkflowRunStatus.CANCELLED

    from apps.identity.models import Consumer, ConsumerProtocol
    from apps.identity.tokens import create_token

    other = Consumer.objects.create(
        organization=workflow_fixture.organization,
        subject="other",
        name="Other",
        protocol=ConsumerProtocol.REST,
    )
    _, token = create_token(consumer=other, name="other")
    assert _client(token).get(f"/v1/runs/{run_id}").status_code == 404


@pytest.mark.django_db
def test_candidate_workflow_uses_isolated_eval_seam(workflow_fixture: WorkflowFixture) -> None:
    result = run_workflow_candidate(
        release=workflow_fixture.release,
        input_payload={"query": "confidential eval input"},
    )
    assert result.status == "completed"
    assert result.output == {"answer": "ok", "sources": []}
    assert result.metadata == {
        "workload_type": "workflow",
        "executed_nodes": ["request", "format", "done"],
    }


def test_workflow_output_policy_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.workflows.runtime.get_artifact_body_for_role",
        lambda release, role: {"output": {"citations": "required"}},
    )
    with pytest.raises(WorkflowRuntimeError, match="POLICY_VIOLATION"):
        _validate_output_policy(object(), {"answer": "ungrounded", "sources": []})


@pytest.mark.django_db
def test_stale_broker_message_for_missing_run_is_safe_noop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert execute_workflow_run(999_999) == "missing"
    assert "run does not exist" in caplog.text
