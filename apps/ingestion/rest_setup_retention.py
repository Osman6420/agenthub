"""Owner-operated expiry maintenance; preserve receipts, clear only private draft content."""

import re
from dataclasses import dataclass
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.db.models import F

from apps.audit.services import record_event
from apps.ingestion.models import RestSetupDraft
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization

MAX_BATCH_SIZE = 500


class RestSetupRetentionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RetentionResult:
    candidates: int
    purged: int
    has_more: bool


def purge_expired_setup_drafts(
    *, organization_id: int, actor: str, apply: bool = False, batch_size: int = 100
) -> RetentionResult:
    """Preview one batch by default. Only the table owner may explicitly apply it."""
    if (
        type(organization_id) is not int
        or not 1 <= organization_id <= 2**63 - 1
        or not isinstance(actor, str)
        or re.fullmatch(r"[A-Za-z0-9_.:@-]{1,150}", actor) is None
        or type(apply) is not bool
        or type(batch_size) is not int
        or not 1 <= batch_size <= MAX_BATCH_SIZE
    ):
        raise RestSetupRetentionError("REST_SETUP_RETENTION_INPUT_INVALID")
    if connection.vendor != "postgresql":
        raise RestSetupRetentionError("REST_SETUP_RETENTION_REQUIRES_POSTGRESQL")
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_get_userbyid(relowner) = current_user FROM pg_class "
                    "WHERE oid = 'public.ingestion_restsetupdraft'::regclass"
                )
                if not cursor.fetchone()[0]:
                    raise RestSetupRetentionError("REST_SETUP_RETENTION_OWNER_REQUIRED")
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '30s'")
            set_tenant_context(organization_id)
            if (
                not Organization.objects.select_for_update(no_key=True)
                .filter(pk=organization_id)
                .exists()
            ):
                raise RestSetupRetentionError("REST_SETUP_RETENTION_ORGANIZATION_UNAVAILABLE")
            with connection.cursor() as cursor:
                cursor.execute("SELECT statement_timestamp()")
                cutoff = cursor.fetchone()[0]
            request_id = str(uuid4())
            rows = list(
                RestSetupDraft.objects.select_for_update()
                .filter(
                    organization_id=organization_id,
                    expires_at__lte=cutoff,
                    completed_source__isnull=True,
                    payload_purged_at__isnull=True,
                )
                .only("pk", "public_id", "revision", "expires_at")
                .order_by("expires_at", "pk")[: batch_size + 1]
            )
            candidates = rows[:batch_size]
            if apply:
                for draft in candidates:
                    RestSetupDraft.objects.filter(
                        pk=draft.pk, organization_id=organization_id
                    ).update(
                        payload={},
                        name="",
                        payload_purged_at=cutoff,
                        revision=F("revision") + 1,
                        updated_at=cutoff,
                    )
                    record_event(
                        actor_type="system",
                        actor_id=actor,
                        action="rest_setup_draft.payload_purged",
                        outcome="success",
                        organization_id=organization_id,
                        resource_type="rest_setup_draft",
                        resource_id=str(draft.public_id),
                        reason="SETUP_RETENTION_EXPIRED",
                        request_id=request_id,
                        before={"revision": draft.revision},
                        after={"revision": draft.revision + 1},
                    )
            return RetentionResult(
                candidates=len(candidates),
                purged=len(candidates) if apply else 0,
                has_more=len(rows) > batch_size,
            )
    except DatabaseError:
        raise RestSetupRetentionError("REST_SETUP_RETENTION_DATABASE_UNAVAILABLE") from None
