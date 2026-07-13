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
        document_set_version_ids: list[int] | None = None,
        consumer_id: int | None = None,
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
        document_set_version_ids: list[int] | None = None,
        consumer_id: int | None = None,
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
        document_set_version_ids: list[int] | None = None,
        consumer_id: int | None = None,
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
        document_set_version_ids: list[int] | None = None,
        consumer_id: int | None = None,
    ) -> list[RetrievedChunk]:
        # P4 document-ACL path: when the release pins document-set versions, serve **only** from
        # their active per-IndexVersion stores (deny-by-default, tenant + RLS scoped). Otherwise
        # fall back to the legacy source-scoped Chunk table (backward compatible).
        if document_set_version_ids:
            return self._retrieve_acl(
                query=query,
                profile=profile,
                organization_id=organization_id,
                document_set_version_ids=document_set_version_ids,
                consumer_id=consumer_id,
            )
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

    def _retrieve_acl(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        document_set_version_ids: list[int],
        consumer_id: int | None,
    ) -> list[RetrievedChunk]:
        """Deny-by-default retrieval from pinned doc-set versions' active per-IndexVersion stores.

        Effective scope = tenant ``organization_id`` (app predicate **and** RLS backstop) ∩ pinned
        ``document_set_version_ids`` ∩ their **active** index versions ∩ non-tombstoned documents.
        No filter comes from the client. PostgreSQL-only (the stores are pgvector).
        """
        from django.db import connection

        if connection.vendor != "postgresql" or not document_set_version_ids or consumer_id is None:
            return []
        from apps.documents.models import (
            DocumentSetGrant,
            DocumentSetVersion,
            DocumentVersion,
            GrantPrincipalType,
        )
        from apps.identity.models import Consumer, ConsumerStatus
        from apps.ingestion import vector_store
        from apps.ingestion.embedding import get_embedding_provider
        from apps.ingestion.models import IndexStatus, IndexVersion

        # The authenticated consumer id comes from the signed execution context (or the durable
        # run's immutable consumer FK). A caller-provided subject is never trusted. Grants store
        # the stable database id as an opaque string so a subject/name change cannot widen access.
        if not Consumer.objects.filter(
            id=consumer_id,
            organization_id=organization_id,
            status=ConsumerStatus.ACTIVE,
        ).exists():
            return []
        authorized_set_ids = DocumentSetGrant.objects.filter(
            organization_id=organization_id,
            principal_type=GrantPrincipalType.CONSUMER,
            principal_ref=str(consumer_id),
            permission="retrieve",
        ).values_list("document_set_id", flat=True)
        authorized_version_ids = list(
            DocumentSetVersion.objects.filter(
                id__in=document_set_version_ids,
                organization_id=organization_id,
                document_set_id__in=authorized_set_ids,
            ).values_list("id", flat=True)
        )
        if not authorized_version_ids:
            return []

        top_k = min(max(int(profile.get("top_k", 5)), 1), 50) if profile else 5
        active_indexes = list(
            IndexVersion.objects.filter(
                organization_id=organization_id,
                document_set_version_id__in=authorized_version_ids,
                status=IndexStatus.ACTIVE,
                store_ready=True,
            ).select_related("embedding_profile")
        )
        if not active_indexes:
            return []
        provider = get_embedding_provider()
        scored: list[tuple[vector_store.VectorHit, int | None]] = []
        for index in active_indexes:
            embedding_profile = index.embedding_profile
            profile_id = str(embedding_profile.public_id) if embedding_profile is not None else None
            query_vector = provider.embed([query], profile_id=profile_id).vectors[0]
            for hit in vector_store.search(
                index, query_vector, organization_id=organization_id, top_k=top_k
            ):
                scored.append((hit, index.document_set_version_id))
        scored.sort(key=lambda item: item[0].score, reverse=True)
        scored = scored[:top_k]

        # Exclude tombstoned documents (soft-deleted content is immediately unservable).
        version_ids = [hit.document_version_id for hit, _ in scored if hit.document_version_id]
        live = {
            dv.id: dv
            for dv in DocumentVersion.objects.filter(
                id__in=version_ids,
                organization_id=organization_id,
                document__deleted_at__isnull=True,
            ).select_related("document")
        }
        results: list[RetrievedChunk] = []
        for hit, dsv_id in scored:
            version = live.get(hit.document_version_id) if hit.document_version_id else None
            if version is None:
                continue
            results.append(
                RetrievedChunk(
                    text=hit.text,
                    source_id=f"docset-version:{dsv_id}",
                    source_uri=version.document.logical_id,
                    title=version.document.title,
                    score=hit.score,
                )
            )
        return results


def get_retrieval_provider() -> RetrievalProvider:
    path = getattr(settings, "RUNTIME_RETRIEVAL_PROVIDER", "")
    if path:
        return import_string(path)()
    return StaticRetrievalProvider()
