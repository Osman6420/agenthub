"""Retrieval provider interface and the default (static) provider.

The real ACL-aware pgvector retriever arrives in Sprint 5 and plugs in via the
``RUNTIME_RETRIEVAL_PROVIDER`` setting without changing the runtime. Until then the
static provider returns no passages (so grounding-required scenarios fall back).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from django.utils.module_loading import import_string

from apps.retrieval.types import RetrievedChunk


@runtime_checkable
class RetrievalProvider(Protocol):
    def retrieve(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        index_versions: list[int],
    ) -> list[RetrievedChunk]: ...


class StaticRetrievalProvider:
    """Returns a fixed list of chunks (empty by default). Useful for tests/dev."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self._chunks = list(chunks or [])

    def retrieve(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        index_versions: list[int],
    ) -> list[RetrievedChunk]:
        top_k = int(profile.get("top_k", len(self._chunks))) if profile else len(self._chunks)
        ranked = sorted(self._chunks, key=lambda c: c.score, reverse=True)
        return ranked[:top_k]


class DemoRetrievalProvider:
    """Dev-only provider returning a single canned passage.

    Lets the governed pipeline produce a grounded answer before the real pgvector
    retriever exists (Sprint 5). Never use in production.
    """

    def retrieve(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        index_versions: list[int],
    ) -> list[RetrievedChunk]:
        passage = "Iade sureci: urun tesliminden itibaren 14 gun icinde iade talebi olusturulur."
        return [
            RetrievedChunk(
                text=passage,
                source_id="mcm_content",
                source_uri="https://kurum.example/iade",
                title="Iade Politikasi",
                score=0.82,
            )
        ]


def get_retrieval_provider() -> RetrievalProvider:
    path = getattr(settings, "RUNTIME_RETRIEVAL_PROVIDER", "")
    if path:
        return import_string(path)()
    return StaticRetrievalProvider()
