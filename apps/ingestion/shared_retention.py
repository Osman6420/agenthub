"""Preview or reclaim one bounded batch without deleting metadata or evidence."""

from dataclasses import dataclass
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.ingestion.models import IndexVersion, SharedVectorChunk
from apps.ingestion.vector_store import VectorStoreError
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization


@dataclass(frozen=True)
class RetentionResult:
    index_version_id: int
    eligible: bool
    reason: str
    deleted: int
    remaining: int


def reclaim_shared_generation(
    *,
    organization_id: int,
    index_version_id: int,
    actor: str,
    apply: bool = False,
    batch_size: int = 1000,
) -> RetentionResult:
    if connection.vendor != "postgresql":
        raise VectorStoreError("VECTOR_STORE_REQUIRES_POSTGRES")
    if (
        type(batch_size) is not int
        or not 1 <= batch_size <= 1000
        or not actor
        or len(actor) > 150
        or type(apply) is not bool
    ):
        raise VectorStoreError("SHARED_RETENTION_INPUT_INVALID")
    with transaction.atomic():
        set_tenant_context(organization_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user) "
                "FROM pg_class c WHERE c.oid = 'public.ingestion_sharedvectorchunk'::regclass"
            )
            owner = cursor.fetchone()
            if not owner or not owner[0]:
                raise VectorStoreError("SHARED_RETENTION_OWNER_REQUIRED")
        Organization.objects.select_for_update(no_key=True).get(pk=organization_id)
        index = (
            IndexVersion.objects.select_for_update()
            .filter(pk=index_version_id, organization_id=organization_id)
            .first()
        )
        if index is None:
            raise VectorStoreError("SHARED_RETENTION_NOT_FOUND")
        if index.storage_layout != "shared_v1":
            raise VectorStoreError("SHARED_RETENTION_LAYOUT_UNSUPPORTED")
        chunks = SharedVectorChunk.objects.filter(
            organization_id=organization_id, index_version_id=index.pk
        )
        remaining = chunks.count()
        with connection.cursor() as cursor:
            cursor.execute("SELECT public.agenthub_shared_retention_blocked(%s)", [index.pk])
            blocked = cursor.fetchone()[0]
        reason = ""
        if blocked:
            reason = "SHARED_RETENTION_REFERENCED"
        elif index.storage_state not in {"sealed", "retired"}:
            reason = "SHARED_RETENTION_NOT_SEALED"
        elif index.storage_state != "retired" and index.updated_at > timezone.now() - timedelta(
            days=90
        ):
            reason = "SHARED_RETENTION_TOO_RECENT"
        if reason or not apply:
            return RetentionResult(index.pk, not reason, reason, 0, remaining)
        retired_now = index.storage_state != "retired"
        if retired_now:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.shared_vector_retention', 'on', true)")
            index.storage_state = "retired"
            index.store_ready = False
            index.save(update_fields=["storage_state", "store_ready", "updated_at"])
        ids = list(chunks.order_by("pk").values_list("pk", flat=True)[:batch_size])
        deleted, _ = chunks.filter(pk__in=ids).delete()
        if deleted or retired_now:
            record_event(
                actor_type="system",
                actor_id=actor,
                organization_id=organization_id,
                action="ingestion.shared_generation.reclaimed",
                outcome="success",
                resource_type="index_version",
                resource_id=str(index.pk),
                after={"deleted_chunks": deleted, "remaining_chunks": remaining - deleted},
            )
        return RetentionResult(index.pk, True, "", deleted, remaining - deleted)
