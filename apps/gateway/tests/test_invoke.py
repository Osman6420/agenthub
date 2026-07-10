"""Gateway invoke/query authorization, idempotency, and error-envelope behavior."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.gateway.errors import ErrorCode
from apps.gateway.tests.conftest import Fixture, build_scenario

INVOKE = "/v1/invoke"


def _client(token: str | None = None) -> APIClient:
    client = APIClient()
    if token:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _assert_envelope(body: dict, code: str) -> None:
    assert set(body["error"].keys()) == {
        "code",
        "message",
        "request_id",
        "retryable",
        "details",
    }
    assert body["error"]["code"] == code


@pytest.mark.django_db
def test_missing_token_returns_401() -> None:
    response = _client().post(
        INVOKE, {"scenario_alias": "x", "input": {"query": "hi"}}, format="json"
    )
    assert response.status_code == 401
    _assert_envelope(response.json(), ErrorCode.AUTHENTICATION_REQUIRED)


@pytest.mark.django_db
def test_invalid_token_returns_401() -> None:
    response = _client("not-a-real-token").post(
        INVOKE, {"scenario_alias": "x", "input": {"query": "hi"}}, format="json"
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_happy_path_returns_completed(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        INVOKE,
        {"scenario_alias": scenario_fixture.alias, "input": {"query": "hi"}},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["scenario_alias"] == scenario_fixture.alias
    assert body["release_id"] is not None
    assert isinstance(body["output"], dict)
    assert "answer" in body["output"]
    assert body["output"]["sources"] == []  # no retrieval index yet
    assert "usage" in body
    assert response["X-Request-ID"]


@pytest.mark.django_db
def test_unbound_alias_returns_403(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        INVOKE, {"scenario_alias": "some-other-alias", "input": {"query": "hi"}}, format="json"
    )
    assert response.status_code == 403
    _assert_envelope(response.json(), ErrorCode.SCENARIO_NOT_ALLOWED)


@pytest.mark.django_db
def test_missing_capability_returns_403() -> None:
    fx = build_scenario(capabilities=["workflow_run"])  # not 'query'
    response = _client(fx.raw_token).post(
        INVOKE, {"scenario_alias": fx.alias, "input": {"query": "hi"}}, format="json"
    )
    assert response.status_code == 403
    _assert_envelope(response.json(), ErrorCode.CAPABILITY_DENIED)


@pytest.mark.django_db
def test_raw_ids_do_not_grant_access(scenario_fixture: Fixture) -> None:
    # No scenario_alias, only raw ids -> rejected (routing is by bound alias only).
    response = _client(scenario_fixture.raw_token).post(
        INVOKE,
        {"project_id": 1, "release_id": 1, "input": {"query": "hi"}},
        format="json",
    )
    assert response.status_code == 400
    _assert_envelope(response.json(), ErrorCode.VALIDATION_ERROR)


@pytest.mark.django_db
def test_input_contract_violation_returns_400(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        INVOKE, {"scenario_alias": scenario_fixture.alias, "input": {}}, format="json"
    )
    assert response.status_code == 400
    _assert_envelope(response.json(), ErrorCode.INPUT_CONTRACT_VIOLATION)


@pytest.mark.django_db
def test_no_active_release_returns_503() -> None:
    fx = build_scenario(active_release=False)
    response = _client(fx.raw_token).post(
        INVOKE, {"scenario_alias": fx.alias, "input": {"query": "hi"}}, format="json"
    )
    assert response.status_code == 503
    _assert_envelope(response.json(), ErrorCode.RELEASE_NOT_AVAILABLE)


@pytest.mark.django_db
def test_idempotency_replay_and_conflict(scenario_fixture: Fixture) -> None:
    client = _client(scenario_fixture.raw_token)
    body = {"scenario_alias": scenario_fixture.alias, "input": {"query": "hi"}}

    first = client.post(INVOKE, body, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert first.status_code == 200
    # Same key + same body -> replay (still 200, same payload).
    replay = client.post(INVOKE, body, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert replay.status_code == 200
    assert replay.json()["request_id"] == first.json()["request_id"]

    # Same key + different body -> conflict.
    conflict = client.post(
        INVOKE,
        {"scenario_alias": scenario_fixture.alias, "input": {"query": "different"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k1",
    )
    assert conflict.status_code == 409
    _assert_envelope(conflict.json(), ErrorCode.IDEMPOTENCY_CONFLICT)


@pytest.mark.django_db
def test_query_facade(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        "/v1/query", {"scenario_alias": scenario_fixture.alias, "query": "hi"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


@pytest.mark.django_db
def test_run_status_not_found(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).get("/v1/runs/run_x")
    assert response.status_code == 404
    _assert_envelope(response.json(), ErrorCode.RUN_NOT_FOUND)
