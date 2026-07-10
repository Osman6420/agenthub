from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.gateway.errors import ErrorCode
from apps.gateway.tests.conftest import Fixture, build_scenario
from apps.mcp.schemas import TOOLS
from apps.releases.models import ReleaseCanary, ReleaseStatus, ScenarioRelease

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


@pytest.mark.django_db
def test_mcp_requires_consumer_token() -> None:
    response = _client().post(MCP, _rpc("tools/list"), format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_initialize_and_tool_schema_snapshot(scenario_fixture: Fixture) -> None:
    client = _client(scenario_fixture.raw_token)
    initialized = client.post(MCP, _rpc("initialize"), format="json")
    assert initialized.status_code == 200
    assert initialized["MCP-Protocol-Version"] == initialized.json()["result"]["protocolVersion"]
    assert initialized.json()["result"]["serverInfo"]["name"] == "agenthub"

    listed = client.post(MCP, _rpc("tools/list"), format="json")
    assert listed.status_code == 200
    assert [tool["name"] for tool in listed.json()["result"]["tools"]] == [
        "agenthub__invoke",
        "agenthub__query",
        "agenthub__run_status",
    ]
    assert [tool["name"] for tool in TOOLS] == [
        "agenthub__invoke",
        "agenthub__query",
        "agenthub__run_status",
        "agenthub__ingestion_status",
        "agenthub__retrieve_debug",
    ]


@pytest.mark.django_db
def test_mcp_query_matches_rest_release_and_output(scenario_fixture: Fixture) -> None:
    rest = _client(scenario_fixture.raw_token).post(
        "/v1/query",
        {"scenario_alias": scenario_fixture.alias, "query": "hi"},
        format="json",
    )
    mcp = _client(scenario_fixture.raw_token).post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__query",
                "arguments": {"scenario_alias": scenario_fixture.alias, "query": "hi"},
            },
        ),
        format="json",
    )
    assert rest.status_code == mcp.status_code == 200
    result = mcp.json()["result"]
    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["release_id"] == rest.json()["release_id"]
    assert structured["output"] == rest.json()["output"]
    assert structured["transport"] == "mcp"


@pytest.mark.django_db
def test_mcp_and_rest_share_sprint6_canary_routing(scenario_fixture: Fixture) -> None:
    active = ScenarioRelease.objects.get(scenario=scenario_fixture.scenario, status="active")
    canary = ScenarioRelease.objects.create(
        scenario=scenario_fixture.scenario,
        status=ReleaseStatus.CANARY,
        runtime_version=active.runtime_version,
        manifest=active.manifest,
        artifact_manifest_sha256="c" * 64,
        created_by="test",
    )
    ReleaseCanary.objects.create(
        scenario=scenario_fixture.scenario,
        consumer=scenario_fixture.consumer,
        release=canary,
        expires_at=timezone.now() + timedelta(minutes=5),
        created_by="test",
    )

    rest = _client(scenario_fixture.raw_token).post(
        "/v1/query",
        {"scenario_alias": scenario_fixture.alias, "query": "hi"},
        format="json",
    )
    mcp = _client(scenario_fixture.raw_token).post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__query",
                "arguments": {"scenario_alias": scenario_fixture.alias, "query": "hi"},
            },
        ),
        format="json",
    )
    assert rest.status_code == mcp.status_code == 200
    assert rest.json()["release_id"] == canary.id
    assert mcp.json()["result"]["structuredContent"]["release_id"] == canary.id


@pytest.mark.django_db
def test_mcp_unbound_alias_and_missing_capability_are_denied(
    scenario_fixture: Fixture,
) -> None:
    client = _client(scenario_fixture.raw_token)
    response = client.post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__query",
                "arguments": {"scenario_alias": "other", "query": "hi"},
            },
        ),
        format="json",
    )
    assert response.status_code == 403
    error = response.json()["result"]["structuredContent"]["error"]
    assert error["code"] == ErrorCode.SCENARIO_NOT_ALLOWED

    scenario_fixture.consumer.bindings.update(capabilities=["workflow_run"])
    response = client.post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__query",
                "arguments": {"scenario_alias": scenario_fixture.alias, "query": "hi"},
            },
        ),
        format="json",
    )
    assert response.status_code == 403
    error = response.json()["result"]["structuredContent"]["error"]
    assert error["code"] == ErrorCode.CAPABILITY_DENIED


@pytest.mark.django_db
def test_mcp_rejects_unknown_fields_and_excessive_depth(scenario_fixture: Fixture) -> None:
    client = _client(scenario_fixture.raw_token)
    response = client.post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__query",
                "arguments": {
                    "scenario_alias": scenario_fixture.alias,
                    "query": "hi",
                    "release_id": 999,
                },
            },
        ),
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["result"]["isError"] is True

    nested: dict[str, Any] = {}
    cursor = nested
    for _ in range(20):
        cursor["x"] = {}
        cursor = cursor["x"]
    deep = _rpc("tools/call", {"name": "agenthub__query", "arguments": nested})
    response = client.post(MCP, deep, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


@pytest.mark.django_db
def test_retrieve_debug_requires_explicit_capability_and_mcp_consumer() -> None:
    fx = build_scenario(capabilities=["query", "retrieve_debug"])
    response = _client(fx.raw_token).post(
        MCP,
        _rpc(
            "tools/call",
            {
                "name": "agenthub__retrieve_debug",
                "arguments": {"scenario_alias": fx.alias, "query": "secret query"},
            },
        ),
        format="json",
    )
    assert response.status_code == 403
    assert "secret query" not in response.content.decode()


def test_tool_schema_is_immutable_snapshot_input() -> None:
    snapshot = copy.deepcopy(TOOLS)
    assert TOOLS == snapshot


@pytest.mark.django_db
def test_mcp_rejects_unapproved_browser_origin_and_protocol_version(
    scenario_fixture: Fixture,
) -> None:
    client = _client(scenario_fixture.raw_token)
    origin = client.post(
        MCP,
        _rpc("tools/list"),
        format="json",
        HTTP_ORIGIN="https://attacker.example",
    )
    assert origin.status_code == 403

    version = client.post(
        MCP,
        _rpc("tools/list"),
        format="json",
        HTTP_MCP_PROTOCOL_VERSION="1900-01-01",
    )
    assert version.status_code == 400
