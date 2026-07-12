"""Embedding providers: the deterministic default and an opt-in real egress client.

The real ``OpenAICompatibleEmbeddingClient`` is a profile-ID-only adapter over the **shared
SSRF-safe stdlib transport** (`apps.tools.egress` + `apps.tools.http_adapter`) — the same choke
point the P1 chat client uses (ADR-0005). No ``openai`` dependency is added. Destinations are
resolved from the platform ``EmbeddingProfile`` catalog; callers never supply a URL/host/scheme/
secret/TLS option. Post-send failures are ``outcome_unknown`` and are never blindly re-sent
(ADR-0002/0005) — the caller fails the chunk/build for controlled re-drive.

The deterministic provider remains the default (``RUNTIME_EMBEDDING_PROVIDER`` empty) so CI and
the ingestion pipeline stay hermetic and open no socket.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from django.utils.module_loading import import_string

from apps.ingestion.models import EmbeddingProfile, EmbeddingProfileStatus
from apps.ingestion.pipeline import embed_deterministic
from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterUncertain
from apps.tools.egress import DnsResolver, EgressDenied, validate_destination
from apps.tools.http_adapter import (
    ConnectionFactory,
    _default_connection_factory,
    perform_https_post,
)
from apps.tools.secrets_resolver import SecretResolutionError, SecretResolver, _secret_name


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimensions: int


class EmbeddingError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EmbeddingOutcomeUnknown(EmbeddingError):
    """A post-send failure: the request may have been processed; never blindly retried."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str], *, profile_id: str | None = None) -> EmbeddingResult: ...


class EmbeddingEnvSecretResolver:
    """Resolve embedding credentials from ``EMBEDDING_SECRET_*`` environment variables."""

    def resolve(self, ref: str) -> str:
        name = _secret_name(ref)
        key = "EMBEDDING_SECRET_" + name.upper().replace("-", "_").replace(".", "_")
        value = os.environ.get(key)
        if not value:
            raise SecretResolutionError("SECRET_UNAVAILABLE")
        return value


class DeterministicEmbeddingProvider:
    """64-dim deterministic embeddings; hermetic default (no network)."""

    def embed(self, texts: list[str], *, profile_id: str | None = None) -> EmbeddingResult:
        vectors = [embed_deterministic(text) for text in texts]
        return EmbeddingResult(vectors=vectors, model="deterministic", dimensions=64)


class OpenAICompatibleEmbeddingClient:
    """Bounded ``/v1/embeddings`` client over the ADR-0005 shared SSRF-safe transport."""

    def __init__(
        self,
        *,
        resolver: DnsResolver | None = None,
        connection_factory: ConnectionFactory | None = None,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        self._resolver = resolver
        self._connection_factory = connection_factory or _default_connection_factory
        self._secret_resolver = secret_resolver or EmbeddingEnvSecretResolver()

    def embed(self, texts: list[str], *, profile_id: str | None = None) -> EmbeddingResult:
        if not isinstance(profile_id, str) or not profile_id:
            raise EmbeddingError("EMBEDDING_PROFILE_INVALID")
        if not texts:
            return EmbeddingResult(vectors=[], model="", dimensions=0)
        try:
            profile = EmbeddingProfile.objects.get(
                public_id=profile_id, status=EmbeddingProfileStatus.ACTIVE
            )
        except (EmbeddingProfile.DoesNotExist, ValueError, TypeError) as exc:
            raise EmbeddingError("EMBEDDING_PROFILE_UNAVAILABLE") from exc
        if len(texts) > profile.max_batch_size:
            raise EmbeddingError("EMBEDDING_BATCH_TOO_LARGE")

        raw = self._call(profile, texts)
        vectors = self._parse(raw, profile, expected=len(texts))
        return EmbeddingResult(vectors=vectors, model=profile.model, dimensions=profile.dimensions)

    def _call(self, profile: EmbeddingProfile, texts: list[str]) -> dict[str, Any]:
        try:
            destination = validate_destination(
                {
                    "scheme": profile.scheme,
                    "host": profile.host,
                    "port": profile.port,
                    "path_prefix": profile.path,
                },
                resolver=self._resolver,
            )
            credential = self._secret_resolver.resolve(profile.secret_ref)
        except EgressDenied as exc:
            raise EmbeddingError(exc.code) from exc
        except SecretResolutionError as exc:
            raise EmbeddingError(exc.code) from exc

        payload = {"model": profile.model, "input": texts}
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        request = ToolAdapterRequest(
            protocol="http",
            method="POST",
            destination=destination,
            payload={},
            credential=credential,
            timeout_seconds=profile.timeout_seconds,
            max_response_bytes=profile.max_response_bytes,
        )
        headers = {
            "Host": destination.host,
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            raw = perform_https_post(
                self._connection_factory,
                request,
                path=destination.path_prefix,
                headers=headers,
                body=body,
            )
        except ToolAdapterUncertain as exc:
            raise EmbeddingOutcomeUnknown("OUTCOME_UNKNOWN") from exc
        except ToolAdapterError as exc:
            raise EmbeddingError(exc.code) from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise EmbeddingError("RESPONSE_NOT_JSON") from exc
        if not isinstance(parsed, dict):
            raise EmbeddingError("RESPONSE_NOT_OBJECT")
        return parsed

    def _parse(
        self, response: dict[str, Any], profile: EmbeddingProfile, *, expected: int
    ) -> list[list[float]]:
        data = response.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID")
        vectors: list[list[float]] = []
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingError("EMBEDDING_RESPONSE_INVALID")
            embedding = item.get("embedding")
            if not isinstance(embedding, list) or len(embedding) != profile.dimensions:
                # Dimension mismatch is a hard failure — never truncate/pad (ADR-0003).
                raise EmbeddingError("EMBEDDING_DIMENSION_MISMATCH")
            try:
                vector = [float(value) for value in embedding]
            except (TypeError, ValueError) as exc:
                raise EmbeddingError("EMBEDDING_RESPONSE_INVALID") from exc
            vectors.append(_normalize(vector) if profile.normalize else vector)
        return vectors


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def get_embedding_provider() -> EmbeddingProvider:
    path = getattr(settings, "RUNTIME_EMBEDDING_PROVIDER", "")
    if path:
        provider: EmbeddingProvider = import_string(path)()
        return provider
    return DeterministicEmbeddingProvider()
