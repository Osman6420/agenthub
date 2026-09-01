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
from typing import Any

from django.db import DatabaseError, connection, transaction

from apps.ingestion.models import (
    HALFVEC_MAX_DIMENSIONS,
    VECTOR_MAX_DIMENSIONS,
    EmbeddingIndexType,
    IndexVersion,
)
from apps.tenancy.context import set_tenant_context

# A store name is only ever ``chunk_iv_<int>``. Validated defensively before any interpolation.
_STORE_NAME = re.compile(r"^chunk_iv_[0-9]+$")
_DDL_ERROR_CODES = frozenset(
    {
        "INDEX_STORE_ACTIVE",
        "INDEX_STORE_GEOMETRY_INVALID",
        "INDEX_STORE_ID_INVALID",
        "INDEX_STORE_NOT_BUILDING",
        "INDEX_STORE_SCOPE_DENIED",
    }
)


class VectorStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _normalize_ddl_error(exc: DatabaseError) -> VectorStoreError:
    """Project database detail to an allowlisted, content-free operational code."""

    cause = exc.__cause__
    diagnostic = getattr(cause, "diag", None)
    primary = getattr(diagnostic, "message_primary", "")
    code = primary if primary in _DDL_ERROR_CODES else "INDEX_STORE_DDL_FAILED"
    return VectorStoreError(code)


@dataclass(frozen=True)
class VectorRow:
    organization_id: int
    document_version_id: int | None
    ordinal: int
    text: str
    embedding: list[float]
    chunk_kind: str = "content"


@dataclass(frozen=True)
class VectorHit:
    document_version_id: int | None
    ordinal: int
    text: str
    score: float
    chunk_kind: str = "content"


@dataclass(frozen=True)
class KeywordHit:
    document_version_id: int | None
    ordinal: int
    text: str
    score: float
    chunk_kind: str = "content"


def _require_postgres() -> None:
    if connection.vendor != "postgresql":
        raise VectorStoreError("VECTOR_STORE_REQUIRES_POSTGRES")


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
    """Provision one authoritative building index through the migration-owned DDL seam."""
    _require_postgres()
    name = store_name(index_version)
    # The application role intentionally has no schema CREATE privilege. The SECURITY DEFINER
    # function accepts only an IndexVersion integer and re-resolves its tenant/lifecycle/type under
    # FORCE RLS before emitting fixed-template DDL as the migration owner.
    try:
        with transaction.atomic():
            set_tenant_context(int(index_version.organization_id))
            with connection.cursor() as cursor:
                cursor.execute("SELECT agenthub_provision_index_store(%s)", [index_version.pk])
                provisioned = cursor.fetchone()[0]
    except DatabaseError as exc:
        raise _normalize_ddl_error(exc) from exc
    if provisioned != name:
        raise VectorStoreError("INDEX_STORE_PROVISION_MISMATCH")
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
                row.chunk_kind,
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
                "(organization_id, document_version_id, ordinal, text, chunk_kind, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
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


