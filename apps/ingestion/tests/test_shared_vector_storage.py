"""Real PostgreSQL evidence for the shared store's ownership and lifecycle boundary."""

from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, transaction

from apps.documents.models import (
    Document,
    DocumentSet,
    DocumentSetMembership,
    DocumentSetVersion,
    DocumentVersion,
)
from apps.ingestion import vector_store
from apps.ingestion.models import IndexedDocument, IndexVersion, SharedVectorChunk
from apps.ingestion.vector_store import VectorRow, VectorStoreError
from apps.tenancy.context import set_tenant_context, set_tenant_scope
from apps.tenancy.models import Organization

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="shared vector integrity requires PG"
    ),
]


def _generation(name="one", dimensions=64, representation="vector"):
    org = Organization.objects.create(slug=name, name=name)
    index = IndexVersion.objects.create(
        organization=org,
        version=1,
        dimensions=dimensions,
        index_type=representation,
        storage_layout="shared_v1",
        storage_state="open",
        status="building",
    )
    doc = IndexedDocument.objects.create(
        organization=org,
        index_version=index,
        source_uri=f"synthetic:{name}",
        checksum="a" * 64,
    )
    return index, doc


def _row(index, doc, **changes):
    values = {
        "organization_id": index.organization_id,
        "index_version": index,
        "indexed_document": doc,
        "ordinal": 0,
        "text": "Synthetic shared chunk",
        "embedding": [1.0] + [0.0] * (index.dimensions - 1),
        "dimensions": index.dimensions,
        "representation": index.index_type,
    }
    values.update(changes)
    return SharedVectorChunk.objects.create(**values)


def test_multiple_geometries_use_the_same_fixed_table():
    first, first_doc = _generation()
    second, second_doc = _generation("two", 768)
    _row(first, first_doc)
    _row(second, second_doc)
    assert SharedVectorChunk.objects.count() == 2
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'ingestion_sharedvectorchunk' "
            "AND indexname LIKE 'shared_%_cos'"
        )
        assert cursor.fetchone()[0] == 5
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'ingestion_sharedvectorchunk'::regclass"
        )
        assert cursor.fetchone() == (True, True)


@pytest.mark.parametrize(
    "dimensions,representation",
    [
        (64, "vector"),
        (768, "vector"),
        (1536, "vector"),
        (3072, "halfvec"),
        (4000, "halfvec"),
    ],
)
def test_every_fixed_geometry_has_a_working_write_and_search_path(dimensions, representation):
    index, document = _generation(dimensions=dimensions, representation=representation)
    embedding = [0.75, 0.25] + [0.0] * (dimensions - 2)
    vector_store.write_chunks(
        index,
        [
            VectorRow(
                index.organization_id,
                None,
                0,
                "synthetic geometry",
                embedding,
                indexed_document_id=document.pk,
            )
        ],
    )
    hits = vector_store.search(
        index,
        embedding,
        organization_id=index.organization_id,
        top_k=10,
    )
    assert len(hits) == 1 and hits[0].indexed_document_id == document.pk
    assert hits[0].score > 0.99


