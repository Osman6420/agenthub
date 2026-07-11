"""Gateway agent invoke (async 202), status/cancel dual dispatch, and authorization."""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from apps.agents.models import AgentRun, AgentRunStatus
from apps.agents.tasks import execute_agent_run
from apps.agents.tests.conftest import build_agent
from apps.gateway.errors import ErrorCode
from apps.identity.capabilities import Capability

pytestmark = pytest.mark.django_db

INVOKE = "/v1/invoke"


def _client(token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _invoke(fixture, token: str, *, key: str = "idem-1"):
    return _client(token).post(
        INVOKE,
        {"scenario_alias": fixture.alias, "input": {"query": "hello"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_agent_invoke_returns_202_with_uuid_run_id() -> None:
    fixture = build_agent()
    response = _invoke(fixture, fixture.token)
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    # The run id is the opaque UUID public id, never the numeric primary key.
    parsed = uuid.UUID(run_id)
    run = AgentRun.objects.get(public_id=parsed)
    assert str(run.public_id) == run_id
    assert run.status == AgentRunStatus.QUEUED


def test_agent_invoke_requires_idempotency_key() -> None:
    fixture = build_agent()
    response = _client(fixture.token).post(
        INVOKE,
        {"scenario_alias": fixture.alias, "input": {"query": "hello"}},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR


def test_agent_invoke_denied_without_capability() -> None:
    fixture = build_agent(capabilities=[Capability.QUERY])
    response = _invoke(fixture, fixture.token)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == ErrorCode.CAPABILITY_DENIED


def test_idempotent_replay_returns_same_run() -> None:
    fixture = build_agent()
    first = _invoke(fixture, fixture.token, key="same")
    second = _invoke(fixture, fixture.token, key="same")
    assert first.json()["run_id"] == second.json()["run_id"]
    assert AgentRun.objects.count() == 1


def test_idempotency_conflict_on_different_body() -> None:
    fixture = build_agent()
    _invoke(fixture, fixture.token, key="dup")
    conflict = _client(fixture.token).post(
        INVOKE,
        {"scenario_alias": fixture.alias, "input": {"query": "different"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="dup",
    )
    assert conflict.status_code == 409


def test_status_and_output_after_completion() -> None:
    fixture = build_agent()
    run_id = _invoke(fixture, fixture.token).json()["run_id"]
    run = AgentRun.objects.get(public_id=uuid.UUID(run_id))
    execute_agent_run(run.id)

    response = _client(fixture.token).get(f"/v1/runs/{run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["status"] == AgentRunStatus.COMPLETED
    assert body["output"]["answer"]


def test_cancel_via_delete() -> None:
    fixture = build_agent()
    run_id = _invoke(fixture, fixture.token).json()["run_id"]
    response = _client(fixture.token).delete(f"/v1/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == AgentRunStatus.CANCELLED


def test_cross_tenant_run_is_not_found() -> None:
    owner = build_agent(org_slug="owner-org")
    other = build_agent(org_slug="other-org")
    run_id = _invoke(owner, owner.token).json()["run_id"]
    # The other tenant's token must never resolve another tenant's run.
    response = _client(other.token).get(f"/v1/runs/{run_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == ErrorCode.RUN_NOT_FOUND


def test_unknown_uuid_run_is_not_found() -> None:
    fixture = build_agent()
    response = _client(fixture.token).get(f"/v1/runs/{uuid.uuid4()}")
    assert response.status_code == 404