def chunk_preview_for_document(
    index_version: IndexVersion,
    document_version_id: int,
    *,
    max_chunks: int = 5,
    max_chars: int = 600,
) -> list[tuple[int, str]]:
    """Return up to ``max_chunks`` ``(ordinal, truncated text)`` rows for one document version.

    A bounded read for authorized operator inspection under tenant RLS: embeddings are never
    returned, at most ``max_chunks`` rows are read, and each chunk's text is truncated to
    ``max_chars`` characters in the database (never materializing full chunk bodies).
    """
    _require_postgres()
    name = store_name(index_version)
    limit = max(1, min(int(max_chunks), 50))
    chars = max(1, min(int(max_chars), 4000))
    with transaction.atomic():
        set_tenant_context(int(index_version.organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT ordinal, LEFT(text, %s) FROM "{name}" '  # noqa: S608
                "WHERE organization_id = %s AND document_version_id = %s "
                "ORDER BY ordinal LIMIT %s",
                [chars, index_version.organization_id, int(document_version_id), limit],
            )
            return [(int(row[0]), row[1]) for row in cursor.fetchall()]


def exact_chunk_text(
    index_version: IndexVersion,
    document_version_id: int,
    ordinal: int,
    *,
    max_chars: int = 8000,
) -> str | None:
    """Resolve one immutable evidence pointer without persisting a duplicate chunk body."""

    _require_postgres()
    name = store_name(index_version)
    chars = max(1, min(int(max_chars), 8000))
    with transaction.atomic():
        set_tenant_context(int(index_version.organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT LEFT(text, %s) FROM "{name}" '  # noqa: S608
                "WHERE organization_id = %s AND document_version_id = %s AND ordinal = %s "
                "LIMIT 1",
                [
                    chars,
                    index_version.organization_id,
                    int(document_version_id),
                    int(ordinal),
                ],
            )
            row = cursor.fetchone()
    return str(row[0]) if row else None


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
                "(organization_id, document_version_id, ordinal, text, chunk_kind, embedding) "
                "SELECT organization_id, document_version_id, ordinal, text, "
                "chunk_kind, embedding "
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
    document_version_ids: list[int] | None = None,
    chunk_kinds: tuple[str, ...] | None = None,
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
    filters, filter_params = _search_filters(
        organization_id=organization_id,
        document_version_ids=document_version_ids,
        chunk_kinds=chunk_kinds,
    )
    if filters is None:
        return []
    # Transaction-local tenant context so the RLS policy (ADR-0004) is active during the read; the
    # ``WHERE organization_id`` app predicate is the first layer, RLS the fail-closed backstop.
    with transaction.atomic():
        set_tenant_context(int(organization_id))
        with connection.cursor() as cursor:
            # "name"/"column_type" are int-derived and validated; values are bound params.
            cursor.execute(
                f"SELECT document_version_id, ordinal, text, chunk_kind, "  # noqa: S608
                f"(embedding <=> %s::{column_type}) AS distance "
                f'FROM "{name}" WHERE {filters} ORDER BY distance LIMIT %s',
                [literal, *filter_params, limit],
            )
            rows = cursor.fetchall()
    return [
        VectorHit(
            document_version_id=row[0],
            ordinal=row[1],
            text=row[2],
            chunk_kind=row[3],
            score=max(0.0, 1.0 - float(row[4])),
        )
        for row in rows
    ]


def keyword_search(
    index_version: IndexVersion,
    query: str,
    *,
    organization_id: int,
    top_k: int,
    document_version_ids: list[int] | None = None,
    chunk_kinds: tuple[str, ...] | None = None,
) -> list[KeywordHit]:
    """BM25-style PostgreSQL full-text ranking in one immutable, RLS-scoped store."""
    _require_postgres()
    clean_query = (query or "").strip()
    if not clean_query or len(clean_query) > 4_000:
        return []
    name = store_name(index_version)
    limit = max(1, min(int(top_k), 100))
    filters, filter_params = _search_filters(
        organization_id=organization_id,
        document_version_ids=document_version_ids,
        chunk_kinds=chunk_kinds,
    )
    if filters is None:
        return []
    with transaction.atomic():
        set_tenant_context(int(organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT document_version_id, ordinal, text, chunk_kind, "  # noqa: S608
                "ts_rank_cd(to_tsvector('simple', text), plainto_tsquery('simple', %s)) AS rank "
                f'FROM "{name}" WHERE {filters} '  # noqa: S608
                "AND to_tsvector('simple', text) @@ plainto_tsquery('simple', %s) "
                "ORDER BY rank DESC, document_version_id, ordinal LIMIT %s",
                [clean_query, *filter_params, clean_query, limit],
            )
            rows = cursor.fetchall()
    return [
        KeywordHit(
            document_version_id=row[0],
            ordinal=row[1],
            text=row[2],
            chunk_kind=row[3],
            score=max(0.0, float(row[4])),
        )
        for row in rows
    ]


def _search_filters(
    *,
    organization_id: int,
    document_version_ids: list[int] | None,
    chunk_kinds: tuple[str, ...] | None,
) -> tuple[str | None, list[Any]]:
    """Build only closed, value-parameterized search predicates for one tenant store."""
    clauses = ["organization_id = %s"]
    params: list[Any] = [int(organization_id)]
    if document_version_ids is not None:
        ids = sorted(
            {
                int(value)
                for value in document_version_ids
                if isinstance(value, int) and not isinstance(value, bool) and value > 0
            }
        )
        if not ids:
            return None, []
        if len(ids) > 5_000:
            raise VectorStoreError("SEARCH_SCOPE_TOO_LARGE")
        clauses.append("document_version_id = ANY(%s)")
        params.append(ids)
    if chunk_kinds is not None:
        if not chunk_kinds or any(
            not isinstance(kind, str) or kind not in {"content", "summary"} for kind in chunk_kinds
        ):
            raise VectorStoreError("CHUNK_KIND_INVALID")
        kinds = tuple(sorted(set(chunk_kinds)))
        clauses.append("chunk_kind = ANY(%s)")
        params.append(list(kinds))
    return " AND ".join(clauses), params


def store_exists(index_version: IndexVersion) -> bool:
    _require_postgres()
    name = store_name(index_version)
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [name])
        return cursor.fetchone()[0] is not None


def drop_store(index_version: IndexVersion) -> None:
    """Drop a non-active store through the migration-owned, tenant-scoped DDL seam."""
    _require_postgres()
    store_name(index_version)
    try:
        with transaction.atomic():
            set_tenant_context(int(index_version.organization_id))
            with connection.cursor() as cursor:
                cursor.execute("SELECT agenthub_drop_index_store(%s)", [index_version.pk])
    except DatabaseError as exc:
        raise _normalize_ddl_error(exc) from exc
