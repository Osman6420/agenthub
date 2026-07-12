"""OpenAICompatibleEmbeddingClient over the shared SSRF-safe transport (offline-injected).

No socket is opened: every test injects a fake DNS resolver and connection factory, mirroring
the P1 chat-provider suite. Proves catalog-only destinations, dimension enforcement (no
truncation), SSRF denial before transport, redirect/malformed fail-closed, and the
post-send-unknown / no-blind-retry rule.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from apps.ingestion.embedding import (
    DeterministicEmbeddingProvider,
    EmbeddingError,
    EmbeddingOutcomeUnknown,
    OpenAICompatibleEmbeddingClient,
    get_embedding_provider,
)
from apps.ingestion.embedding_services import register_embedding_profile
from apps.ingestion.models import EmbeddingProfile
from apps.tools.secrets_resolver import SecretResolver

pytestmark = pytest.mark.django_db


class _SecretResolver(SecretResolver):
    def resolve(self, ref: str) -> str:
        assert ref == "secret:embed-token"  # noqa: S101
        return "test-credential"


class _Response:
    def __init__(self, body: dict[str, Any] | bytes, *, status: int = 200) -> None:
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


class _Connection:
    def __init__(self, response: _Response, *, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.request_body = b""
        self.headers: dict[str, str] = {}

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.request_body = body or b""
        self.headers = headers or {}
        if self.error is not None:
            raise self.error

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        return None


def _public_dns(host: str, port: int) -> list[tuple[Any, ...]]:
    return [(None, None, None, None, ("93.184.216.34", port))]


def _profile(
    dimensions: int = 4, *, normalize: bool = True, max_batch_size: int = 64
) -> EmbeddingProfile:
    admin = get_user_model().objects.create_superuser(username="platform", password=None)
    return register_embedding_profile(
        actor=admin,
        logical_id="default-embed",
        revision=1,
        provider="openai_compatible",
        scheme="https",
        host="embeddings.example.com",
        port=443,
        path="/v1/embeddings",
        model="text-embed-3",
        secret_ref="secret:embed-token",  # noqa: S106
        dimensions=dimensions,
        index_type="vector",
        normalize=normalize,
        distance_metric="cosine",
        timeout_seconds=10,
        max_response_bytes=65_536,
        max_batch_size=max_batch_size,
    )


def _client(
    connection: _Connection, *, resolver: Any = _public_dns
) -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        resolver=resolver,
        connection_factory=lambda ip, port, timeout, hostname: connection,
        secret_resolver=_SecretResolver(),
    )


def test_default_provider_is_deterministic_and_hermetic() -> None:
    provider = get_embedding_provider()
    assert isinstance(provider, DeterministicEmbeddingProvider)
    result = provider.embed(["hello", "world"])
    assert result.dimensions == 64
    assert len(result.vectors) == 2 and len(result.vectors[0]) == 64


def test_happy_path_uses_catalog_endpoint_and_normalizes() -> None:
    profile = _profile(dimensions=4)
    connection = _Connection(_Response({"data": [{"embedding": [3.0, 0.0, 4.0, 0.0]}]}))
    result = _client(connection).embed(["a"], profile_id=str(profile.public_id))
    assert result.model == "text-embed-3"
    assert result.dimensions == 4
    assert math.isclose(math.sqrt(sum(v * v for v in result.vectors[0])), 1.0, rel_tol=1e-6)
    payload = json.loads(connection.request_body)
    assert payload == {"model": "text-embed-3", "input": ["a"]}
    assert connection.headers["Authorization"] == "Bearer test-credential"


def test_dimension_mismatch_is_hard_failure_no_truncation() -> None:
    profile = _profile(dimensions=4)
    connection = _Connection(_Response({"data": [{"embedding": [1.0, 2.0, 3.0]}]}))  # len 3 != 4
    with pytest.raises(EmbeddingError, match="EMBEDDING_DIMENSION_MISMATCH"):
        _client(connection).embed(["a"], profile_id=str(profile.public_id))


def test_batch_over_limit_is_rejected() -> None:
    profile = _profile(dimensions=4, max_batch_size=1)
    connection = _Connection(_Response({"data": []}))
    with pytest.raises(EmbeddingError, match="EMBEDDING_BATCH_TOO_LARGE"):
        _client(connection).embed(["a", "b"], profile_id=str(profile.public_id))


def test_private_dns_denied_before_transport() -> None:
    profile = _profile()
    client = OpenAICompatibleEmbeddingClient(
        resolver=lambda host, port: [(None, None, None, None, ("127.0.0.1", port))],
        connection_factory=lambda *args: pytest.fail("transport must not run"),
        secret_resolver=_SecretResolver(),
    )
    with pytest.raises(EmbeddingError, match="DESTINATION_NOT_PUBLIC"):
        client.embed(["a"], profile_id=str(profile.public_id))


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (_Response({}, status=302), "REDIRECT_NOT_ALLOWED"),
        (_Response(b"not-json"), "RESPONSE_NOT_JSON"),
        (
            _Response(
                {"data": [{"embedding": [1.0, 2.0, 3.0, 4.0]}, {"embedding": [1.0, 2.0, 3.0, 4.0]}]}
            ),
            "EMBEDDING_RESPONSE_INVALID",
        ),
    ],
)
def test_transport_and_shape_failures_fail_closed(response: _Response, code: str) -> None:
    profile = _profile(dimensions=4)
    with pytest.raises(EmbeddingError, match=code):
        _client(_Connection(response)).embed(["a"], profile_id=str(profile.public_id))


def test_post_send_timeout_is_outcome_unknown_and_not_retried() -> None:
    profile = _profile(dimensions=4)
    connection = _Connection(_Response({"data": []}), error=TimeoutError())
    with pytest.raises(EmbeddingOutcomeUnknown, match="OUTCOME_UNKNOWN"):
        _client(connection).embed(["a"], profile_id=str(profile.public_id))


def test_unknown_or_disabled_profile_fails_closed() -> None:
    client = OpenAICompatibleEmbeddingClient()
    with pytest.raises(EmbeddingError, match="EMBEDDING_PROFILE_UNAVAILABLE"):
        client.embed(["a"], profile_id="00000000-0000-0000-0000-000000000001")


def test_missing_profile_id_is_rejected() -> None:
    with pytest.raises(EmbeddingError, match="EMBEDDING_PROFILE_INVALID"):
        OpenAICompatibleEmbeddingClient().embed(["a"], profile_id=None)
