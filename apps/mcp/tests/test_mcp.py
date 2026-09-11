"""Canonical MCP Responses adapter and transport authorization."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.gateway.errors import ErrorCode
from apps.gateway.tests.conftest import Fixture, build_scenario
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.tokens import create_token
from apps.mcp.schemas import TOOLS
from apps.mcp.tests.conftest import McpFixture
from apps.workflows.models import Run, RunStatus

MCP = "/mcp/"


def _client(token: str | None = None) -> APIClient:
    client = APIClient()
    if token:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _call(arguments: dict[str, Any]) -> dict[str, Any]:
    return _rpc(
        "tools/call",
        {
            "name": "agenthub__responses",
            "arguments": arguments,
        },
    )


@pytest.mark.django_db
def test_mcp_requires_consumer_token() -> None:
    assert _client().post(MCP, _rpc("tools/list"), format="json").status_code == 401


@pytest.mark.django_db
def test_mcp_rejects_rest_credential() -> None:
    fixture = build_scenario()
    response = _client(fixture.raw_token).post(MCP, _rpc("tools/list"), format="json")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == -32001
    assert AuditEvent.objects.filter(action="mcp.protocol", reason="PROTOCOL_DENIED").exists()


@pytest.mark.django_db
def test_initialize_and_tool_schema_snapshot(scenario_fixture: McpFixture) -> None:
    client = _client(scenario_fixture.raw_token)
    initialized = client.post(MCP, _rpc("initialize"), format="json")
    assert initialized.status_code == 200
    assert initialized["MCP-Protocol-Version"] == initialized.json()["result"]["protocolVersion"]
    assert initialized.json()["result"]["serverInfo"]["name"] == "agenthub"

    listed = client.post(MCP, _rpc("tools/list"), format="json")
    assert [tool["name"] for tool in listed.json()["result"]["tools"]] == [
        "agenthub__responses",
        "agenthub__run_status",
    ]
    assert [tool["name"] for tool in TOOLS] == [
        "agenthub__responses",
        "agenthub__run_status",
        "agenthub__ingestion_status",
        "agenthub__retrieve_debug",
    ]


@pytest.mark.django_db(transaction=True)
def test_mcp_sync_responses_uses_canonical_run(scenario_fixture: McpFixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        MCP,
        _call(
            {
                "model": scenario_fixture.alias,
                "input": "hello",
                "idempotency_key": "mcp-sync-1",
            }
        ),
        format="json",
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["object"] == "response"
    assert structured["status"] == "completed"
    assert structured["transport"] == "mcp"
    run = Run.objects.get(consumer=scenario_fixture.consumer, idempotency_key="mcp-sync-1")
    assert run.status == RunStatus.COMPLETED
    assert structured["id"] == run.response_id
    assert run.events.exists()


@pytest.mark.django_db(transaction=True)
def test_mcp_background_and_status_are_consumer_scoped(
    scenario_fixture: McpFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async",
        lambda *_, **__: None,
    )
    client = _client(scenario_fixture.raw_token)
    response = client.post(
        MCP,
        _call(
            {
                "model": scenario_fixture.alias,
                "input": "hello",
                "background": True,
                "idempotency_key": "mcp-bg-1",
            }
        ),
        format="json",
    )
    structured = response.json()["result"]["structuredContent"]
    assert response.status_code == 200
    assert structured["status"] == "queued"
    run_id = structured["metadata"]["run_id"]

    status = client.post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__run_status",
                "arguments": {"run_id": run_id},
            },
        ),
        format="json",
    )
    assert status.status_code == 200
    assert status.json()["result"]["structuredContent"]["run_id"] == run_id

    foreign = Consumer.objects.create(
        organization=scenario_fixture.organization,
        subject="foreign-mcp",
        name="Foreign MCP",
        protocol=ConsumerProtocol.MCP,
    )
    _, foreign_token = create_token(foreign, "foreign")
    denied = _client(foreign_token).post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__run_status",
                "arguments": {"run_id": run_id},
            },
        ),
        format="json",
    )
    assert denied.status_code == 404


@pytest.mark.django_db
def test_mcp_alias_capability_and_schema_denials_are_safe(
    scenario_fixture: McpFixture,
) -> None:
    client = _client(scenario_fixture.raw_token)
    unbound = client.post(
        MCP,
        _call(
            {
                "model": "other",
                "input": "secret query",
                "idempotency_key": "deny-1",
            }
        ),
        format="json",
    )
    assert unbound.status_code == 403
    assert unbound.json()["result"]["structuredContent"]["error"]["code"] == (
        ErrorCode.SCENARIO_NOT_ALLOWED
    )
    assert "secret query" not in unbound.content.decode()

    scenario_fixture.consumer.bindings.update(capabilities=[])
    denied = client.post(
        MCP,
        _call(
            {
                "model": scenario_fixture.alias,
                "input": "hello",
                "idempotency_key": "deny-2",
            }
        ),
        format="json",
    )
    assert denied.status_code == 403
    assert denied.json()["result"]["structuredContent"]["error"]["code"] == (
        ErrorCode.CAPABILITY_DENIED
    )

    invalid = client.post(
        MCP,
        _call(
            {
                "model": scenario_fixture.alias,
                "input": "hello",
                "idempotency_key": "x" * 129,
                "release_id": 999,
            }
        ),
        format="json",
    )
    assert invalid.status_code == 400
    assert invalid.json()["result"]["isError"] is True


@pytest.mark.django_db
def test_retrieve_debug_requires_mcp_protocol_and_explicit_capability() -> None:
    fixture = build_scenario(capabilities=["workflow_run", "retrieve_debug"])
    response = _client(fixture.raw_token).post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__retrieve_debug",
                "arguments": {"scenario_alias": fixture.alias, "query": "secret query"},
            },
        ),
        format="json",
    )
    assert response.status_code == 403
    assert "secret query" not in response.content.decode()


@pytest.mark.django_db
def test_mcp_rejects_unapproved_origin_version_and_excessive_depth(
    scenario_fixture: Fixture,
) -> None:
    client = _client(scenario_fixture.raw_token)
    assert (
        client.post(
            MCP,
            _rpc("tools/list"),
            format="json",
            HTTP_ORIGIN="https://attacker.example",
        ).status_code
        == 403
    )
    assert (
        client.post(
            MCP,
            _rpc("tools/list"),
            format="json",
            HTTP_MCP_PROTOCOL_VERSION="1900-01-01",
        ).status_code
        == 400
    )
    nested: dict[str, Any] = {}
    cursor = nested
    for _ in range(20):
        cursor["x"] = {}
        cursor = cursor["x"]
    response = client.post(MCP, _rpc("tools/call", nested), format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


def test_tool_schema_is_immutable_snapshot_input() -> None:
    assert TOOLS == copy.deepcopy(TOOLS)
