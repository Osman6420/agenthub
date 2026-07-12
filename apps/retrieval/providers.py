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


class PgvectorRetrievalProvider:
    """Cosine retrieval constrained by signed-context tenant and pinned indexes."""

    def retrieve(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        index_versions: list[int],
    ) -> list[RetrievedChunk]:
        if not index_versions:
            return []
        from pgvector.django import CosineDistance

        from apps.ingestion.models import Chunk, IndexStatus
        from apps.ingestion.pipeline import embed_deterministic

        top_k = min(max(int(profile.get("top_k", 5)), 1), 50)
        query_vector = embed_deterministic(query)
        rows = (
            Chunk.objects.filter(
                organization_id=organization_id,
                index_version_id__in=index_versions,
                index_version__status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
            )
            .select_related("document", "index_version__source")
            .annotate(distance=CosineDistance("embedding", query_vector))
            .order_by("distance")[:top_k]
        )
        return [
            RetrievedChunk(
                # This legacy path only serves source-scoped index versions; a P3 document-set
                # index version writes to its own per-IndexVersion store, not this Chunk table.
                text=row.text,
                source_id=row.index_version.source.slug if row.index_version.source else "",
                source_uri=row.document.source_uri,
                title=row.document.title,
                score=max(0.0, 1.0 - float(row.distance)),
            )
            for row in rows
        ]


def get_retrieval_provider() -> RetrievalProvider:
    path = getattr(settings, "RUNTIME_RETRIEVAL_PROVIDER", "")
    if path:
        return import_string(path)()
    return StaticRetrievalProvider()
