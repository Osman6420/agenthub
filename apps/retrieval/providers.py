"""Retrieval provider interface and the default (static) provider.

The real ACL-aware pgvector retriever arrives in Sprint 5 and plugs in via the
``RUNTIME_RETRIEVAL_PROVIDER`` setting without changing the runtime. Until then the
static provider returns no passages (so grounding-required scenarios fall back).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from django.db import transaction
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
        scenario_id: int | None = None,
        document_set_version_ids: list[int] | None = None,
        consumer_id: int | None = None,
        operator_test: bool = False,
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
        scenario_id: int | None = None,
        document_set_version_ids: list[int] | None = None,
        consumer_id: int | None = None,
        operator_test: bool = False,
    ) -> list[RetrievedChunk]:
        top_k = int(profile.get("top_k", len(self._chunks))) if profile else len(self._chunks)
        threshold = float(profile.get("score_threshold", 0.0)) if profile else 0.0
        ranked = sorted(
            (chunk for chunk in self._chunks if chunk.score >= threshold),
            key=lambda c: c.score,
            reverse=True,
        )
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
        scenario_id: int | None = None,
        document_set_version_ids: list[int] | None = None,
        consumer_id: int | None = None,
        operator_test: bool = False,
    ) -> list[RetrievedChunk]:
        passage = "Iade sureci: urun tesliminden itibaren 14 gun icinde iade talebi olusturulur."
        threshold = float(profile.get("score_threshold", 0.0)) if profile else 0.0
        if 0.82 < threshold:
            return []
        document_set_version_id = document_set_version_ids[0] if document_set_version_ids else None
        index_version_id = index_versions[0] if index_versions else None
        return [
            RetrievedChunk(
                text=passage,
                source_id="mcm_content",
                source_uri="https://kurum.example/iade",
                title="Iade Politikasi",
                score=0.82,
                vector_rank=1,
                vector_score=0.82,
                keyword_rank=1,
                keyword_score=0.82,
                fused_score=0.82,
                document_set_version_id=document_set_version_id,
                index_version_id=index_version_id,
                ordinal=0,
            )
        ]


class PgvectorRetrievalProvider:
    """Cosine retrieval constrained by signed-context tenant and pinned indexes."""

    @transaction.atomic
    def retrieve_prepared(
        self,
        *,
        query,
        profile,
        organization_id,
        scenario_id,
        consumer_id,
        release_id,
        run_id,
        selection_id=None,
    ) -> list[RetrievedChunk]:
        from apps.evaluations.prepared import prepared_run_generations
        from apps.evaluations.services import EvalError
        from apps.orchestration.resolver import resolve_bundle
        from apps.tenancy.context import set_tenant_context
        from apps.workflows.models import Run
        from apps.workflows.retrieval_selection import read_active_selection

        set_tenant_context(organization_id)
        run = (
            Run.objects.select_related("release")
            .filter(
                pk=run_id,
                organization_id=organization_id,
                scenario_id=scenario_id,
                consumer_id=consumer_id,
                release_id=release_id,
                prepared_evaluation__isnull=False,
            )
            .first()
        )
        if run is None:
            raise EvalError("PREPARED_EVALUATION_RUN_INVALID")
        pins = prepared_run_generations(run)
        version_ids = tuple(p.document_set_version_id for p in pins)
        index_ids = tuple(p.index_version_id for p in pins)
        if resolve_bundle(run.release).data_selection == "active_generation":
            if selection_id is None:
                raise EvalError("RETRIEVAL_SELECTION_REQUIRED")
            selected = read_active_selection(
                organization_id=organization_id,
                run_id=run.pk,
                release_id=release_id,
                consumer_id=consumer_id,
                selection_id=selection_id,
                query=query,
                profile=profile,
            )
            if set(
                zip(selected.document_set_version_ids, selected.index_version_ids, strict=True)
            ) != set(zip(version_ids, index_ids, strict=True)):
                raise EvalError("PREPARED_EVALUATION_SELECTION_INVALID")
        elif selection_id is not None:
            raise EvalError("PREPARED_EVALUATION_SELECTION_INVALID")
        return self._retrieve_acl(
            query=query,
            profile=profile,
            organization_id=organization_id,
            scenario_id=scenario_id,
            consumer_id=consumer_id,
            document_set_version_ids=list(version_ids),
            selected_index_version_ids=index_ids,
            prepared_run=run,
        )

    @transaction.atomic
    def retrieve_selected(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        scenario_id: int,
        consumer_id: int,
        release_id: int,
        run_id: Any,
        selection_id: int,
    ) -> list[RetrievedChunk]:
        from apps.tenancy.context import set_tenant_context
        from apps.workflows.models import Run
        from apps.workflows.retrieval_selection import (
            RetrievalSelectionError,
            read_active_selection,
        )

        set_tenant_context(organization_id)
        if not Run.objects.filter(
            pk=run_id,
            organization_id=organization_id,
            scenario_id=scenario_id,
            consumer_id=consumer_id,
            release_id=release_id,
        ).exists():
            raise RetrievalSelectionError("RETRIEVAL_SELECTION_UNRESOLVED")
        selected = read_active_selection(
            organization_id=organization_id,
            run_id=run_id,
            release_id=release_id,
            consumer_id=consumer_id,
            selection_id=selection_id,
            query=query,
            profile=profile,
        )
        return self._retrieve_acl(
            query=query,
            profile=profile,
            organization_id=organization_id,
            scenario_id=scenario_id,
            consumer_id=consumer_id,
            document_set_version_ids=list(selected.document_set_version_ids),
            selected_index_version_ids=selected.index_version_ids,
        )

    def retrieve(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        index_versions: list[int],
        scenario_id: int | None = None,
        document_set_version_ids: list[int] | None = None,
        consumer_id: int | None = None,
        operator_test: bool = False,
    ) -> list[RetrievedChunk]:
        # P4 document-ACL path: when the release pins document-set versions, serve **only** from
        # their active per-IndexVersion stores (deny-by-default, tenant + RLS scoped). Otherwise
        # fall back to the legacy source-scoped Chunk table (backward compatible).
        if document_set_version_ids:
            return self._retrieve_acl(
                query=query,
                profile=profile,
                organization_id=organization_id,
                scenario_id=scenario_id,
                document_set_version_ids=document_set_version_ids,
                consumer_id=consumer_id,
                operator_test=operator_test,
            )
        if not index_versions:
            return []
        return self._retrieve_source_indexes(
            query=query,
            profile=profile,
            organization_id=organization_id,
            index_versions=index_versions,
        )

    @transaction.atomic
    def _retrieve_source_indexes(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        index_versions: list[int],
    ) -> list[RetrievedChunk]:
        """Keep the legacy source contract while each generation transitions independently."""
        from pgvector.django import CosineDistance

        from apps.ingestion.models import Chunk, IndexedDocument, IndexStatus, IndexVersion
        from apps.ingestion.pipeline import embed_deterministic
        from apps.ingestion.vector_store import search
        from apps.tenancy.context import set_tenant_context

        set_tenant_context(organization_id)
        top_k = min(max(int(profile.get("top_k", 5)), 1), 50)
        threshold = float(profile.get("score_threshold", 0.0)) if profile else 0.0
        query_vector = embed_deterministic(query)
        rows = (
            Chunk.objects.filter(
                organization_id=organization_id,
                index_version_id__in=index_versions,
                index_version__status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
                index_version__storage_layout="legacy",
            )
            .select_related("document", "index_version__source")
            .annotate(distance=CosineDistance("embedding", query_vector))
            .order_by("distance")[:top_k]
        )
        results = [
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
            if max(0.0, 1.0 - float(row.distance)) >= threshold
        ]
        for index in IndexVersion.objects.filter(
            organization_id=organization_id,
            pk__in=index_versions,
            source__isnull=False,
            storage_layout="shared_v1",
            storage_state="sealed",
            store_ready=True,
            status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
        ).select_related("source"):
            hits = search(index, query_vector, organization_id=organization_id, top_k=top_k)
            documents = {
                document.pk: document
                for document in IndexedDocument.objects.filter(
                    organization_id=organization_id,
                    index_version=index,
                    pk__in=[hit.indexed_document_id for hit in hits if hit.indexed_document_id],
                )
            }
            for hit in hits:
                document = (
                    documents.get(hit.indexed_document_id)
                    if hit.indexed_document_id is not None
                    else None
                )
                if document is not None and hit.score >= threshold:
                    results.append(
                        RetrievedChunk(
                            text=hit.text,
                            source_id=index.source.slug if index.source else "",
                            source_uri=document.source_uri,
                            title=document.title,
                            score=hit.score,
                        )
                    )
        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]

    def _retrieve_acl(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        organization_id: int,
        scenario_id: int | None,
        document_set_version_ids: list[int],
        consumer_id: int | None,
        operator_test: bool = False,
        selected_index_version_ids: tuple[int, ...] | None = None,
        prepared_run=None,
    ) -> list[RetrievedChunk]:
        """Deny-by-default retrieval from pinned doc-set versions' active per-IndexVersion stores.

        Effective scope = tenant ``organization_id`` (app predicate **and** RLS backstop) ∩ pinned
        ``document_set_version_ids`` ∩ their **active** index versions ∩ non-tombstoned documents.
        No filter comes from the client. PostgreSQL-only (the stores are pgvector).
        """
        from django.db import connection

        if connection.vendor != "postgresql" or not document_set_version_ids:
            return []
        from apps.documents.models import (
            DocumentSetGrant,
            DocumentSetVersion,
            DocumentVersion,
            GrantPrincipalType,
        )
        from apps.documents.retrieve_scope import live_consumer_scenario_grants
        from apps.identity.models import Consumer, ConsumerStatus
        from apps.ingestion import vector_store
        from apps.ingestion.embedding import get_embedding_provider
        from apps.ingestion.models import IndexStatus, IndexVersion

        prepared_index_ids = ()
        if prepared_run is not None:
            from apps.evaluations.prepared import prepared_run_generations
            from apps.evaluations.services import EvalError

            pins = prepared_run_generations(prepared_run)
            prepared_index_ids = tuple(p.index_version_id for p in pins)
            if (
                operator_test
                or prepared_run.organization_id != organization_id
                or prepared_run.scenario_id != scenario_id
                or prepared_run.consumer_id != consumer_id
                or set(prepared_index_ids) != set(selected_index_version_ids or ())
                or {p.document_set_version_id for p in pins} != set(document_set_version_ids)
            ):
                raise EvalError("PREPARED_EVALUATION_SCOPE_INVALID")

        # The authenticated consumer id comes from the signed execution context (or the durable
        # run's immutable consumer FK). A caller-provided subject is never trusted. Grants store
        # the stable database id as an opaque string so a subject/name change cannot widen access.
        if operator_test:
            # This path is reachable only through the evaluations service after an explicit
            # DOCUMENT_SET_OPERATIONS_MANAGE authorization decision. It deliberately does not
            # manufacture or reuse consumer grants.
            live_scenario_set_ids = list(
                DocumentSetVersion.objects.filter(
                    id__in=document_set_version_ids,
                    organization_id=organization_id,
                ).values_list("document_set_id", flat=True)
            )
        else:
            consumer = Consumer.objects.filter(
                id=consumer_id or 0,
                organization_id=organization_id,
                status=ConsumerStatus.ACTIVE,
                organization__status="active",
            ).first()
            if consumer is None:
                return []
            authorized_set_ids = list(
                DocumentSetGrant.objects.filter(
                    organization_id=organization_id,
                    principal_type=GrantPrincipalType.CONSUMER,
                    principal_ref=str(consumer_id),
                    permission="retrieve",
                ).values_list("document_set_id", flat=True)
            )
            if scenario_id is None:
                live_scenario_set_ids = authorized_set_ids
            else:
                live_scenario_set_ids = list(
                    live_consumer_scenario_grants(
                        consumer=consumer,
                        scenario_ids=[scenario_id],
                    ).values_list("document_set_id", flat=True)
                )
        authorized_version_ids = list(
            DocumentSetVersion.objects.filter(
                id__in=document_set_version_ids,
                organization_id=organization_id,
                document_set_id__in=live_scenario_set_ids,
            ).values_list("id", flat=True)
        )
        if not authorized_version_ids:
            return []

        top_k = min(max(int(profile.get("top_k", 5)), 1), 50) if profile else 5
        indexes = IndexVersion.objects.filter(
            organization_id=organization_id,
            document_set_version_id__in=authorized_version_ids,
            store_ready=True,
        )
        if selected_index_version_ids is None:
            indexes = indexes.filter(status=IndexStatus.ACTIVE)
        else:
            from django.db.models import Q

            indexes = indexes.filter(
                pk__in=selected_index_version_ids,
                status__in=[IndexStatus.ACTIVE, IndexStatus.SUPERSEDED]
                + ([IndexStatus.PROMOTABLE] if prepared_index_ids else []),
            ).filter(
                Q(storage_layout="legacy") | Q(storage_layout="shared_v1", storage_state="sealed")
            )
        active_indexes = list(indexes.select_related("embedding_profile"))
        if not active_indexes:
            return []
        mode = str(profile.get("mode", "vector")) if profile else "vector"
        if mode not in {"keyword", "vector", "hybrid"}:
            return []
        provider = get_embedding_provider() if mode in {"vector", "hybrid"} else None
        threshold = float(profile.get("score_threshold", 0.0)) if profile else 0.0
        candidate_limit = min(100, max(top_k, top_k * 4))
        query_vectors: dict[int, list[float]] = {}

        def collect_candidates(
            *,
            chunk_kinds: tuple[str, ...] | None,
            document_version_ids: list[int] | None,
            limit: int,
        ) -> list[dict[str, Any]]:
            candidates: dict[tuple[int, int | None, int, str], dict[str, Any]] = {}
            for index in active_indexes:
                embedding_profile = index.embedding_profile
                if provider is not None:
                    query_vector = query_vectors.get(int(index.pk))
                    if query_vector is None:
                        profile_id = (
                            str(embedding_profile.public_id)
                            if embedding_profile is not None
                            else None
                        )
                        query_vector = provider.embed([query], profile_id=profile_id).vectors[0]
                        query_vectors[int(index.pk)] = query_vector
                    vector_hits = vector_store.search(
                        index,
                        query_vector,
                        organization_id=organization_id,
                        top_k=limit,
                        document_version_ids=document_version_ids,
                        chunk_kinds=chunk_kinds,
                    )
                    for rank, vector_hit in enumerate(vector_hits, start=1):
                        key = (
                            int(index.pk),
                            vector_hit.document_version_id,
                            vector_hit.ordinal,
                            vector_hit.chunk_kind,
                        )
                        item = candidates.setdefault(
                            key,
                            {
                                "hit": vector_hit,
                                "document_set_version_id": index.document_set_version_id,
                            },
                        )
                        item["vector_rank"] = rank
                        item["vector_score"] = vector_hit.score
                if mode in {"keyword", "hybrid"}:
                    keyword_hits = vector_store.keyword_search(
                        index,
                        query,
                        organization_id=organization_id,
                        top_k=limit,
                        document_version_ids=document_version_ids,
                        chunk_kinds=chunk_kinds,
                    )
                    for rank, keyword_hit in enumerate(keyword_hits, start=1):
                        key = (
                            int(index.pk),
                            keyword_hit.document_version_id,
                            keyword_hit.ordinal,
                            keyword_hit.chunk_kind,
                        )
                        item = candidates.setdefault(
                            key,
                            {
                                "hit": keyword_hit,
                                "document_set_version_id": index.document_set_version_id,
                            },
                        )
                        item["keyword_rank"] = rank
                        item["keyword_score"] = keyword_hit.score

            rank_constant = 60.0
            vector_weight = float(profile.get("vector_weight", 0.5)) if profile else 0.5
            keyword_weight = float(profile.get("keyword_weight", 0.5)) if profile else 0.5
            for item in candidates.values():
                if mode == "vector":
                    item["score"] = float(item.get("vector_score", 0.0))
                elif mode == "keyword":
                    raw_keyword = float(item.get("keyword_score", 0.0))
                    item["score"] = raw_keyword / (1.0 + raw_keyword)
                else:
                    fused = 0.0
                    if item.get("vector_rank") is not None:
                        fused += vector_weight / (rank_constant + int(item["vector_rank"]))
                    if item.get("keyword_rank") is not None:
                        fused += keyword_weight / (rank_constant + int(item["keyword_rank"]))
                    item["score"] = fused * (rank_constant + 1.0)
                    item["fused_score"] = item["score"]
            return sorted(
                candidates.values(),
                key=lambda item: float(item["score"]),
                reverse=True,
            )

        summary_document_top_k = (
            min(max(int(profile.get("summary_document_top_k", 0)), 0), 50) if profile else 0
        )
        max_chunks_per_document = (
            min(max(int(profile.get("max_chunks_per_document", 3)), 1), 10)
            if summary_document_top_k
            else top_k
        )
        routing_scores: dict[int, float] = {}
        routed_document_ids: list[int] = []
        retrieval_stage = "direct"
        if summary_document_top_k:
            summary_candidates = collect_candidates(
                chunk_kinds=("summary",),
                document_version_ids=None,
                limit=min(100, max(summary_document_top_k, summary_document_top_k * 4)),
            )
            summary_version_ids = {
                int(item["hit"].document_version_id)
                for item in summary_candidates
                if item["hit"].document_version_id is not None
            }
            live_summary_ids = set(
                DocumentVersion.objects.filter(
                    id__in=summary_version_ids,
                    organization_id=organization_id,
                    document__deleted_at__isnull=True,
                ).values_list("id", flat=True)
            )
            for item in summary_candidates:
                document_version_id = item["hit"].document_version_id
                score = float(item["score"])
                if (
                    document_version_id is None
                    or document_version_id not in live_summary_ids
                    or document_version_id in routing_scores
                    or score < threshold
                ):
                    continue
                routed_document_ids.append(document_version_id)
                routing_scores[document_version_id] = score
                if len(routed_document_ids) >= summary_document_top_k:
                    break
            retrieval_stage = "summary_routed" if routed_document_ids else "summary_fallback"

        scored = collect_candidates(
            chunk_kinds=("content",) if summary_document_top_k else None,
            document_version_ids=routed_document_ids or None,
            limit=100 if routed_document_ids else candidate_limit,
        )

        # Exclude tombstoned documents before the final top-k/cap selection (soft-deleted content
        # is immediately unservable and cannot consume a result slot).
        version_ids = [
            item["hit"].document_version_id for item in scored if item["hit"].document_version_id
        ]
        live = {
            dv.id: dv
            for dv in DocumentVersion.objects.filter(
                id__in=version_ids,
                organization_id=organization_id,
                document__deleted_at__isnull=True,
            ).select_related("document")
        }
        results: list[RetrievedChunk] = []
        chunks_per_document: dict[int, int] = {}
        for item in scored:
            hit = item["hit"]
            dsv_id = item["document_set_version_id"]
            version = live.get(hit.document_version_id) if hit.document_version_id else None
            score = float(item["score"])
            if version is None or score < threshold:
                continue
            if (
                chunks_per_document.get(version.pk, 0) >= max_chunks_per_document
                and summary_document_top_k
            ):
                continue
            results.append(
                RetrievedChunk(
                    text=hit.text,
                    source_id=f"docset-version:{dsv_id}",
                    source_uri=version.document.logical_id,
                    title=version.document.title,
                    score=score,
                    chunk_kind=hit.chunk_kind,
                    vector_rank=item.get("vector_rank"),
                    vector_score=item.get("vector_score"),
                    keyword_rank=item.get("keyword_rank"),
                    keyword_score=item.get("keyword_score"),
                    fused_score=item.get("fused_score"),
                    document_routing_score=routing_scores.get(version.pk),
                    retrieval_stage=retrieval_stage,
                    document_version_id=version.pk,
                    document_set_version_id=dsv_id,
                    index_version_id=next(
                        (
                            int(index.pk)
                            for index in active_indexes
                            if index.document_set_version_id == dsv_id
                        ),
                        None,
                    ),
                    ordinal=hit.ordinal,
                )
            )
            chunks_per_document[version.pk] = chunks_per_document.get(version.pk, 0) + 1
            if len(results) >= top_k:
                break
        return results


def get_retrieval_provider() -> RetrievalProvider:
    path = getattr(settings, "RUNTIME_RETRIEVAL_PROVIDER", "")
    if path:
        return import_string(path)()
    return StaticRetrievalProvider()
