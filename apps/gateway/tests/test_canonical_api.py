"""Canonical Responses, Chat and UUID Run API contract."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.catalog.lifecycle import activate_scenario, disable_scenario
from apps.catalog.models import LifecycleStatus
from apps.gateway.errors import ErrorCode
from apps.gateway.tests.conftest import Fixture
from apps.identity.models import (
    Consumer,
    ConsumerProtocol,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.tokens import create_token
from apps.observability.models import UsageEvent
from apps.tenancy.models import OrganizationMembership
from apps.workflows.models import Run, RunStatus


def _client(token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db(transaction=True)
def test_gateway_callability_follows_explicit_scenario_lifecycle(
    scenario_fixture: Fixture,
) -> None:
    user_model = get_user_model()
    manager = user_model.objects.create_user("lifecycle-manager", password="unused")  # noqa: S106
    membership = OrganizationMembership.objects.create(
        organization=scenario_fixture.organization, user=manager
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=scenario_fixture.organization,
        membership=membership,
        scenario=scenario_fixture.scenario,
        responsibility=ScenarioResponsibility.RELEASE_MANAGER,
        assigned_by=manager,
    )
    scenario_fixture.scenario.status = LifecycleStatus.DRAFT
    scenario_fixture.scenario.save(update_fields=["status", "updated_at"])
    client = _client(scenario_fixture.raw_token)

    denied = client.post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="lifecycle-denied",
    )
    assert denied.status_code == 403

    activate_scenario(scenario_fixture.scenario, actor=manager)
    allowed = client.post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="lifecycle-allowed",
    )
    assert allowed.status_code == 200

    disable_scenario(scenario_fixture.scenario, actor=manager)
    denied_again = client.post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="lifecycle-disabled",
    )
    assert denied_again.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_sync_responses_persists_run_events_usage_and_audit(
    scenario_fixture: Fixture,
) -> None:
    response = _client(scenario_fixture.raw_token).post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="responses-1",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    run = Run.objects.get(consumer=scenario_fixture.consumer, idempotency_key="responses-1")
    assert response["X-AgentHub-Run-Id"] == str(run.id)
    assert body["id"] == run.response_id
    assert body["id"].startswith("resp_")
    assert body["id"] != str(run.id)
    assert run.status == RunStatus.COMPLETED
    assert list(run.events.values_list("sequence", flat=True)) == list(
        range(1, run.events.count() + 1)
    )
    assert UsageEvent.objects.filter(consumer_id=scenario_fixture.consumer.id).exists()
    assert AuditEvent.objects.filter(
        resource_type="run",
        resource_id=str(run.id),
        action="gateway.unified_run_completed",
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_chat_adapter_uses_same_sync_run(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        "/v1/chat/completions",
        {
            "model": scenario_fixture.alias,
            "messages": [{"role": "user", "content": "hello"}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="chat-1",
    )
    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"
    run = Run.objects.get(idempotency_key="chat-1")
    assert run.status == RunStatus.COMPLETED
    assert response["X-AgentHub-Run-Id"] == str(run.id)


@pytest.mark.django_db(transaction=True)
def test_background_response_status_and_idempotent_cancel(
    scenario_fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async",
        lambda *_, **__: None,
    )
    client = _client(scenario_fixture.raw_token)
    admitted = client.post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello", "background": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY="background-1",
    )
    assert admitted.status_code == 202
    body = admitted.json()
    assert body["object"] == "response"
    assert body["status"] == "queued"
    run_id = body["metadata"]["run_id"]
    assert admitted["X-AgentHub-Run-Id"] == run_id

    status = client.get(f"/v1/runs/{run_id}")
    assert status.status_code == 200
    assert status.json()["status"] == RunStatus.QUEUED
    first = client.post(f"/v1/runs/{run_id}/cancel", {}, format="json")
    second = client.post(f"/v1/runs/{run_id}/cancel", {}, format="json")
    assert first.status_code == second.status_code == 200
    assert first.json()["cancellation_state"] == "requested"
    assert second.json()["status"] == first.json()["status"]


@pytest.mark.django_db(transaction=True)
def test_run_read_and_cancel_are_exact_consumer_scoped(
    scenario_fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async",
        lambda *_, **__: None,
    )
    admitted = _client(scenario_fixture.raw_token).post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello", "background": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY="scope-1",
    )
    run_id = admitted.json()["metadata"]["run_id"]
    foreign = Consumer.objects.create(
        organization=scenario_fixture.organization,
        subject="foreign-rest",
        name="Foreign REST",
        protocol=ConsumerProtocol.REST,
    )
    _, foreign_token = create_token(foreign, "foreign")
    foreign_client = _client(foreign_token)
    assert foreign_client.get(f"/v1/runs/{run_id}").status_code == 404
    assert foreign_client.post(f"/v1/runs/{run_id}/cancel", {}, format="json").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_binding_capability_validation_and_idempotency_fail_closed(
    scenario_fixture: Fixture,
) -> None:
    client = _client(scenario_fixture.raw_token)
    scenario_fixture.consumer.bindings.update(capabilities=[])
    denied = client.post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="denied-1",
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == ErrorCode.CAPABILITY_DENIED
    scenario_fixture.consumer.bindings.update(capabilities=["workflow_run"])

    first = client.post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="same-key",
    )
    replay = client.post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "hello"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="same-key",
    )
    conflict = client.post(
        "/v1/responses",
        {"model": scenario_fixture.alias, "input": "different"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="same-key",
    )
    assert first.status_code == replay.status_code == 200
    assert first["X-AgentHub-Run-Id"] == replay["X-AgentHub-Run-Id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == ErrorCode.IDEMPOTENCY_CONFLICT
    assert Run.objects.filter(consumer=scenario_fixture.consumer).count() == 1


@pytest.mark.django_db
def test_removed_routes_and_delete_cancellation_are_absent(scenario_fixture: Fixture) -> None:
    client = _client(scenario_fixture.raw_token)
    assert client.post("/v1/" + "query", {}, format="json").status_code == 404
    assert client.post("/v1/" + "invoke", {}, format="json").status_code == 404
    assert client.delete("/v1/runs/00000000-0000-0000-0000-000000000001").status_code == 405
