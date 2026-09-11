from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

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


@pytest.mark.parametrize(
    "value",
    [
        "https://agenthub-web:8000",
        "http://user:password@agenthub-web:8000",
        "http://agenthub-web:8000/v1",
        "http://agenthub-web:8000?token=x",
    ],
)
def test_api_base_rejects_non_internal_origin_shapes(value: str) -> None:
    with pytest.raises(CommandError, match="api-base"):
        demo.Command._validate_api_base(value)


def test_api_base_accepts_cluster_service_origin() -> None:
    assert (
        demo.Command._validate_api_base("http://agenthub-web:8000/") == "http://agenthub-web:8000"
    )


@override_settings(
    RUNTIME_MODEL_PROVIDER="apps.orchestration.providers.OpenAICompatibleModelProvider",
    RUNTIME_EMBEDDING_PROVIDER="apps.ingestion.embedding.OpenAICompatibleEmbeddingClient",
)
def test_no_print_secrets_suppresses_operator_password_and_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = StringIO()
    command = demo.Command(stdout=output)
    opaque_a = "sensitive-value"
    opaque_b = "raw-value"
    payload = {"operator": {"password": opaque_a}, "consumers": {}}
    monkeypatch.setattr(command, "_provision", lambda **_kwargs: (payload, {"research": opaque_b}))
    monkeypatch.setattr(command, "_write_credentials", lambda *_args: None)

    command.handle(
        credentials_file=str(tmp_path / "credentials.json"),
        password=opaque_a,
        wikipedia_title="Istanbul",
        wikipedia_language="tr",
        refresh_wikipedia=False,
        rotate_tokens=False,
        no_print_secrets=True,
        model_profile_id="00000000-0000-0000-0000-000000000001",
        embedding_profile_id="00000000-0000-0000-0000-000000000002",
        api_base="http://agenthub-web:8000",
    )

    rendered = output.getvalue()
    assert opaque_a not in rendered
    assert opaque_b not in rendered


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
def test_organization_bootstrap_installs_tenant_scope_before_tenant_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = demo.Command._ensure_users("local-demo-password")
    scoped: list[int] = []
    monkeypatch.setattr(demo, "set_tenant_context", scoped.append)

    organization = demo.Command._ensure_organization(users)

    assert scoped == [organization.pk]
    assert organization.memberships.count() == 3


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


@pytest.mark.django_db
def test_active_generic_profiles_are_reused_and_embedding_is_granted() -> None:
    actor = get_user_model().objects.create_superuser(username="profile-actor", password=None)
    organization = Organization.objects.create(slug="profile-demo", name="Profile Demo")
    model = demo.ModelProfile.objects.create(
        logical_id="non-gemini-chat",
        revision=1,
        host="llm.example.com",
        model="chat-model",
        secret_ref="secret:primary",  # noqa: S106 - logical reference, not a credential
        created_by=actor.username,
    )
    embedding = demo.EmbeddingProfile.objects.create(
        logical_id="non-gemini-embedding",
        revision=1,
        host="embedding.example.com",
        model="embedding-model",
        secret_ref="secret:primary",  # noqa: S106 - logical reference, not a credential
        dimensions=1024,
        created_by=actor.username,
    )

    selected_model = demo.Command._ensure_model_profile(actor, profile_id=str(model.public_id))
    selected_embedding = demo.Command._ensure_embedding_profile(
        actor,
        organization,
        profile_id=str(embedding.public_id),
    )

    assert selected_model == model
    assert selected_embedding == embedding
    assert embedding.tenant_grants.filter(organization=organization).exists()
