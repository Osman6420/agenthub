"""Name-parameterized data-access layer for per-``IndexVersion`` vector stores (ADR-0003).

Each ``IndexVersion`` owns one **immutable, dimension-fixed** physical store — its own
``vector(D)``/``halfvec(D)`` table and HNSW cosine index — so active and staged index versions of
different dimensions coexist (blue/green) and promotion/rollback is a metadata pointer flip that
touches no vector data (the flip itself lands in P4). This is the ADR-0003 "main implementation
risk": the store relation name is **system-generated from the integer ``IndexVersion`` id only**
(never from tenant/user/author input) and is validated against a strict pattern before it is ever
interpolated into DDL; every value (vectors, ids) is passed as a bound parameter.

PostgreSQL-only: SQLite cannot exercise pgvector, so the whole DAL fails closed off PostgreSQL,
exactly like the existing pgvector retrieval suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import connection, transaction

from apps.ingestion.models import (
    HALFVEC_MAX_DIMENSIONS,
    VECTOR_MAX_DIMENSIONS,
    EmbeddingIndexType,
    IndexVersion,
)

# A store name is only ever ``chunk_iv_<int>``. Validated defensively before any interpolation.
_STORE_NAME = re.compile(r"^chunk_iv_[0-9]+$")


class VectorStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VectorRow:
    organization_id: int
    document_version_id: int | None
    ordinal: int
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class VectorHit:
    document_version_id: int | None
    ordinal: int
    text: str
    score: float


def _require_postgres() -> None:
    if connection.vendor != "postgresql":
        raise VectorStoreError("VECTOR_STORE_REQUIRES_POSTGRES")


def set_tenant_context(organization_id: int) -> None:
    """Set the transaction-local tenant id for RLS (ADR-0004); PostgreSQL-only, else no-op.

    ``is_local=true`` scopes the setting to the current transaction so it never leaks to the next
    operation on a pooled connection. Callers must run inside a transaction that also issues the
    tenant-scoped query, or the setting is lost. A missing/invalid setting makes the RLS policy
    return no rows (fail-closed).
    """
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(int(organization_id))])


def store_name(index_version: IndexVersion | int) -> str:
    """Return the system-generated store relation name for an index version.

    The name derives from the integer primary key only; it is validated against a strict
    pattern so it can never carry attacker-influenced SQL-identifier content.
    """
    iv_id = index_version if isinstance(index_version, int) else index_version.pk
    if not isinstance(iv_id, int) or isinstance(iv_id, bool) or iv_id <= 0:
        raise VectorStoreError("INVALID_INDEX_VERSION")
    name = f"chunk_iv_{iv_id}"
    if not _STORE_NAME.fullmatch(name):  # defense-in-depth; the name is int-derived
        raise VectorStoreError("INVALID_STORE_NAME")
    return name


def _column_spec(index_type: str, dimensions: int | None) -> tuple[str, str]:
    if dimensions is None or isinstance(dimensions, bool) or not isinstance(dimensions, int):
        raise VectorStoreError("DIMENSIONS_INVALID")
    dim = int(dimensions)
    if index_type == EmbeddingIndexType.HALFVEC:
        if not 1 <= dim <= HALFVEC_MAX_DIMENSIONS:
            raise VectorStoreError("DIMENSIONS_UNSUPPORTED")
        return f"halfvec({dim})", "halfvec_cosine_ops"
    if index_type not in ("", EmbeddingIndexType.VECTOR):
        raise VectorStoreError("INDEX_TYPE_INVALID")
    if not 1 <= dim <= VECTOR_MAX_DIMENSIONS:
        raise VectorStoreError("DIMENSIONS_UNSUPPORTED")
    return f"vector({dim})", "vector_cosine_ops"


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def provision_store(index_version: IndexVersion) -> str:
    """Create the fixed-dimension store table and its HNSW cosine index (idempotent)."""
    _require_postgres()
    name = store_name(index_version)
    column_type, opclass = _column_spec(index_version.index_type, index_version.dimensions)
    with connection.cursor() as cursor:
        cursor.execute(
            f'CREATE TABLE IF NOT EXISTS "{name}" ('
            "id bigserial PRIMARY KEY, "
            "organization_id bigint NOT NULL, "
            "document_version_id bigint, "
            "ordinal integer NOT NULL, "
            "text text NOT NULL, "
            f"embedding {column_type} NOT NULL)"
        )
        cursor.execute(
            f'CREATE INDEX IF NOT EXISTS "{name}_hnsw" ON "{name}" '
            f"USING hnsw (embedding {opclass}) WITH (m = 16, ef_construction = 64)"
        )
        # RLS backstop (ADR-0004): FORCE applies the policy even to the table owner, so a missing
        # ``app.tenant_id`` (or a mismatched one) yields no rows regardless of the app predicate.
        cursor.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        cursor.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        cursor.execute(f'DROP POLICY IF EXISTS "{name}_tenant" ON "{name}"')
        # NULLIF makes a missing OR empty ``app.tenant_id`` resolve to NULL -> the predicate is
        # NULL -> no rows (fail-closed), and avoids an ``''::bigint`` cast error.
        cursor.execute(
            f'CREATE POLICY "{name}_tenant" ON "{name}" '
            "USING (organization_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"
        )
    return name


def write_chunks(index_version: IndexVersion, rows: list[VectorRow]) -> int:
    """Insert chunk rows, rejecting any vector whose length ≠ the store dimension."""
    _require_postgres()
    name = store_name(index_version)
    dimensions = int(index_version.dimensions or 0)
    params = []
    for row in rows:
        if len(row.embedding) != dimensions:
            raise VectorStoreError("DIMENSION_MISMATCH")
        params.append(
            [
                row.organization_id,
                row.document_version_id,
                row.ordinal,
                row.text,
                _vector_literal(row.embedding),
            ]
        )
    if not params:
        return 0
    # A store is single-tenant; set the tenant context so the RLS WITH CHECK admits the rows
    # under the production (non-owner) app role. The INSERT + context share one transaction.
    with transaction.atomic():
        set_tenant_context(int(index_version.organization_id))
        with connection.cursor() as cursor:
            # "name" is int-derived and regex-validated (ADR-0003); values are bound parameters.
            cursor.executemany(
                f'INSERT INTO "{name}" '  # noqa: S608
                "(organization_id, document_version_id, ordinal, text, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                params,
            )
    return len(params)


def chunk_counts_by_document(
    index_version: IndexVersion, document_version_ids: list[int]
) -> dict[int, int]:
    """Return exact chunk counts for requested immutable document versions under tenant RLS."""
    _require_postgres()
    if not document_version_ids:
        return {}
    name = store_name(index_version)
    ids = sorted({int(value) for value in document_version_ids})
    with transaction.atomic():
        set_tenant_context(int(index_version.organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT document_version_id, COUNT(*) FROM "{name}" '  # noqa: S608
                "WHERE organization_id = %s AND document_version_id = ANY(%s) "
                "GROUP BY document_version_id",
                [index_version.organization_id, ids],
            )
            return {int(row[0]): int(row[1]) for row in cursor.fetchall()}


def copy_chunks(parent: IndexVersion, target: IndexVersion, document_version_ids: list[int]) -> int:
    """Copy compatible immutable rows between int-derived stores under the same tenant context."""
    _require_postgres()
    if parent.organization_id != target.organization_id:
        raise VectorStoreError("VECTOR_COPY_TENANT_MISMATCH")
    if parent.dimensions != target.dimensions or parent.index_type != target.index_type:
        raise VectorStoreError("VECTOR_COPY_GEOMETRY_MISMATCH")
    if (
        not parent.pipeline_fingerprint
        or parent.pipeline_fingerprint != target.pipeline_fingerprint
    ):
        raise VectorStoreError("VECTOR_COPY_PIPELINE_MISMATCH")
    parent_set_version = parent.document_set_version
    target_set_version = target.document_set_version
    if (
        parent_set_version is None
        or target_set_version is None
        or parent_set_version.document_set_id != target_set_version.document_set_id
    ):
        raise VectorStoreError("VECTOR_COPY_DOCUMENT_SET_MISMATCH")
    ids = sorted({int(value) for value in document_version_ids})
    if not ids:
        return 0
    parent_name = store_name(parent)
    target_name = store_name(target)
    with transaction.atomic():
        set_tenant_context(int(target.organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO "{target_name}" '  # noqa: S608
                "(organization_id, document_version_id, ordinal, text, embedding) "
                f"SELECT organization_id, document_version_id, ordinal, text, embedding "
                f'FROM "{parent_name}" '  # noqa: S608
                "WHERE organization_id = %s AND document_version_id = ANY(%s)",
                [target.organization_id, ids],
            )
            return int(cursor.rowcount)


def search(
    index_version: IndexVersion,
    query_embedding: list[float],
    *,
    organization_id: int,
    top_k: int,
) -> list[VectorHit]:
    """Cosine-nearest chunks in one store, scoped to a tenant (RLS is the P4 backstop)."""
    _require_postgres()
    name = store_name(index_version)
    dimensions = int(index_version.dimensions or 0)
    if len(query_embedding) != dimensions:
        raise VectorStoreError("DIMENSION_MISMATCH")
    column_type, _ = _column_spec(index_version.index_type, dimensions)
    literal = _vector_literal(query_embedding)
    limit = max(1, min(int(top_k), 100))
    # Transaction-local tenant context so the RLS policy (ADR-0004) is active during the read; the
    # ``WHERE organization_id`` app predicate is the first layer, RLS the fail-closed backstop.
    with transaction.atomic():
        set_tenant_context(int(organization_id))
        with connection.cursor() as cursor:
            # "name"/"column_type" are int-derived and validated; values are bound params.
            cursor.execute(
                f"SELECT document_version_id, ordinal, text, "  # noqa: S608
                f"(embedding <=> %s::{column_type}) AS distance "
                f'FROM "{name}" WHERE organization_id = %s ORDER BY distance LIMIT %s',
                [literal, organization_id, limit],
            )
            rows = cursor.fetchall()
    return [
        VectorHit(
            document_version_id=row[0],
            ordinal=row[1],
            text=row[2],
            score=max(0.0, 1.0 - float(row[3])),
        )
        for row in rows
    ]


def store_exists(index_version: IndexVersion) -> bool:
    _require_postgres()
    name = store_name(index_version)
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [name])
        return cursor.fetchone()[0] is not None


def drop_store(index_version: IndexVersion) -> None:
    """Drop a store's physical relation (retention/purge and rollback of a failed build)."""
    _require_postgres()
    name = store_name(index_version)
    with connection.cursor() as cursor:
        cursor.execute(f'DROP TABLE IF EXISTS "{name}"')
