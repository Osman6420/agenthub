"""Per-IndexVersion vector-store DAL (ADR-0003). Vector paths are PostgreSQL-only."""

from __future__ import annotations

import pytest
from django.db import DatabaseError, connection, transaction

from apps.ingestion import vector_store
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.ingestion.pipeline import embed_deterministic
from apps.ingestion.vector_store import VectorRow, VectorStoreError
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization

pg_only = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="pgvector store requires PostgreSQL"
)


def test_store_name_is_int_derived_and_validated() -> None:
    assert vector_store.store_name(7) == "chunk_iv_7"
    for bad in (0, -1, True):
        with pytest.raises(VectorStoreError):
            vector_store.store_name(bad)


@pytest.mark.skipif(connection.vendor == "postgresql", reason="asserts the off-PostgreSQL guard")
@pytest.mark.django_db
def test_provision_requires_postgres_off_pg() -> None:
    org = Organization.objects.create(slug="o", name="O")
    iv = IndexVersion.objects.create(
        organization=org, dimensions=4, index_type="vector", version=1, status=IndexStatus.BUILDING
    )
    with pytest.raises(VectorStoreError, match="VECTOR_STORE_REQUIRES_POSTGRES"):
        vector_store.provision_store(iv)


def _index_version(dimensions: int = 4, index_type: str = "vector") -> IndexVersion:
    org = Organization.objects.create(slug="vs-org", name="VS Org")
    return IndexVersion.objects.create(
        organization=org,
        dimensions=dimensions,
        index_type=index_type,
        version=1,
        status=IndexStatus.BUILDING,
    )


@pg_only
@pytest.mark.django_db
def test_provision_write_search_roundtrip() -> None:
    iv = _index_version(dimensions=4)
    vector_store.provision_store(iv)
    assert vector_store.store_exists(iv)
    vector_store.write_chunks(
        iv,
        [
            VectorRow(iv.organization_id, 10, 0, "iade policy", [1.0, 0.0, 0.0, 0.0]),
            VectorRow(iv.organization_id, 10, 1, "shipping", [0.0, 1.0, 0.0, 0.0]),
        ],
    )
    hits = vector_store.search(
        iv, [1.0, 0.0, 0.0, 0.0], organization_id=iv.organization_id, top_k=1
    )
    assert len(hits) == 1
    assert hits[0].text == "iade policy"
    assert hits[0].score > 0.9

    vector_store.drop_store(iv)
    assert not vector_store.store_exists(iv)


@pg_only
@pytest.mark.django_db(transaction=True)
def test_non_owner_ddl_functions_require_exact_scope_without_schema_create() -> None:
    iv = _index_version(dimensions=4)
    other = Organization.objects.create(slug="vs-other", name="VS Other")
    role = "index_store_ddl_probe"
    with connection.cursor() as cursor:
        cursor.execute(
            f'DO $$ BEGIN CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN; '
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"  # noqa: S608
        )
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", [role])
        assert cursor.fetchone() == (False, False)
        cursor.execute(
            "SELECT has_function_privilege(%s, "
            "'public.agenthub_provision_index_store(bigint)', 'EXECUTE')",
            [role],
        )
        assert cursor.fetchone()[0] is False
        cursor.execute(f'REVOKE CREATE ON SCHEMA public FROM "{role}"')  # noqa: S608
        cursor.execute(f'GRANT SELECT ON ingestion_indexversion TO "{role}"')  # noqa: S608
        cursor.execute(
            f"GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint), "
            f"agenthub_provision_index_store(bigint), agenthub_drop_index_store(bigint) "
            f'TO "{role}"'  # noqa: S608
        )
        cursor.execute("SELECT has_schema_privilege(%s, 'public', 'CREATE')", [role])
        assert cursor.fetchone()[0] is False
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SET SESSION AUTHORIZATION "{role}"')  # noqa: S608
        try:
            with pytest.raises(DatabaseError, match="INDEX_STORE_SCOPE_DENIED"):
                with transaction.atomic():
                    set_tenant_context(other.pk)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT agenthub_provision_index_store(%s)", [iv.pk])

            vector_store.provision_store(iv)
            assert vector_store.store_exists(iv)
            vector_store.drop_store(iv)
            assert not vector_store.store_exists(iv)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET SESSION AUTHORIZATION")
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET SESSION AUTHORIZATION")
            cursor.execute(f'DROP OWNED BY "{role}"')  # noqa: S608
            cursor.execute(f'DROP ROLE "{role}"')  # noqa: S608


