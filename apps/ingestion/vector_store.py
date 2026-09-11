"""Generation-scoped vector DAL with an additive shared-store transition (ADR-0020).

Shared generations use migration-owned geometry indexes and row-level lifecycle
fences without runtime DDL. Legacy generations retain validated integer-derived
physical names (ADR-0003) until verified backfill. Values are bound parameters;
geometry SQL fragments come only from the migration-backed finite registry.

PostgreSQL-only: SQLite cannot exercise pgvector, so the whole DAL fails closed off PostgreSQL,
exactly like the existing pgvector retrieval suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import DatabaseError, connection, transaction

from apps.ingestion.generation_lifecycle import (
    GenerationFenced,
    lock_build_request,
    lock_generation,
)
from apps.ingestion.models import (
    HALFVEC_MAX_DIMENSIONS,
    VECTOR_MAX_DIMENSIONS,
    EmbeddingIndexType,
    IndexVersion,
)
from apps.ingestion.vector_geometry import shared_geometry
from apps.tenancy.context import normalize_tenant_scope, set_tenant_context

# A store name is only ever ``chunk_iv_<int>``. Validated defensively before any interpolation.
_STORE_NAME = re.compile(r"^chunk_iv_[0-9]+$")
_DDL_ERROR_CODES = frozenset(
    {
        "INDEX_STORE_ACTIVE",
        "INDEX_STORE_GEOMETRY_INVALID",
        "INDEX_STORE_ID_INVALID",
        "INDEX_STORE_NOT_BUILDING",
        "INDEX_STORE_SCOPE_DENIED",
        "INDEX_STORE_LAYOUT_INVALID",
        "RETRIEVAL_GENERATION_PROTECTED",
    }
)


class VectorStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def new_generation_layout() -> str:
    """Deployment-controlled transition; clients cannot choose or downgrade storage."""
    layout = getattr(settings, "INGESTION_VECTOR_STORAGE_LAYOUT", "legacy")
    if layout not in {"legacy", "shared_v1"}:
        raise VectorStoreError("VECTOR_STORAGE_LAYOUT_INVALID")
    return str(layout)


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
    indexed_document_id: int | None = None


@dataclass(frozen=True)
class VectorHit:
    document_version_id: int | None
    ordinal: int
    text: str
    score: float
    chunk_kind: str = "content"
    indexed_document_id: int | None = None


@dataclass(frozen=True)
class KeywordHit:
    document_version_id: int | None
    ordinal: int
    text: str
    score: float
    chunk_kind: str = "content"
    indexed_document_id: int | None = None


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
    if isinstance(index_version, IndexVersion) and index_version.storage_layout == "shared_v1":
        return "ingestion_sharedvectorchunk"
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


def _generation_filter(index_version: IndexVersion) -> tuple[str, list[int]]:
    if index_version.storage_layout != "shared_v1":
        return "", []
    return (
        "AND index_version_id = %s AND EXISTS (SELECT 1 FROM ingestion_indexversion g "
        "WHERE g.id = %s AND g.storage_state IN ('open', 'sealed'))",
        [index_version.pk, index_version.pk],
    )


def _write_shared_chunks(index_version: IndexVersion, rows: list[VectorRow]) -> int:
    try:
        with transaction.atomic():
            set_tenant_context(index_version.organization_id)
            locked = lock_generation(index_version)
            if (
                locked.storage_layout != "shared_v1"
                or locked.status != "building"
                or locked.storage_state != "open"
            ):
                raise VectorStoreError("SHARED_CHUNK_NOT_WRITABLE")
            try:
                geometry = shared_geometry(locked.index_type, locked.dimensions)
            except ValueError as exc:
                raise VectorStoreError(str(exc)) from exc
            params = []
            for row in rows:
                if len(row.embedding) != geometry.dimensions:
                    raise VectorStoreError("DIMENSION_MISMATCH")
                if row.organization_id != locked.organization_id:
                    raise VectorStoreError("SHARED_CHUNK_DOCUMENT_SCOPE")
                params.append(
                    [
                        row.organization_id,
                        locked.pk,
                        row.document_version_id,
                        row.indexed_document_id,
                        row.ordinal,
                        row.text,
                        row.chunk_kind,
                        _vector_literal(row.embedding),
                        geometry.dimensions,
                        geometry.representation,
                    ]
                )
            if params:
                with connection.cursor() as cursor:
                    placeholder = (
                        f"(%s,%s,%s,%s,%s,%s,%s,%s::{geometry.cast}::vector,"
                        "%s,%s,CURRENT_TIMESTAMP)"
                    )
                    for offset in range(0, len(params), 100):
                        batch = params[offset : offset + 100]
                        cursor.execute(
                            "INSERT INTO ingestion_sharedvectorchunk "  # noqa: S608
                            "(organization_id, index_version_id, document_version_id, "
                            "indexed_document_id, ordinal, text, chunk_kind, embedding, "
                            "dimensions, representation, created_at) VALUES "
                            + ",".join([placeholder] * len(batch)),
                            [value for row in batch for value in row],
                        )
            return len(params)
    except GenerationFenced as exc:
        raise VectorStoreError(exc.code) from exc
    except DatabaseError as exc:
        primary = getattr(getattr(exc.__cause__, "diag", None), "message_primary", "")
        code = (
            primary
            if primary
            in {
                "SHARED_CHUNK_NOT_WRITABLE",
                "SHARED_CHUNK_DOCUMENT_SCOPE",
                "SHARED_CHUNK_SCOPE_GEOMETRY",
                "SHARED_CHUNK_GENERATION_INVALID",
            }
            else "SHARED_CHUNK_WRITE_REJECTED"
        )
        raise VectorStoreError(code) from exc


def provision_store(index_version: IndexVersion) -> str:
    """Provision one authoritative building index through the migration-owned DDL seam."""
    _require_postgres()
    name = store_name(index_version)
    if index_version.storage_layout == "shared_v1":
        with transaction.atomic():
            set_tenant_context(index_version.organization_id)
            try:
                locked = lock_generation(index_version)
            except GenerationFenced as exc:
                raise VectorStoreError(exc.code) from exc
            if (
                locked.storage_layout != "shared_v1"
                or locked.status != "building"
                or locked.storage_state not in {"new", "open"}
            ):
                raise VectorStoreError("SHARED_CHUNK_NOT_WRITABLE")
            try:
                shared_geometry(locked.index_type, locked.dimensions)
            except ValueError as exc:
                raise VectorStoreError(str(exc)) from exc
            locked.storage_state = "open"
            locked.save(update_fields=["storage_state", "updated_at"])
            index_version.storage_state = "open"
        return name
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
    if index_version.storage_layout == "shared_v1":
        return _write_shared_chunks(index_version, rows)
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
            for offset in range(0, len(params), 100):
                batch = params[offset : offset + 100]
                cursor.execute(
                    f'INSERT INTO "{name}" '  # noqa: S608
                    "(organization_id, document_version_id, ordinal, text, chunk_kind, embedding) "
                    "VALUES " + ",".join(["(%s,%s,%s,%s,%s,%s)"] * len(batch)),
                    [value for row in batch for value in row],
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
    generation_filter, generation_params = _generation_filter(index_version)
    ids = sorted({int(value) for value in document_version_ids})
    with transaction.atomic():
        set_tenant_context(int(index_version.organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT document_version_id, COUNT(*) FROM "{name}" '  # noqa: S608
                f"WHERE organization_id = %s AND document_version_id = ANY(%s) {generation_filter} "
                "GROUP BY document_version_id",
                [index_version.organization_id, ids, *generation_params],
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
    generation_filter, generation_params = _generation_filter(index_version)
    limit = max(1, min(int(max_chunks), 50))
    chars = max(1, min(int(max_chars), 4000))
    with transaction.atomic():
        set_tenant_context(int(index_version.organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT ordinal, LEFT(text, %s) FROM "{name}" '  # noqa: S608
                f"WHERE organization_id = %s AND document_version_id = %s {generation_filter} "
                "ORDER BY ordinal LIMIT %s",
                [
                    chars,
                    index_version.organization_id,
                    int(document_version_id),
                    *generation_params,
                    limit,
                ],
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
    generation_filter, generation_params = _generation_filter(index_version)
    chars = max(1, min(int(max_chars), 8000))
    with transaction.atomic():
        set_tenant_context(int(index_version.organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT LEFT(text, %s) FROM "{name}" '  # noqa: S608
                "WHERE organization_id = %s AND document_version_id = %s AND ordinal = %s "
                f"{generation_filter} "
                "LIMIT 1",
                [
                    chars,
                    index_version.organization_id,
                    int(document_version_id),
                    int(ordinal),
                    *generation_params,
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
        try:
            lock_build_request(target)
        except GenerationFenced as exc:
            raise VectorStoreError(exc.code) from exc
        # One ordered lock protocol fences retirement and target sealing for both layouts.
        locked = {
            item.pk: item
            for item in IndexVersion.objects.select_for_update()
            .filter(pk__in=[parent.pk, target.pk], organization_id=target.organization_id)
            .order_by("pk")
        }
        if len(locked) != 2:
            raise VectorStoreError("VECTOR_COPY_GENERATION_INVALID")
        if any(locked[item.pk].storage_layout != item.storage_layout for item in (parent, target)):
            raise VectorStoreError("VECTOR_COPY_LAYOUT_CHANGED")
        source_filter, source_params = _generation_filter(parent)
        target_columns = (
            "organization_id, document_version_id, ordinal, text, chunk_kind, embedding"
        )
        source_columns = target_columns
        params: list[Any] = []
        if target.storage_layout == "shared_v1":
            current = locked[target.pk]
            if current.status != "building" or current.storage_state != "open":
                raise VectorStoreError("SHARED_CHUNK_NOT_WRITABLE")
            try:
                geometry = shared_geometry(current.index_type, current.dimensions)
            except ValueError as exc:
                raise VectorStoreError(str(exc)) from exc
            target_columns += ", index_version_id, dimensions, representation, created_at"
            # Preserve the existing halfvec quantization when copying legacy stores.
            source_columns = (
                "organization_id, document_version_id, ordinal, text, chunk_kind, embedding::vector"
                ", %s, %s, %s, CURRENT_TIMESTAMP"
            )
            params.extend([target.pk, geometry.dimensions, geometry.representation])
        elif parent.storage_layout == "shared_v1":
            # A rolling old writer cannot silently bring a migrated lineage back to dynamic DDL.
            raise VectorStoreError("VECTOR_COPY_LAYOUT_DOWNGRADE")
        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO "{target_name}" '  # noqa: S608
                f"({target_columns}) SELECT {source_columns} "
                f'FROM "{parent_name}" '  # noqa: S608
                f"WHERE organization_id = %s AND document_version_id = ANY(%s) {source_filter}",
                [*params, target.organization_id, ids, *source_params],
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
    geometry_predicate = ""
    embedding_expression = "embedding"
    indexed_document_column = "NULL::bigint"
    use_exact = False
    if index_version.storage_layout == "shared_v1":
        try:
            geometry = shared_geometry(index_version.index_type, index_version.dimensions)
        except ValueError as exc:
            raise VectorStoreError(str(exc)) from exc
        column_type = geometry.cast
        geometry_predicate = f" AND {geometry.predicate}"
        embedding_expression = f"embedding::{geometry.cast}"
        indexed_document_column = "indexed_document_id"
        # Small sealed corpora are cheaper and more accurate through the scope B-tree
        # plus exact cosine sorting. Bound work by vector elements, including geometry.
        use_exact = (
            index_version.storage_state == "sealed"
            and 0 < index_version.chunk_count * dimensions <= 128_000
        )
    literal = _vector_literal(query_embedding)
    limit = max(1, min(int(top_k), 100))
    filters, filter_params = _search_filters(
        organization_id=organization_id,
        document_version_ids=document_version_ids,
        chunk_kinds=chunk_kinds,
    )
    if filters is None:
        return []
    generation_filter, generation_params = _generation_filter(index_version)
    filters += f" {generation_filter}{geometry_predicate}"
    filter_params.extend(generation_params)
    # Transaction-local tenant context so the RLS policy (ADR-0004) is active during the read; the
    # ``WHERE organization_id`` app predicate is the first layer, RLS the fail-closed backstop.
    with transaction.atomic():
        shared_ann = index_version.storage_layout == "shared_v1" and not use_exact
        if not shared_ann:
            set_tenant_context(int(organization_id))
        with connection.cursor() as cursor:
            if shared_ann:
                # A shared ANN index filters tenant/generation after candidate lookup.
                # pgvector >= 0.8 keeps scanning within these closed, bounded budgets.
                cursor.execute(
                    "SELECT set_config('app.tenant_scope', %s, true), "
                    "set_config('hnsw.iterative_scan', 'strict_order', true), "
                    "set_config('hnsw.ef_search', '200', true), "
                    "set_config('hnsw.max_scan_tuples', '20000', true), "
                    "set_config('hnsw.scan_mem_multiplier', '2', true), "
                    "set_config('plan_cache_mode', 'force_custom_plan', true)",
                    [str(normalize_tenant_scope((int(organization_id),))[0])],
                )
            # "name"/"column_type" are int-derived and validated; values are bound params.
            cursor.execute(
                f"SELECT document_version_id, ordinal, text, chunk_kind, "  # noqa: S608
                f"({embedding_expression} <=> %s::{column_type})"
                f"{' + 0' if use_exact else ''} AS distance, "
                f"{indexed_document_column} "
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
            indexed_document_id=row[5],
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
    indexed_document_column = (
        "indexed_document_id" if index_version.storage_layout == "shared_v1" else "NULL::bigint"
    )
    filters, filter_params = _search_filters(
        organization_id=organization_id,
        document_version_ids=document_version_ids,
        chunk_kinds=chunk_kinds,
    )
    if filters is None:
        return []
    generation_filter, generation_params = _generation_filter(index_version)
    filters += f" {generation_filter}"
    filter_params.extend(generation_params)
    with transaction.atomic():
        set_tenant_context(int(organization_id))
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT document_version_id, ordinal, text, chunk_kind, "  # noqa: S608
                "ts_rank_cd(to_tsvector('simple', text), plainto_tsquery('simple', %s)) AS rank, "
                f"{indexed_document_column} "
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
            indexed_document_id=row[5],
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
    if index_version.storage_layout == "shared_v1":
        with transaction.atomic():
            set_tenant_context(index_version.organization_id)
            return IndexVersion.objects.filter(
                pk=index_version.pk,
                organization_id=index_version.organization_id,
                storage_layout="shared_v1",
                storage_state__in=["open", "sealed"],
            ).exists()
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [name])
        return cursor.fetchone()[0] is not None


def drop_store(index_version: IndexVersion) -> None:
    """Drop a non-active store through the migration-owned, tenant-scoped DDL seam."""
    _require_postgres()
    store_name(index_version)
    if index_version.storage_layout == "shared_v1":
        _retire_shared_store(index_version)
        return
    try:
        with transaction.atomic():
            set_tenant_context(int(index_version.organization_id))
            # The migration-owned function locks and checks receipt references, including
            # direct SQL callers. Runtime keeps its SELECT + EXECUTE-only DDL contract.
            with connection.cursor() as cursor:
                cursor.execute("SELECT agenthub_drop_index_store(%s)", [index_version.pk])
    except DatabaseError as exc:
        raise _normalize_ddl_error(exc) from exc


def _retire_shared_store(index_version: IndexVersion) -> None:
    """Fence failed build cleanup before bounded deletes; never drop a shared relation.

    Served/sealed generations remain retained until the full reference-aware retention
    cutover is verified. This conservative boundary also protects historical citations.
    """
    try:
        with transaction.atomic():
            set_tenant_context(index_version.organization_id)
            current = lock_generation(index_version, require_running=False)
            if current.storage_layout != "shared_v1":
                raise VectorStoreError("VECTOR_COPY_LAYOUT_CHANGED")
            if current.status == "active":
                raise VectorStoreError("INDEX_STORE_ACTIVE")
            if current.store_ready or current.storage_state == "sealed":
                raise VectorStoreError("SHARED_CHUNK_RETENTION_REQUIRED")
            current.storage_state = "retired"
            current.save(update_fields=["storage_state", "updated_at"])
        # The committed fence prevents new writes during and after each bounded batch.
        # A crash leaves a retired, non-serving generation; the same call resumes cleanup.
        while True:
            with transaction.atomic():
                set_tenant_context(index_version.organization_id)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM ingestion_sharedvectorchunk WHERE id IN ("
                        "SELECT id FROM ingestion_sharedvectorchunk "
                        "WHERE organization_id = %s AND index_version_id = %s "
                        "ORDER BY id LIMIT 1000)",
                        [index_version.organization_id, index_version.pk],
                    )
                    if cursor.rowcount == 0:
                        break
        index_version.storage_state = "retired"
    except DatabaseError as exc:
        primary = getattr(getattr(exc.__cause__, "diag", None), "message_primary", "")
        code = (
            primary
            if primary
            in {
                "SHARED_CHUNK_REFERENCED",
                "SHARED_CHUNK_RETIRE_REQUIRED",
            }
            else "SHARED_CHUNK_RETIRE_FAILED"
        )
        raise VectorStoreError(code) from exc
