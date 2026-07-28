"""End-to-end document-ACL retrieval over promoted per-IndexVersion stores (P4.2/P4.4).

PostgreSQL-only (pgvector stores). Uses the deterministic embedder (64-dim) and the hermetic
in-memory object store, so no live egress or MinIO. Proves the deny-by-default predicate and the
cross-tenant / cross-set / tombstoned / not-yet-promoted negatives.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.documents import services as doc_services
from apps.documents import storage
from apps.documents.models import (
    Document,
    DocumentSetVersion,
    GrantPrincipalType,
    ScenarioDocumentSetGrant,
    ScenarioDocumentSetGrantStatus,
)
from apps.identity.models import Consumer, ConsumerProtocol
from apps.ingestion.embedding_services import grant_embedding_profile, register_embedding_profile
from apps.ingestion.models import EmbeddingProfile
from apps.ingestion.staged_build import build_staged_index, promote_staged_index
from apps.orchestration.providers import ModelResponse
from apps.retrieval.providers import PgvectorRetrievalProvider
from apps.tenancy.models import Organization

pg_only = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="pgvector store requires PostgreSQL"
)
pytestmark = [pytest.mark.django_db, pg_only]


@pytest.fixture(autouse=True)
def _memory_object_store(settings: object) -> Iterator[None]:
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"  # type: ignore[attr-defined]
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


def _profile(org: Organization) -> EmbeddingProfile:
    admin = get_user_model().objects.create_superuser(username=f"pa-{org.slug}", password=None)
    profile = register_embedding_profile(
        actor=admin,
        logical_id="det-embed",
        revision=1,
        provider="openai_compatible",
        scheme="https",
        host="embeddings.example.com",
        port=443,
        path="/v1/embeddings",
        model="det",
        secret_ref="secret:embed-token",  # noqa: S106
        dimensions=64,
        index_type="vector",
        normalize=True,
        distance_metric="cosine",
        timeout_seconds=30,
        max_response_bytes=5_000_000,
        max_batch_size=64,
    )
    grant_embedding_profile(actor=admin, organization=org, embedding_profile=profile)
    return profile


def _published_set(org: Organization, logical_id: str, texts: list[str]) -> DocumentSetVersion:
    doc_set = doc_services.create_document_set(
        organization=org, logical_id=logical_id, name=logical_id, actor="op"
    )
    version = doc_services.create_document_set_version(document_set=doc_set, actor="op")
    for i, text in enumerate(texts):
        dv = doc_services.upload_document(
            organization=org,
            logical_id=f"{logical_id}-doc-{i}",
            title=f"Doc {i}",
            mime_type="text/markdown",
            data=text.encode("utf-8"),
            actor="op",
            document_set_version=version,
        )
        doc_services.add_document_to_set_version(
            set_version=version, document_version=dv, actor="op"
        )
    doc_services.publish_document_set_version(set_version=version, actor="op")
    version.refresh_from_db()
    return version


def _build_and_promote(
    org: Organization, dsv: DocumentSetVersion, profile: EmbeddingProfile
) -> None:
    index = build_staged_index(document_set_version=dsv, embedding_profile=profile, actor="op")
    promote_staged_index(index, actor="op")


def _consumer(org: Organization, subject: str = "client") -> Consumer:
    return Consumer.objects.create(
        organization=org, subject=subject, name=subject, protocol=ConsumerProtocol.REST
    )


def _grant(consumer: Consumer, dsv: DocumentSetVersion) -> None:
    doc_services.grant_document_set(
        document_set=dsv.document_set,
        principal_type=GrantPrincipalType.CONSUMER,
        principal_ref=str(consumer.id),
        actor="op",
    )


def _retrieve(
    org: Organization,
    dsv_ids: list[int],
    query: str = "alpha policy",
    consumer: Consumer | None = None,
    scenario: Scenario | None = None,
    retrieval_profile: dict[str, object] | None = None,
) -> list:
    return PgvectorRetrievalProvider().retrieve(
        query=query,
        profile=retrieval_profile or {"mode": "vector", "top_k": 5},
        organization_id=org.id,
        index_versions=[],
        scenario_id=scenario.pk if scenario else None,
        document_set_version_ids=dsv_ids,
        consumer_id=consumer.id if consumer else None,
    )


def _scenario(org: Organization) -> Scenario:
    project = AIProject.objects.create(organization=org, slug="acl", name="ACL")
    return Scenario.objects.create(
        organization=org,
        project=project,
        slug="acl",
        name="ACL",
    )


def test_end_to_end_returns_bound_documents() -> None:
    org = Organization.objects.create(slug="a", name="A")
    profile = _profile(org)
    dsv = _published_set(org, "kb", ["alpha policy text", "beta shipping text"])
    _build_and_promote(org, dsv, profile)
    consumer = _consumer(org)
    _grant(consumer, dsv)
    hits = _retrieve(org, [dsv.id], query="alpha policy text", consumer=consumer)
    assert hits and any("alpha" in h.text for h in hits)
    assert all(h.source_id == f"docset-version:{dsv.id}" for h in hits)


def test_keyword_and_hybrid_share_acl_scope_and_expose_component_diagnostics() -> None:
    org = Organization.objects.create(slug="hybrid", name="Hybrid")
    embedding_profile = _profile(org)
    dsv = _published_set(
        org,
        "kb",
        ["alpha unique_keyword policy text", "beta shipping text"],
    )
    _build_and_promote(org, dsv, embedding_profile)
    consumer = _consumer(org)
    _grant(consumer, dsv)

    keyword_hits = _retrieve(
        org,
        [dsv.id],
        query="unique_keyword",
        consumer=consumer,
        retrieval_profile={
            "mode": "keyword",
            "top_k": 5,
            "score_threshold": 0.0,
        },
    )
    assert keyword_hits and "unique_keyword" in keyword_hits[0].text
    assert keyword_hits[0].keyword_rank == 1
    assert keyword_hits[0].keyword_score is not None
    assert keyword_hits[0].vector_score is None

    hybrid_hits = _retrieve(
        org,
        [dsv.id],
        query="unique_keyword",
        consumer=consumer,
        retrieval_profile={
            "mode": "hybrid",
            "top_k": 5,
            "score_threshold": 0.0,
            "vector_weight": 0.4,
            "keyword_weight": 0.6,
        },
    )
    assert hybrid_hits and hybrid_hits[0].fused_score == hybrid_hits[0].score
    assert hybrid_hits[0].keyword_rank is not None
    assert hybrid_hits[0].vector_rank is not None


def test_summary_routing_selects_documents_then_returns_only_source_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = Organization.objects.create(slug="summary-route", name="Summary Route")
    embedding_profile = _profile(org)
    dsv = _published_set(
        org,
        "kb",
        [
            "chosen-source " + ("route_token selected source evidence " * 80),
            "distractor-source route_token fallback_token excluded source evidence",
        ],
    )
    model = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.MODEL_PROFILE,
        logical_id="summary-model",
        body={"profile_id": str(uuid.uuid4())},
        created_by="manager",
    )
    prompt = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        logical_id="summary-prompt",
        body={"template": "Summarize the untrusted context."},
        created_by="manager",
    )

    class _SummaryProvider:
        def generate(self, **kwargs: object) -> ModelResponse:
            context = kwargs["context"]
            source = context[0].text  # type: ignore[index]
            if "chosen-source" in source:
                return ModelResponse(text="route_token selected document summary")
            return ModelResponse(text="unrelated document summary")

    monkeypatch.setattr(
        "apps.documents.summary_services.get_model_provider",
        lambda: _SummaryProvider(),
    )
    index = build_staged_index(
        document_set_version=dsv,
        embedding_profile=embedding_profile,
        summary_model_profile=model,
        summary_prompt_contract=prompt,
        actor="op",
    )
    promote_staged_index(index, actor="op")
    consumer = _consumer(org)
    _grant(consumer, dsv)

    hits = _retrieve(
        org,
        [dsv.id],
        query="route_token",
        consumer=consumer,
        retrieval_profile={
            "mode": "keyword",
            "top_k": 5,
            "score_threshold": 0.0,
            "summary_document_top_k": 1,
            "max_chunks_per_document": 2,
        },
    )

    assert hits
    assert len(hits) == 2
    assert {hit.title for hit in hits} == {"Doc 0"}
    assert all(hit.chunk_kind == "content" for hit in hits)
    assert all(hit.retrieval_stage == "summary_routed" for hit in hits)
    assert all(hit.document_routing_score is not None for hit in hits)
    assert all("summary" not in hit.text for hit in hits)

    fallback_hits = _retrieve(
        org,
        [dsv.id],
        query="fallback_token",
        consumer=consumer,
        retrieval_profile={
            "mode": "keyword",
            "top_k": 5,
            "score_threshold": 0.0,
            "summary_document_top_k": 1,
            "max_chunks_per_document": 2,
        },
    )
    assert fallback_hits
    assert {hit.title for hit in fallback_hits} == {"Doc 1"}
    assert all(hit.chunk_kind == "content" for hit in fallback_hits)
    assert all(hit.retrieval_stage == "summary_fallback" for hit in fallback_hits)
    assert all(hit.document_routing_score is None for hit in fallback_hits)


def test_live_scenario_grant_revocation_blocks_pinned_release_retrieval() -> None:
    org = Organization.objects.create(slug="live-grant", name="Live Grant")
    profile = _profile(org)
    dsv = _published_set(org, "kb", ["alpha policy text"])
    _build_and_promote(org, dsv, profile)
    consumer = _consumer(org)
    _grant(consumer, dsv)
    scenario = _scenario(org)
    manager = get_user_model().objects.create_user(username="live-manager", password=None)
    grant = ScenarioDocumentSetGrant.objects.create(
        organization=org,
        scenario=scenario,
        document_set=dsv.document_set,
        granted_by=manager,
        granted_at=timezone.now(),
    )

    assert _retrieve(org, [dsv.id], consumer=consumer, scenario=scenario)

    grant.status = ScenarioDocumentSetGrantStatus.REVOKED
    grant.revoked_by = manager
    grant.revoked_at = timezone.now()
    grant.save()

    assert _retrieve(org, [dsv.id], consumer=consumer, scenario=scenario) == []


def test_deny_by_default_when_not_promoted() -> None:
    org = Organization.objects.create(slug="a", name="A")
    profile = _profile(org)
    dsv = _published_set(org, "kb", ["alpha policy text"])
    consumer = _consumer(org)
    _grant(consumer, dsv)
    build_staged_index(
        document_set_version=dsv, embedding_profile=profile, actor="op"
    )  # staged only
    # A promotable (not active) index is never served — the serving guardrail.
    assert _retrieve(org, [dsv.id], consumer=consumer) == []


def test_no_pinned_versions_retrieves_nothing() -> None:
    org = Organization.objects.create(slug="a", name="A")
    assert _retrieve(org, [], consumer=_consumer(org)) == []


def test_cross_tenant_returns_nothing() -> None:
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    profile = _profile(org_a)
    dsv = _published_set(org_a, "kb", ["alpha policy text"])
    _build_and_promote(org_a, dsv, profile)
    consumer_b = _consumer(org_b)
    # Org B pins org A's document-set version: the tenant predicate yields no active index.
    assert _retrieve(org_b, [dsv.id], consumer=consumer_b) == []


def test_cross_set_is_excluded() -> None:
    org = Organization.objects.create(slug="a", name="A")
    profile = _profile(org)
    dsv1 = _published_set(org, "kb1", ["alpha policy text"])
    dsv2 = _published_set(org, "kb2", ["beta shipping text"])
    _build_and_promote(org, dsv1, profile)
    _build_and_promote(org, dsv2, profile)
    consumer = _consumer(org)
    _grant(consumer, dsv1)
    _grant(consumer, dsv2)
    hits = _retrieve(org, [dsv1.id], query="alpha policy text", consumer=consumer)
    assert hits and all(h.source_id == f"docset-version:{dsv1.id}" for h in hits)


def test_tombstoned_document_excluded() -> None:
    org = Organization.objects.create(slug="a", name="A")
    profile = _profile(org)
    dsv = _published_set(org, "kb", ["alpha policy text"])
    _build_and_promote(org, dsv, profile)
    consumer = _consumer(org)
    _grant(consumer, dsv)
    # Soft-delete the only document; it must immediately drop out of answers.
    doc = Document.objects.get(organization=org, logical_id="kb-doc-0")
    doc_services.soft_delete_document(doc, actor="op")
    assert _retrieve(org, [dsv.id], consumer=consumer) == []


def test_grant_is_required_and_is_consumer_specific() -> None:
    org = Organization.objects.create(slug="a", name="A")
    profile = _profile(org)
    dsv = _published_set(org, "kb", ["alpha policy text"])
    _build_and_promote(org, dsv, profile)
    allowed = _consumer(org, "allowed")
    denied = _consumer(org, "denied")
    _grant(allowed, dsv)

    assert _retrieve(org, [dsv.id], consumer=allowed)
    assert _retrieve(org, [dsv.id], consumer=denied) == []
    assert _retrieve(org, [dsv.id]) == []