def test_malformed_dimension_and_cross_generation_document_are_rejected():
    index, doc = _generation()
    other, other_doc = _generation("other")
    for changes in (
        {"embedding": [1.0, 0.0]},
        {"organization_id": other.organization_id},
        {"indexed_document": other_doc},
        {"dimensions": 768, "embedding": [1.0] * 768},
        {"chunk_kind": "unknown"},
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            _row(index, doc, **changes)
    assert SharedVectorChunk.objects.count() == 0


def test_chunks_are_immutable_unique_and_retirement_fences_late_writers():
    index, doc = _generation()
    row = _row(index, doc)
    with pytest.raises(DatabaseError), transaction.atomic():
        _row(index, doc)
    with pytest.raises(DatabaseError, match="SHARED_CHUNK_IMMUTABLE"), transaction.atomic():
        SharedVectorChunk.objects.filter(pk=row.pk).update(text="changed")
    with pytest.raises(DatabaseError, match="SHARED_CHUNK_RETIRE_REQUIRED"), transaction.atomic():
        row.delete()
    index.storage_state = "retired"
    index.save(update_fields=["storage_state"])
    with pytest.raises(DatabaseError, match="SHARED_CHUNK_NOT_WRITABLE"), transaction.atomic():
        _row(index, doc, ordinal=1)
    row.delete()
    assert not SharedVectorChunk.objects.exists()


def test_active_generation_rejects_new_chunks_even_with_open_state():
    index, doc = _generation()
    index.status = "active"
    index.save(update_fields=["status"])
    with pytest.raises(DatabaseError, match="SHARED_CHUNK_NOT_WRITABLE"), transaction.atomic():
        _row(index, doc)


def test_non_owner_role_cannot_cross_tenant_or_impersonate_backfill():
    index, doc = _generation()
    other, other_doc = _generation("other")
    _row(other, other_doc)
    role = f"shared_probe_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion_sharedvectorchunk TO "{role}"'
        )  # noqa: S608
        cursor.execute(f'GRANT SELECT, UPDATE ON ingestion_indexversion TO "{role}"')  # noqa: S608
        # Same immutable receipt visibility as the production runtime-role template.
        cursor.execute(f'GRANT SELECT ON workflows_runretrievalgeneration TO "{role}"')
        cursor.execute(f'GRANT SELECT ON ingestion_indexeddocument, ingestion_source TO "{role}"')  # noqa: S608
        cursor.execute(f'GRANT USAGE ON SEQUENCE ingestion_sharedvectorchunk_id_seq TO "{role}"')  # noqa: S608
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )  # noqa: S608
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SET LOCAL ROLE "{role}"')  # noqa: S608
        set_tenant_scope(())
        assert not SharedVectorChunk.objects.exists()
        set_tenant_context(index.organization_id)
        _row(index, doc)
        assert list(SharedVectorChunk.objects.values_list("organization_id", flat=True)) == [
            index.organization_id
        ]
        for target in (index, other, index):
            hits = vector_store.search(
                target, [1.0] * 64, organization_id=target.organization_id, top_k=10
            )
            assert len(hits) == 1
            assert hits[0].indexed_document_id == (
                doc.pk if target.pk == index.pk else other_doc.pk
            )
        assert (
            vector_store.search(other, [1.0] * 64, organization_id=index.organization_id, top_k=10)
            == []
        )
        set_tenant_context(index.organization_id)
        with pytest.raises(DatabaseError), transaction.atomic():
            _row(other, other_doc, ordinal=1)
        index.status = "active"
        index.save(update_fields=["status"])
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.shared_vector_backfill', 'on', true)")
        with pytest.raises(DatabaseError, match="SHARED_CHUNK_NOT_WRITABLE"), transaction.atomic():
            _row(index, doc, ordinal=1)
        from apps.ingestion.shared_backfill import backfill_generation

        with pytest.raises(VectorStoreError, match="SHARED_BACKFILL_OWNER_REQUIRED"):
            backfill_generation(
                index_version_id=index.pk,
                organization_id=index.organization_id,
                actor="synthetic-runtime",
                apply=True,
            )
        set_tenant_scope(())
        assert not SharedVectorChunk.objects.exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


def _managed_generations(layout="shared_v1", dimensions=64, representation="vector"):
    org = Organization.objects.create(slug="managed", name="Managed")
    doc_set = DocumentSet.objects.create(organization=org, logical_id="set", name="Set")
    doc = Document.objects.create(organization=org, logical_id="doc", title="Document")
    version = DocumentVersion.objects.create(
        organization=org,
        document=doc,
        version=1,
        checksum="a" * 64,
        mime_type="text/plain",
        byte_size=10,
        object_key="synthetic/doc",
    )
    indexes = []
    for number in (1, 2):
        set_version = DocumentSetVersion.objects.create(
            organization=org,
            document_set=doc_set,
            version=number,
        )
        DocumentSetMembership.objects.create(
            organization=org,
            document_set_version=set_version,
            document_version=version,
        )
        indexes.append(
            IndexVersion.objects.create(
                organization=org,
                document_set_version=set_version,
                version=1,
                dimensions=dimensions,
                index_type=representation,
                storage_layout=layout,
                storage_state="new",
                pipeline_fingerprint="a" * 64,
            )
        )
    return indexes[0], indexes[1], version


