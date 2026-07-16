"""Contract and security tests for the bounded OpenAI-compatible ingress."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.agents.models import AgentRun
from apps.agents.tests.conftest import build_agent
from apps.audit.models import AuditEvent
from apps.gateway.errors import ErrorCode
from apps.gateway.openai_compat import MAX_MESSAGE_CHARS, MAX_MESSAGES, MAX_TOTAL_CHARS
from apps.gateway.tests.conftest import Fixture
from apps.identity.models import ConsumerProtocol
from apps.workflows.models import WorkflowRun
from apps.workflows.tests.conftest import WorkflowFixture, workflow_fixture  # noqa: F401

CHAT = "/v1/chat/completions"
RESPONSES = "/v1/responses"


def _client(token: str | None = None) -> APIClient:
    client = APIClient()
    if token:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _chat(alias: str, content: str = "Merhaba") -> dict[str, object]:
    return {"model": alias, "messages": [{"role": "user", "content": content}]}


@pytest.mark.django_db
def test_chat_completions_minimal_success(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        CHAT, _chat(scenario_fixture.alias), format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("chatcmpl_")
    assert body["object"] == "chat.completion"
    assert body["model"] == scenario_fixture.alias
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert isinstance(body["choices"][0]["message"]["content"], str)
    assert body["choices"][0]["finish_reason"] == "stop"
    assert set(body["usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}
    assert response["X-Request-ID"]


@pytest.mark.django_db
def test_responses_minimal_string_success(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        RESPONSES,
        {"model": scenario_fixture.alias, "input": "Merhaba"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("resp_")
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["model"] == scenario_fixture.alias
    assert body["output"][0]["content"][0]["type"] == "output_text"


@pytest.mark.django_db
def test_compatible_error_shape_and_alias_authorization(scenario_fixture: Fixture) -> None:
    missing = _client().post(CHAT, _chat(scenario_fixture.alias), format="json")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == ErrorCode.AUTHENTICATION_REQUIRED
    assert set(missing.json()["error"]) == {"message", "type", "param", "code"}

    foreign = _client(scenario_fixture.raw_token).post(CHAT, _chat("foreign-alias"), format="json")
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == ErrorCode.SCENARIO_NOT_ALLOWED


@pytest.mark.django_db
def test_https_rejects_mcp_credential(scenario_fixture: Fixture) -> None:
    scenario_fixture.consumer.protocol = ConsumerProtocol.MCP
    scenario_fixture.consumer.save(update_fields=["protocol"])

    response = _client(scenario_fixture.raw_token).post(
        CHAT, _chat(scenario_fixture.alias), format="json"
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == ErrorCode.CAPABILITY_DENIED
    event = AuditEvent.objects.get(action="gateway.openai.chat_completions")
    assert event.reason == "PROTOCOL_DENIED"


@pytest.mark.django_db
def test_request_content_length_is_bounded(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        CHAT,
        _chat(scenario_fixture.alias),
        format="json",
        CONTENT_LENGTH="1000001",
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert AuditEvent.objects.filter(
        action="gateway.openai.chat_completions",
        outcome="deny",
        reason=ErrorCode.VALIDATION_ERROR,
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stream", True),
        ("tools", []),
        ("response_format", {"type": "json_object"}),
        ("store", True),
    ],
)
def test_unsupported_governance_fields_are_rejected(
    scenario_fixture: Fixture, field: str, value: object
) -> None:
    request = _chat(scenario_fixture.alias)
    request[field] = value
    response = _client(scenario_fixture.raw_token).post(CHAT, request, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert response.json()["error"]["param"] == field


@pytest.mark.django_db
def test_history_role_and_bounds_are_enforced(scenario_fixture: Fixture) -> None:
    client = _client(scenario_fixture.raw_token)
    bad_role = client.post(
        CHAT,
        {
            "model": scenario_fixture.alias,
            "messages": [{"role": "tool", "content": "secret"}],
        },
        format="json",
    )
    assert bad_role.status_code == 400
    assert bad_role.json()["error"]["param"] == "messages.0.role"

    too_many = client.post(
        CHAT,
        {
            "model": scenario_fixture.alias,
            "messages": [
                {"role": "user", "content": str(index)} for index in range(MAX_MESSAGES + 1)
            ],
        },
        format="json",
    )
    assert too_many.status_code == 400

    too_long = client.post(
        CHAT,
        _chat(scenario_fixture.alias, "x" * (MAX_MESSAGE_CHARS + 1)),
        format="json",
    )
    assert too_long.status_code == 400

    total = client.post(
        CHAT,
        {
            "model": scenario_fixture.alias,
            "messages": [
                {"role": "user", "content": "x" * (MAX_TOTAL_CHARS // 4 + 1)} for _ in range(4)
            ],
        },
        format="json",
    )
    assert total.status_code == 400


@pytest.mark.django_db
def test_at_least_one_user_message_is_required(scenario_fixture: Fixture) -> None:
    response = _client(scenario_fixture.raw_token).post(
        CHAT,
        {
            "model": scenario_fixture.alias,
            "messages": [{"role": "system", "content": "Policy"}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["param"] == "messages"


@pytest.mark.django_db
def test_idempotency_replay_keeps_opaque_id_and_conflicts_across_body(
    scenario_fixture: Fixture,
) -> None:
    client = _client(scenario_fixture.raw_token)
    first = client.post(
        CHAT,
        _chat(scenario_fixture.alias, "one"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="openai-1",
    )
    replay = client.post(
        CHAT,
        _chat(scenario_fixture.alias, "one"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="openai-1",
    )
    conflict = client.post(
        CHAT,
        _chat(scenario_fixture.alias, "two"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="openai-1",
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == ErrorCode.IDEMPOTENCY_CONFLICT


@pytest.mark.django_db
def test_client_user_is_not_returned_or_authority(scenario_fixture: Fixture) -> None:
    marker = "private-user-marker"
    response = _client(scenario_fixture.raw_token).post(
        CHAT,
        {**_chat(scenario_fixture.alias), "user": marker},
        format="json",
    )
    assert response.status_code == 200
    assert marker not in response.content.decode()


@pytest.mark.django_db
def test_responses_background_queues_agent_and_requires_idempotency() -> None:
    fixture = build_agent()
    client = _client(fixture.token)
    request = {"model": fixture.alias, "input": "Do the task", "background": True}

    missing = client.post(RESPONSES, request, format="json")
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR

    accepted = client.post(
        RESPONSES,
        request,
        format="json",
        HTTP_IDEMPOTENCY_KEY="agent-response-1",
    )
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["object"] == "response"
    assert body["status"] == "queued"
    assert body["background"] is True
    assert body["metadata"]["run_id"]
    assert AgentRun.objects.filter(public_id=body["metadata"]["run_id"]).exists()


@pytest.mark.django_db
def test_chat_rejects_agent_and_responses_requires_background() -> None:
    fixture = build_agent()
    client = _client(fixture.token)

    chat = client.post(CHAT, _chat(fixture.alias), format="json")
    assert chat.status_code == 400
    assert chat.json()["error"]["param"] == "model"

    response = client.post(
        RESPONSES,
        {"model": fixture.alias, "input": "Do the task"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="agent-response-2",
    )
    assert response.status_code == 400
    assert response.json()["error"]["param"] == "background"


@pytest.mark.django_db
def test_responses_background_queues_workflow(
    workflow_fixture: WorkflowFixture,  # noqa: F811
) -> None:
    response = _client(workflow_fixture.token).post(
        RESPONSES,
        {"model": workflow_fixture.alias, "input": "Do the task", "background": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY="workflow-response-1",
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["background"] is True
    assert WorkflowRun.objects.filter(pk=body["metadata"]["run_id"]).exists()
