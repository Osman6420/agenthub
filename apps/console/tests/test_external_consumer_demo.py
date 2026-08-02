from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import override_settings

from apps.catalog.models import AIProject, Scenario
from apps.console.management.commands import seed_external_consumer_demo as demo
from apps.identity.models import ConsumerBinding
from apps.tenancy.models import Organization


class _WikipediaResponse:
    status = 200

    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode()

    def read(self, amount: int) -> bytes:
        return self.payload[:amount]


class _WikipediaConnection:
    def __init__(self, response: _WikipediaResponse) -> None:
        self.response = response
        self.request_args: tuple | None = None

    def request(self, *args: object, **kwargs: object) -> None:
        self.request_args = (args, kwargs)

    def getresponse(self) -> _WikipediaResponse:
        return self.response

    def close(self) -> None:
        return None


def test_wikipedia_fetch_uses_fixed_https_host_and_returns_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _WikipediaResponse(
        {
            "query": {
                "pages": [
                    {
                        "title": "İstanbul",
                        "extract": "İstanbul hakkında doğrulanabilir bilgi. " * 20,
                    }
                ]
            }
        }
    )
    connection = _WikipediaConnection(response)
    captured: dict[str, object] = {}

    def factory(host: str, port: int, timeout: int) -> _WikipediaConnection:
        captured.update(host=host, port=port, timeout=timeout)
        return connection

    monkeypatch.setattr(demo.http.client, "HTTPSConnection", factory)
    page = demo.fetch_wikipedia_extract(language="tr", title="İstanbul")

    assert captured == {"host": "tr.wikipedia.org", "port": 443, "timeout": 15}
    assert page["url"] == "https://tr.wikipedia.org/wiki/%C4%B0stanbul"
    assert page["title"] == "İstanbul"
    assert connection.request_args is not None
    assert connection.request_args[0][0] == "GET"


def test_wikipedia_fetch_rejects_unapproved_language() -> None:
    with pytest.raises(CommandError, match="language"):
        demo.fetch_wikipedia_extract(language="de", title="Berlin")


@override_settings(RUNTIME_MODEL_PROVIDER="", RUNTIME_EMBEDDING_PROVIDER="")
def test_bootstrap_fails_closed_without_live_model_provider() -> None:
    with pytest.raises(CommandError, match="OpenAI-compatible"):
        demo.Command().handle(credentials_file="unused")


@pytest.mark.django_db
def test_only_console_operator_receives_a_usable_password() -> None:
    demo.Command._ensure_users("local-demo-password")
    users = {
        user.username: user
        for user in get_user_model()
        .objects.filter(username__startswith="external-demo-")
        .order_by("username")
    }

    assert users[demo.OPERATOR_USERNAME].check_password("local-demo-password")
    assert not users[demo.EDITOR_USERNAME].has_usable_password()
    assert not users[demo.DOC_MANAGER_USERNAME].has_usable_password()
    assert not users[demo.PLATFORM_USERNAME].has_usable_password()


@pytest.mark.django_db
def test_consumers_are_bound_only_to_their_declared_scenarios() -> None:
    organization = Organization.objects.create(slug="external-demo", name="External")
    project = AIProject.objects.create(organization=organization, slug="showcase", name="Showcase")
    scenarios = {
        alias: Scenario.objects.create(
            organization=organization, project=project, slug=alias, name=alias
        )
        for alias in demo.SCENARIOS
    }

    consumers = demo.Command._ensure_consumers(organization, scenarios)

    for key, consumer in consumers.items():
        active_aliases = set(
            ConsumerBinding.objects.filter(consumer=consumer, status="active").values_list(
                "scenario__slug", flat=True
            )
        )
        assert active_aliases == set(demo.CONSUMERS[key]["scenarios"])
        assert all(binding.capabilities == ["workflow_run"] for binding in consumer.bindings.all())


@pytest.mark.django_db
def test_existing_valid_plaintext_token_is_reused() -> None:
    organization = Organization.objects.create(slug="token-demo", name="Token Demo")
    consumers = {}
    existing: dict[str, dict] = {"consumers": {}}
    for key in demo.CONSUMERS:
        consumer = demo.Consumer.objects.create(
            organization=organization,
            subject=f"subject-{key}",
            name=key,
            protocol="rest",
        )
        _record, raw = demo.create_token(consumer, "test")
        consumers[key] = consumer
        existing["consumers"][key] = {"token": raw}

    tokens = demo.Command._ensure_tokens(consumers, existing, rotate=False)

    assert tokens == {key: existing["consumers"][key]["token"] for key in demo.CONSUMERS}
    assert all(consumer.tokens.count() == 1 for consumer in consumers.values())