def test_all_managed_dal_reads_and_copy_keep_exact_generation():
    first, second, doc = _managed_generations()
    embedding = [1.0] + [0.0] * 63
    for index in (first, second):
        assert vector_store.provision_store(index) == "ingestion_sharedvectorchunk"
    vector_store.write_chunks(
        first,
        [
            VectorRow(
                first.organization_id,
                doc.pk,
                0,
                "policy first",
                embedding,
            )
        ],
    )
    assert vector_store.copy_chunks(first, second, [doc.pk]) == 1
    vector_store.write_chunks(
        second,
        [
            VectorRow(
                second.organization_id,
                doc.pk,
                1,
                "policy second summary",
                embedding,
                "summary",
            )
        ],
    )
    assert vector_store.chunk_counts_by_document(first, [doc.pk]) == {doc.pk: 1}
    assert vector_store.chunk_counts_by_document(second, [doc.pk]) == {doc.pk: 2}
    assert vector_store.chunk_preview_for_document(first, doc.pk) == [(0, "policy first")]
    assert vector_store.exact_chunk_text(first, doc.pk, 1) is None
    assert vector_store.exact_chunk_text(second, doc.pk, 1) == "policy second summary"
    assert [
        hit.text
        for hit in vector_store.search(
            first,
            embedding,
            organization_id=first.organization_id,
            top_k=10,
        )
    ] == ["policy first"]
    assert [
        hit.text
        for hit in vector_store.keyword_search(
            second,
            "policy",
            organization_id=second.organization_id,
            top_k=10,
            document_version_ids=[doc.pk],
            chunk_kinds=("summary",),
        )
    ] == ["policy second summary"]
    assert (
        vector_store.search(
            first,
            embedding,
            organization_id=first.organization_id + 999,
            top_k=10,
        )
        == []
    )
    assert (
        vector_store.search(
            first,
            embedding,
            organization_id=first.organization_id,
            top_k=10,
            document_version_ids=[],
        )
        == []
    )
    vector_store.drop_store(first)
    assert not vector_store.store_exists(first)
    assert vector_store.store_exists(second)
    assert vector_store.chunk_counts_by_document(second, [doc.pk]) == {doc.pk: 2}
    with pytest.raises(VectorStoreError, match="SHARED_CHUNK_NOT_WRITABLE"):
        vector_store.write_chunks(first, [])


def test_generation_lineage_cannot_change_or_reopen_after_sealing():
    index, doc = _generation()
    _row(index, doc)
    for change in (
        {"dimensions": 768},
        {"storage_layout": "legacy"},
        {"pipeline_fingerprint": "b" * 64},
    ):
        with (
            pytest.raises(DatabaseError, match="SHARED_GENERATION_IMMUTABLE"),
            transaction.atomic(),
        ):
            IndexVersion.objects.filter(pk=index.pk).update(**change)
    index.storage_state = "sealed"
    index.save(update_fields=["storage_state"])
    with (
        pytest.raises(DatabaseError, match="SHARED_GENERATION_STATE_INVALID"),
        transaction.atomic(),
    ):
        IndexVersion.objects.filter(pk=index.pk).update(storage_state="open")
    with pytest.raises(VectorStoreError, match="SHARED_CHUNK_RETENTION_REQUIRED"):
        vector_store.drop_store(index)
    assert SharedVectorChunk.objects.filter(index_version=index).count() == 1


