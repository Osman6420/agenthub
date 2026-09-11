"""Owner-only, resumable additive backfill; no providers, DDL or legacy deletion.

Each invocation copies at most one bounded batch. A generation switches layout only
after exact content/vector identity checks; historical integer/document pointers stay.
The deployment runbook still requires compatible reader/writer drain before cutover.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.db import DatabaseError, connection, transaction

from apps.audit.services import record_event
from apps.ingestion.models import IndexVersion
from apps.ingestion.vector_geometry import shared_geometry
from apps.ingestion.vector_store import VectorStoreError, store_name
from apps.tenancy.context import set_tenant_context

_ORDER = "document_version_id NULLS FIRST, indexed_document_id NULLS FIRST, ordinal, chunk_kind"


@dataclass(frozen=True)
class BackfillResult:
    index_version_id: int
    copied: int
    remaining: int
    verified: bool
    switched: bool
    checksum: str = ""


def _source(index: IndexVersion) -> tuple[str, list[int]]:
    if index.document_set_version_id:
        if not index.store_ready:
            raise VectorStoreError("SHARED_BACKFILL_SOURCE_NOT_READY")
        # Passing the validated integer deliberately resolves the old physical relation.
        name = store_name(index.pk)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)", [name])
            if cursor.fetchone()[0] is None:
                raise VectorStoreError("SHARED_BACKFILL_SOURCE_MISSING")
            # Prevent any old writer from changing the source during this batch/verification.
            cursor.execute(f'LOCK TABLE "{name}" IN SHARE MODE')  # noqa: S608
        return (
            f"SELECT document_version_id, NULL::bigint AS indexed_document_id, ordinal, "  # noqa: S608
            f'chunk_kind, text, embedding::vector::text AS embedding_value FROM "{name}" '
            "WHERE organization_id = %s",
            [index.organization_id],
        )
    if not index.source_id:
        raise VectorStoreError("SHARED_BACKFILL_LINEAGE_INVALID")
    return (
        "SELECT NULL::bigint AS document_version_id, document_id AS indexed_document_id, "
        "ordinal, 'content'::text AS chunk_kind, text, embedding::vector::text AS embedding_value "
        "FROM ingestion_chunk WHERE organization_id = %s AND index_version_id = %s",
        [index.organization_id, index.pk],
    )


def _identity_checksum(sql: str, params: list[int]) -> str:
    digest = hashlib.sha256()
    with connection.cursor() as cursor:
        # Hash content inside PostgreSQL; neither text nor vectors enter operator output.
        cursor.execute(
            "SELECT encode(sha256(convert_to(row_to_json(s)::text, 'UTF8')), 'hex') "  # noqa: S608
            f"FROM ({sql}) s ORDER BY {_ORDER}",
            params,
        )
        while rows := cursor.fetchmany(1000):
            for row in rows:
                digest.update(row[0].encode("ascii"))
    return digest.hexdigest()


def backfill_generation(
    *,
    index_version_id: int,
    organization_id: int,
    actor: str,
    apply: bool = False,
    batch_size: int = 1000,
) -> BackfillResult:
    """Preview or import one stable generation under the migration owner's DB identity."""
    if connection.vendor != "postgresql":
        raise VectorStoreError("VECTOR_STORE_REQUIRES_POSTGRES")
    if not actor or len(actor) > 150 or isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
        raise VectorStoreError("SHARED_BACKFILL_INPUT_INVALID")
    try:
        with transaction.atomic():
            set_tenant_context(organization_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user) "
                    "FROM pg_class c WHERE c.oid = 'ingestion_sharedvectorchunk'::regclass"
                )
                if not cursor.fetchone()[0]:
                    raise VectorStoreError("SHARED_BACKFILL_OWNER_REQUIRED")
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '30s'")
            index = IndexVersion.objects.select_for_update().get(
                pk=index_version_id, organization_id=organization_id
            )
            if index.status not in {"promotable", "active", "superseded"}:
                raise VectorStoreError("SHARED_BACKFILL_GENERATION_BUSY")
            dimensions = index.dimensions if index.dimensions is not None else 64
            representation = index.index_type or "vector"
            try:
                geometry = shared_geometry(representation, dimensions)
            except ValueError as exc:
                raise VectorStoreError(str(exc)) from exc
            source_sql, source_params = _source(index)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM ({source_sql}) s",  # noqa: S608
                    source_params,
                )
                if int(cursor.fetchone()[0]) != index.chunk_count:
                    raise VectorStoreError("SHARED_BACKFILL_COUNT_MISMATCH")
            target_sql = (
                "SELECT document_version_id, indexed_document_id, ordinal, chunk_kind, text, "
                "embedding::vector::text AS embedding_value FROM ingestion_sharedvectorchunk "
                "WHERE organization_id = %s AND index_version_id = %s"
            )
            target_params = [organization_id, index.pk]
            missing = (
                f"SELECT s.* FROM ({source_sql}) s WHERE NOT EXISTS ("  # noqa: S608
                "SELECT 1 FROM ingestion_sharedvectorchunk t WHERE "
                "t.organization_id = %s AND t.index_version_id = %s "
                "AND t.document_version_id IS NOT DISTINCT FROM s.document_version_id "
                "AND t.indexed_document_id IS NOT DISTINCT FROM s.indexed_document_id "
                "AND t.ordinal = s.ordinal AND t.chunk_kind = s.chunk_kind)"
            )
            copied = 0
            with connection.cursor() as cursor:
                if apply and index.storage_layout == "legacy":
                    cursor.execute("SELECT set_config('app.shared_vector_backfill', 'on', true)")
                    cursor.execute(
                        "INSERT INTO ingestion_sharedvectorchunk (organization_id, "  # noqa: S608
                        "index_version_id, document_version_id, indexed_document_id, ordinal, "
                        "chunk_kind, text, embedding, dimensions, representation, created_at) "
                        "SELECT %s, %s, s.document_version_id, s.indexed_document_id, s.ordinal, "
                        "s.chunk_kind, s.text, s.embedding_value::vector, "
                        "%s, %s, CURRENT_TIMESTAMP "
                        f"FROM ({missing} ORDER BY {_ORDER} LIMIT %s) s",
                        [
                            organization_id,
                            index.pk,
                            geometry.dimensions,
                            geometry.representation,
                            *source_params,
                            *target_params,
                            batch_size,
                        ],
                    )
                    copied = cursor.rowcount
                    cursor.execute("SELECT set_config('app.shared_vector_backfill', '', true)")
                cursor.execute(
                    f"SELECT COUNT(*) FROM ({missing}) s",  # noqa: S608
                    [*source_params, *target_params],
                )
                remaining = int(cursor.fetchone()[0])
                verified = False
                checksum = ""
                if remaining == 0:
                    # EXCEPT ALL also detects duplicate identities and extra/stale target rows.
                    cursor.execute(
                        f"SELECT EXISTS((({source_sql}) EXCEPT ALL ({target_sql})) "  # noqa: S608
                        f"UNION ALL (({target_sql}) EXCEPT ALL ({source_sql})))",
                        [*source_params, *target_params, *target_params, *source_params],
                    )
                    if cursor.fetchone()[0]:
                        raise VectorStoreError("SHARED_BACKFILL_MISMATCH")
                    verified = True
                    checksum = _identity_checksum(source_sql, source_params)
            switched = False
            if verified and apply and index.storage_layout == "legacy":
                # Normalize the legacy ORM's implicit 64D geometry without re-embedding.
                index.dimensions = dimensions
                index.index_type = representation
                index.storage_layout = "shared_v1"
                index.storage_state = "sealed"
                index.store_ready = True
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.shared_vector_backfill', 'on', true)")
                    index.save(
                        update_fields=[
                            "dimensions",
                            "index_type",
                            "storage_layout",
                            "storage_state",
                            "store_ready",
                            "updated_at",
                        ]
                    )
                    cursor.execute("SELECT set_config('app.shared_vector_backfill', '', true)")
                switched = True
            if apply:
                record_event(
                    actor_type="system",
                    actor_id=actor,
                    organization_id=organization_id,
                    action="ingestion.shared_vector.backfill",
                    outcome="success",
                    resource_type="index_version",
                    resource_id=str(index.pk),
                    reason="VERIFIED_AND_SWITCHED" if switched else "BATCH_PERSISTED",
                    after={
                        "copied": copied,
                        "remaining": remaining,
                        "verified": verified,
                        "checksum": checksum,
                    },
                )
            return BackfillResult(index.pk, copied, remaining, verified, switched, checksum)
    except IndexVersion.DoesNotExist as exc:
        raise VectorStoreError("SHARED_BACKFILL_GENERATION_NOT_FOUND") from exc
    except DatabaseError as exc:
        raise VectorStoreError("SHARED_BACKFILL_REJECTED") from exc
