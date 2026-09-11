"""Upgrade evidence with real vectors, partial batches and preserved lineage."""

import pytest
from django.db import connection

from apps.audit.models import AuditEvent
from apps.ingestion import vector_store
from apps.ingestion.models import Chunk, IndexedDocument, IndexVersion, SharedVectorChunk, Source
from apps.ingestion.shared_backfill import backfill_generation
from apps.ingestion.tests.test_shared_vector_storage import _managed_generations
from apps.ingestion.vector_store import VectorRow, VectorStoreError
from apps.tenancy.models import Organization

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="backfill requires PostgreSQL"),
]


def _legacy_managed(dimensions=64, representation="vector"):
    index, other, doc = _managed_generations("legacy", dimensions, representation)
    vector_store.provision_store(index)
    embedding = [0.1234567, 0.7654321] + [0.0] * (dimensions - 2)
    vector_store.write_chunks(
        index,
        [
            VectorRow(
                index.organization_id, doc.pk, ordinal, f"immutable policy {ordinal}", embedding
            )
            for ordinal in range(3)
        ],
    )
    index.status = "promotable"
    index.store_ready = True
    index.chunk_count = 3
    index.save(update_fields=["status", "store_ready", "chunk_count"])
    return index, other, doc


def _call(index, **kwargs):
    return backfill_generation(
        index_version_id=index.pk,
        organization_id=index.organization_id,
        actor="synthetic-migration-operator",
        **kwargs,
    )


@pytest.mark.parametrize("geometry", [(64, "vector"), (3072, "halfvec")])
def test_resumable_backfill_preserves_exact_vectors_and_switches_only_when_complete(geometry):
    index, _, doc = _legacy_managed(*geometry)
    legacy_name = vector_store.store_name(index)
    preview = _call(index)
    assert preview.remaining == 3 and not preview.switched
    assert not SharedVectorChunk.objects.exists()
    partial = _call(index, apply=True, batch_size=1)
    assert partial.copied == 1 and partial.remaining == 2 and not partial.verified
    index.refresh_from_db()
    assert index.storage_layout == "legacy"
    assert vector_store.exact_chunk_text(index, doc.pk, 2) == "immutable policy 2"
    finished = _call(index, apply=True)
    assert finished.copied == 2 and finished.remaining == 0
    assert finished.verified and finished.switched and len(finished.checksum) == 64
    index.refresh_from_db()
    assert index.storage_layout == "shared_v1" and index.storage_state == "sealed"
    assert vector_store.exact_chunk_text(index, doc.pk, 2) == "immutable policy 2"
    replay = _call(index, apply=True)
    assert replay.copied == 0 and replay.verified and not replay.switched
    assert replay.checksum == finished.checksum
    assert SharedVectorChunk.objects.filter(index_version=index).count() == 3
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [legacy_name])
        assert cursor.fetchone()[0] is not None
    event = AuditEvent.objects.filter(
        action="ingestion.shared_vector.backfill",
        reason="VERIFIED_AND_SWITCHED",
    ).get()
    assert "immutable policy" not in str(event.after)


def test_legacy_orm_chunks_keep_document_ids_and_implicit_geometry():
    from apps.retrieval.providers import PgvectorRetrievalProvider

    org = Organization.objects.create(slug="orm", name="ORM")
    source = Source.objects.create(organization=org, slug="orm", name="ORM", connector_type="https")
    index = IndexVersion.objects.create(
        organization=org,
        source=source,
        version=1,
        status="promotable",
        chunk_count=1,
    )
    doc = IndexedDocument.objects.create(
        organization=org,
        index_version=index,
        source_uri="synthetic:orm",
        checksum="a" * 64,
    )
    original = Chunk.objects.create(
        organization=org,
        index_version=index,
        document=doc,
        ordinal=0,
        text="legacy identity",
        embedding=[1.0] + [0.0] * 63,
    )
    provider = PgvectorRetrievalProvider()
    previous = provider.retrieve(
        query="legacy identity",
        profile={"top_k": 3},
        organization_id=org.pk,
        index_versions=[index.pk],
    )
    result = _call(index, apply=True)
    assert result.verified and result.switched
    index.refresh_from_db()
    assert (index.dimensions, index.index_type) == (64, "vector")
    copied = SharedVectorChunk.objects.get(index_version=index)
    assert copied.indexed_document_id == original.document_id
    assert copied.document_version_id is None and copied.text == original.text
    assert Chunk.objects.filter(pk=original.pk).exists()
    current = provider.retrieve(
        query="legacy identity",
        profile={"top_k": 3},
        organization_id=org.pk,
        index_versions=[index.pk],
    )
    assert current == previous


def test_busy_and_incomplete_generations_are_not_certified():
    index, busy, _ = _legacy_managed()
    with pytest.raises(VectorStoreError, match="SHARED_BACKFILL_GENERATION_BUSY"):
        _call(busy, apply=True)
    index.chunk_count = 4
    index.save(update_fields=["chunk_count"])
    with pytest.raises(VectorStoreError, match="SHARED_BACKFILL_COUNT_MISMATCH"):
        _call(index, apply=True)
    assert not SharedVectorChunk.objects.exists()


def test_final_batch_and_layout_switch_roll_back_if_audit_fails(monkeypatch):
    index, _, _ = _legacy_managed()
    _call(index, apply=True, batch_size=1)

    def unavailable(**kwargs):
        raise RuntimeError("synthetic audit unavailable")

    monkeypatch.setattr("apps.ingestion.shared_backfill.record_event", unavailable)
    with pytest.raises(RuntimeError, match="synthetic audit unavailable"):
        _call(index, apply=True)
    index.refresh_from_db()
    assert index.storage_layout == "legacy"
    assert SharedVectorChunk.objects.filter(index_version=index).count() == 1