def test_document_purge_preserves_blob_when_only_shared_generation_still_references_it(monkeypatch):
    from apps.documents import services, storage

    index, _, document_version = _managed_generations()
    vector_store.provision_store(index)
    vector_store.write_chunks(
        index,
        [VectorRow(index.organization_id, document_version.pk, 0, "retained", [1.0] * 64)],
    )
    DocumentSetMembership.objects.filter(document_version=document_version).delete()
    deletions = []
    monkeypatch.setattr(
        storage.InMemoryObjectStore, "delete", lambda self, key: deletions.append(key)
    )
    with pytest.raises(services.DocumentError) as caught:
        services.purge_document(document_version.document, actor="synthetic")
    assert caught.value.code == "DOCUMENT_IN_USE"
    assert deletions == []
    assert DocumentVersion.objects.filter(pk=document_version.pk).exists()
    assert SharedVectorChunk.objects.filter(index_version=index).count() == 1


def test_bulk_write_rolls_back_earlier_batches_when_a_later_row_is_invalid():
    first, _, doc = _managed_generations()
    vector_store.provision_store(first)
    rows = [
        VectorRow(
            first.organization_id,
            doc.pk,
            ordinal,
            "synthetic batch",
            [1.0] * 64,
        )
        for ordinal in range(101)
    ]
    rows.append(rows[0])
    with pytest.raises(VectorStoreError, match="SHARED_CHUNK_WRITE_REJECTED"):
        vector_store.write_chunks(first, rows)
    assert not SharedVectorChunk.objects.exists()


def test_managed_chunk_requires_exact_membership_and_unsupported_geometry_fails_early():
    first, second, doc = _managed_generations()
    DocumentSetMembership.objects.filter(document_set_version=second.document_set_version).delete()
    vector_store.provision_store(second)
    with pytest.raises(VectorStoreError, match="SHARED_CHUNK_DOCUMENT_SCOPE"):
        vector_store.write_chunks(
            second,
            [
                VectorRow(
                    second.organization_id,
                    doc.pk,
                    0,
                    "must not persist",
                    [1.0] * 64,
                )
            ],
        )
    invalid = IndexVersion.objects.create(
        organization_id=first.organization_id,
        version=99,
        dimensions=65,
        index_type="vector",
        storage_layout="shared_v1",
    )
    with pytest.raises(VectorStoreError, match="SHARED_VECTOR_GEOMETRY_UNSUPPORTED"):
        vector_store.provision_store(invalid)
    assert not SharedVectorChunk.objects.exists()


def test_real_shared_build_seals_and_supports_promotion_and_incremental_copy(settings):
    from apps.documents import services, storage
    from apps.ingestion.staged_build import build_staged_index, promote_staged_index
    from apps.ingestion.tests.test_staged_build import _granted_profile, _published_set_version

    settings.INGESTION_VECTOR_STORAGE_LAYOUT = "shared_v1"
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    storage.reset_in_memory_store()
    try:
        org = Organization.objects.create(slug="shared-build", name="Shared build")
        profile = _granted_profile(org)
        version = _published_set_version(org, ["policy original"])
        first = build_staged_index(
            document_set_version=version,
            embedding_profile=profile,
            actor="synthetic",
        )
        assert (first.storage_layout, first.storage_state, first.status) == (
            "shared_v1",
            "sealed",
            "promotable",
        )
        assert first.chunk_count == 1
        with pytest.raises(VectorStoreError, match="SHARED_CHUNK_NOT_WRITABLE"):
            vector_store.write_chunks(first, [])
        promote_staged_index(first, actor="synthetic")
        branched = services.branch_document_set_version(source=version, actor="synthetic")
        services.publish_document_set_version(set_version=branched, actor="synthetic")
        branched.refresh_from_db()
        second = build_staged_index(
            document_set_version=branched,
            embedding_profile=profile,
            actor="synthetic",
        )
        assert second.reused_chunk_count == 1
        assert second.embedded_chunk_count == 0
        assert second.storage_state == "sealed"
        first.refresh_from_db()
        assert first.status == "active"
        assert vector_store.store_name(first) == vector_store.store_name(second)
        assert SharedVectorChunk.objects.count() == 2
    finally:
        storage.reset_in_memory_store()