@pg_only
@pytest.mark.django_db(transaction=True)
def test_ddl_functions_enforce_store_lifecycle() -> None:
    iv = _index_version(dimensions=4)
    vector_store.provision_store(iv)
    iv.status = IndexStatus.ACTIVE
    iv.save(update_fields=["status", "updated_at"])

    with pytest.raises(VectorStoreError, match="INDEX_STORE_ACTIVE"):
        vector_store.drop_store(iv)

    iv.status = IndexStatus.SUPERSEDED
    iv.save(update_fields=["status", "updated_at"])
    vector_store.drop_store(iv)
    assert not vector_store.store_exists(iv)


@pg_only
@pytest.mark.django_db
def test_search_filters_exact_document_versions_and_chunk_kinds() -> None:
    iv = _index_version(dimensions=4)
    vector_store.provision_store(iv)
    vector_store.write_chunks(
        iv,
        [
            VectorRow(
                iv.organization_id,
                10,
                0,
                "route term summary",
                [1.0, 0.0, 0.0, 0.0],
                "summary",
            ),
            VectorRow(
                iv.organization_id,
                10,
                1,
                "route term selected content",
                [1.0, 0.0, 0.0, 0.0],
            ),
            VectorRow(
                iv.organization_id,
                20,
                0,
                "route term excluded content",
                [1.0, 0.0, 0.0, 0.0],
            ),
        ],
    )

    vector_hits = vector_store.search(
        iv,
        [1.0, 0.0, 0.0, 0.0],
        organization_id=iv.organization_id,
        top_k=10,
        document_version_ids=[10],
        chunk_kinds=("content",),
    )
    keyword_hits = vector_store.keyword_search(
        iv,
        "route term",
        organization_id=iv.organization_id,
        top_k=10,
        document_version_ids=[10],
        chunk_kinds=("content",),
    )

    assert [(hit.document_version_id, hit.chunk_kind) for hit in vector_hits] == [(10, "content")]
    assert [(hit.document_version_id, hit.chunk_kind) for hit in keyword_hits] == [(10, "content")]
    vector_store.drop_store(iv)


@pg_only
@pytest.mark.django_db
def test_chunk_preview_is_bounded_and_ordered() -> None:
    # Backs the console document-detail chunk view (Scope G): counts + a bounded, ordered,
    # truncated text preview for one document version, embeddings never returned.
    iv = _index_version(dimensions=4)
    vector_store.provision_store(iv)
    rows = [
        VectorRow(
            iv.organization_id, 42, ordinal, f"chunk-{ordinal} " + "x" * 50, [1.0, 0.0, 0.0, 0.0]
        )
        for ordinal in range(8)
    ]
    rows.append(VectorRow(iv.organization_id, 99, 0, "other doc", [0.0, 1.0, 0.0, 0.0]))
    vector_store.write_chunks(iv, rows)

    counts = vector_store.chunk_counts_by_document(iv, [42, 99])
    assert counts == {42: 8, 99: 1}

    preview = vector_store.chunk_preview_for_document(iv, 42, max_chunks=3, max_chars=10)
    assert [ordinal for ordinal, _ in preview] == [0, 1, 2]  # ordered, capped at max_chunks
    assert all(len(text) <= 10 for _, text in preview)  # truncated in the database
    vector_store.drop_store(iv)


@pg_only
@pytest.mark.django_db
def test_search_is_tenant_scoped() -> None:
    iv = _index_version(dimensions=4)
    vector_store.provision_store(iv)
    vector_store.write_chunks(
        iv,
        [
            VectorRow(iv.organization_id, 1, 0, "ours", [1.0, 0.0, 0.0, 0.0]),
            VectorRow(iv.organization_id + 999, 2, 0, "theirs", [1.0, 0.0, 0.0, 0.0]),
        ],
    )
    hits = vector_store.search(
        iv, [1.0, 0.0, 0.0, 0.0], organization_id=iv.organization_id, top_k=10
    )
    assert [h.text for h in hits] == ["ours"]  # the other tenant's row is filtered out


@pg_only
@pytest.mark.django_db
def test_write_rejects_dimension_mismatch() -> None:
    iv = _index_version(dimensions=4)
    vector_store.provision_store(iv)
    with pytest.raises(VectorStoreError, match="DIMENSION_MISMATCH"):
        vector_store.write_chunks(iv, [VectorRow(iv.organization_id, 1, 0, "x", [1.0, 2.0, 3.0])])


@pg_only
@pytest.mark.django_db
def test_halfvec_store_roundtrip() -> None:
    iv = _index_version(dimensions=3, index_type="halfvec")
    vector_store.provision_store(iv)
    vector_store.write_chunks(
        iv, [VectorRow(iv.organization_id, 1, 0, "h", embed_deterministic("h")[:3])]
    )
    hits = vector_store.search(
        iv, embed_deterministic("h")[:3], organization_id=iv.organization_id, top_k=1
    )
    assert len(hits) == 1
