"""Recoverable generic REST snapshot sync into immutable document lineage."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.documents.models import (
    Document,
    DocumentLifecycle,
    DocumentSetStatus,
    DocumentVersion,
)
from apps.documents.services import DocumentError, get_or_create_manual_draft, upload_document
from apps.ingestion.connector_jobs import (
    cleanup_connector_uploads,
    complete_connector_snapshot,
    connector_write,
)
from apps.ingestion.models import (
    ConnectorType,
    RestDocumentCursor,
    RestPullContract,
    RestPullContractStatus,
    RestPullProfile,
    RestPullProfileStatus,
    RestSyncRun,
    RestSyncStatus,
    SourceStatus,
    StagedIndexBuildJob,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest import GovernedRestClient, RestPullError, RestPullItem
from apps.ingestion.services import source_lock
from apps.ingestion.snapshot import create_material_candidate
from apps.ingestion.vector_store import set_tenant_context


class RestSyncClient(Protocol):
    @property
    def fetched_bytes(self) -> int: ...

    def iter_items(
        self,
        profile: RestPullProfile,
        contract: RestPullContract,
        *,
        inputs: dict[str, object],
    ) -> Iterator[RestPullItem]: ...

    def get_content(
        self,
        profile: RestPullProfile,
        contract: RestPullContract,
        item: RestPullItem,
        *,
        inputs: dict[str, object],
    ) -> bytes: ...


def execute_rest_sync(
    run_id: int,
    *,
    organization_id: int,
    client: RestSyncClient | None = None,
) -> str:
    run = _claim_run(run_id, organization_id=organization_id)
    if run is None:
        return "not_claimed"
    rest = client or GovernedRestClient()
    try:
        _validate_runtime_grant(run)
        with source_lock(run.source_id) as acquired:
            if not acquired:
                raise RestPullError("SOURCE_BUSY")
            _execute_snapshot(run, rest)
    except (RestPullError, DocumentError) as exc:
        return _fail_run(
            run.pk,
            organization_id=organization_id,
            code=getattr(exc, "code", "REST_SYNC_FAILED"),
            fetched_bytes=rest.fetched_bytes,
        )
    except Exception:
        return _fail_run(
            run.pk,
            organization_id=organization_id,
            code="REST_INTERNAL_ERROR",
            fetched_bytes=rest.fetched_bytes,
        )
    return RestSyncStatus.SUCCEEDED


def _claim_run(run_id: int, *, organization_id: int) -> RestSyncRun | None:
    with transaction.atomic():
        set_tenant_context(organization_id)
        if StagedIndexBuildJob.objects.filter(
            organization_id=organization_id, rest_sync_run_id=run_id
        ).exists():
            return None
        run = (
            RestSyncRun.objects.select_for_update(of=("self",))
            .select_related(
                "source",
                "source__document_set",
                "rest_profile",
                "rest_contract",
                "schedule",
            )
            .filter(pk=run_id, organization_id=organization_id)
            .first()
        )
        if run is None or run.status not in {RestSyncStatus.QUEUED, RestSyncStatus.RETRY}:
            return None
        if (
            run.source.document_set is None
            or run.source.document_set.status != DocumentSetStatus.ACTIVE
        ):
            return None
        run.status = RestSyncStatus.RUNNING
        run.attempt += 1
        run.error_code = ""
        run.snapshot_complete = False
        run.started_at = timezone.now()
        run.finished_at = None
        run.save(
            update_fields=[
                "status",
                "attempt",
                "error_code",
                "snapshot_complete",
                "started_at",
                "finished_at",
                "updated_at",
            ]
        )
        _audit_run(run, "rest_sync.started", Outcome.SUCCESS, after={"attempt": run.attempt})
        return run


def _validate_runtime_grant(run: RestSyncRun) -> None:
    from apps.ingestion.connections import ConnectionError, verify_source_connection

    source = run.source
    from apps.ingestion.rest_services import RestServiceError
    from apps.ingestion.source_revisions import assert_revision_sync

    try:
        assert_revision_sync(source, scheduled=run.schedule_id is not None)
    except RestServiceError as exc:
        raise RestPullError(exc.code) from exc
    try:
        connection_profile = verify_source_connection(source)
    except ConnectionError as exc:
        raise RestPullError(exc.code) from None
    if connection_profile is not None and connection_profile.status != RestPullProfileStatus.ACTIVE:
        raise RestPullError("REST_PROFILE_DISABLED")
    if source.connector_type != ConnectorType.GENERIC_REST:
        raise RestPullError("REST_SOURCE_REQUIRED")
    if source.status != SourceStatus.ACTIVE:
        raise RestPullError("SOURCE_DISABLED")
    if run.rest_profile.status != RestPullProfileStatus.ACTIVE:
        raise RestPullError("REST_PROFILE_DISABLED")
    if run.rest_contract.status != RestPullContractStatus.ACTIVE:
        raise RestPullError("REST_CONTRACT_DISABLED")
    if (
        source.rest_profile_id != run.rest_profile_id
        or source.rest_contract_id != run.rest_contract_id
        or not source.document_set_id
    ):
        raise RestPullError("REST_SOURCE_BINDING_INVALID")
    with transaction.atomic():
        set_tenant_context(run.organization_id)
        if not TenantRestPullProfileGrant.objects.filter(
            organization_id=run.organization_id,
            document_set_id=source.document_set_id,
            rest_profile_id=run.rest_profile_id,
        ).exists():
            raise RestPullError("REST_PROFILE_NOT_GRANTED")


def _execute_snapshot(run: RestSyncRun, client: RestSyncClient) -> None:
    with connector_write(run):
        pass
    source = run.source
    inputs = dict(source.connector_config["inputs"])
    discovered = changed = unchanged = 0
    seen_external_ids: set[str] = set()
    for item in client.iter_items(run.rest_profile, run.rest_contract, inputs=inputs):
        if item.external_id in seen_external_ids:
            raise RestPullError("REST_DUPLICATE_EXTERNAL_ID")
        seen_external_ids.add(item.external_id)
        discovered += 1
        with connector_write(run):
            cursor = RestDocumentCursor.objects.filter(
                source=source, external_id=item.external_id
            ).first()
        if item.deleted:
            if cursor is not None:
                _mark_cursor(cursor, run=run, revision=item.revision, state="missing")
            unchanged += 1
        elif cursor is not None and item.revision and cursor.external_revision == item.revision:
            _mark_cursor(cursor, run=run, revision=item.revision, state="active")
            unchanged += 1
        else:
            content = client.get_content(run.rest_profile, run.rest_contract, item, inputs=inputs)
            if _persist_item(run, item, content, cursor):
                changed += 1
            else:
                unchanged += 1
        with connector_write(run):
            RestSyncRun.objects.filter(pk=run.pk).update(
                discovered_count=discovered,
                changed_count=changed,
                unchanged_count=unchanged,
                fetched_bytes=client.fetched_bytes,
            )

    with connector_write(run):
        missing = RestDocumentCursor.objects.filter(source=source, state="active").exclude(
            last_seen_run=run
        )
        missing_count = missing.count()
        missing.update(state="missing")
        document_set = source.document_set
        if document_set is None:
            raise RestPullError("REST_SOURCE_BINDING_INVALID")
        active_ids = list(
            RestDocumentCursor.objects.filter(
                source=source,
                state="active",
                last_seen_run=run,
                document__deleted_at__isnull=True,
            )
            .order_by("external_id")
            .values_list("document_version_id", flat=True)
        )
        candidate = create_material_candidate(
            document_set=document_set,
            source_id=source.pk,
            source_document_version_ids=active_ids,
            actor="rest-worker",
        )
        complete_connector_snapshot(run)
        locked = RestSyncRun.objects.select_for_update().get(pk=run.pk)
        locked.status = RestSyncStatus.SUCCEEDED
        locked.snapshot_complete = True
        locked.material_change = candidate is not None
        locked.discovered_count = discovered
        locked.changed_count = changed
        locked.unchanged_count = unchanged
        locked.missing_count = missing_count
        locked.fetched_bytes = client.fetched_bytes
        locked.candidate_set_version = candidate
        locked.finished_at = timezone.now()
        locked.save(
            update_fields=[
                "status",
                "snapshot_complete",
                "material_change",
                "discovered_count",
                "changed_count",
                "unchanged_count",
                "missing_count",
                "fetched_bytes",
                "candidate_set_version",
                "finished_at",
                "updated_at",
            ]
        )
        _audit_run(
            locked,
            "rest_sync.succeeded" if candidate else "rest_sync.noop",
            Outcome.SUCCESS,
            after={
                "candidate_set_version_id": candidate.pk if candidate else None,
                "material_change": candidate is not None,
                "discovered_count": discovered,
                "changed_count": changed,
                "unchanged_count": unchanged,
                "missing_count": missing_count,
                "fetched_bytes": client.fetched_bytes,
            },
        )


def _persist_item(
    run: RestSyncRun,
    item: RestPullItem,
    content: bytes,
    existing_cursor: RestDocumentCursor | None,
) -> bool:
    created_keys: list[str] = []
    try:
        with connector_write(run):
            return _persist_item_locked(run, item, content, existing_cursor, created_keys)
    except Exception:
        cleanup_connector_uploads(organization_id=run.organization_id, created_keys=created_keys)
        raise


def _persist_item_locked(
    run: RestSyncRun,
    item: RestPullItem,
    content: bytes,
    existing_cursor: RestDocumentCursor | None,
    created_keys: list[str],
) -> bool:
    source = run.source
    checksum = hashlib.sha256(content).hexdigest()
    if existing_cursor is not None and existing_cursor.content_checksum == checksum:
        _mark_cursor(existing_cursor, run=run, revision=item.revision, state="active")
        if item.title and existing_cursor.document.title != item.title:
            existing_cursor.document.title = item.title
            existing_cursor.document.save(update_fields=["title", "updated_at"])
        return False
    logical_id = f"rest-{source.pk}-{hashlib.sha256(item.external_id.encode()).hexdigest()[:32]}"
    document = Document.objects.filter(
        organization_id=run.organization_id, logical_id=logical_id
    ).first()
    if document is not None:
        if document.source_id != source.id:
            raise RestPullError("REST_DOCUMENT_ID_CONFLICT")
        if document.lifecycle_state != DocumentLifecycle.ACTIVE:
            raise RestPullError("REST_DOCUMENT_TOMBSTONED")
    version = _reusable_version(document, checksum)
    if version is None:
        if source.document_set is None:
            raise RestPullError("REST_SOURCE_SET_REQUIRED")
        draft = get_or_create_manual_draft(
            document_set=source.document_set,
            actor="rest-worker",
        )
        version = upload_document(
            organization=source.organization,
            logical_id=logical_id,
            title=item.title,
            mime_type=run.rest_contract.definition["response"]["mime_type"],
            data=content,
            actor="rest-worker",
            document_set_version=draft,
            source=source,
        )
        created_keys.append(version.object_key)
    with transaction.atomic():
        set_tenant_context(run.organization_id)
        cursor = (
            RestDocumentCursor.objects.select_for_update()
            .filter(source=source, external_id=item.external_id)
            .first()
        )
        if cursor is None:
            cursor = RestDocumentCursor(
                organization_id=run.organization_id,
                source=source,
                external_id=item.external_id,
                external_revision=item.revision,
                content_checksum=checksum,
                document=version.document,
                document_version=version,
                last_seen_run=run,
                state="active",
            )
        else:
            cursor.external_revision = item.revision
            cursor.content_checksum = checksum
            cursor.document = version.document
            cursor.document_version = version
            cursor.last_seen_run = run
            cursor.state = "active"
        cursor.full_clean(validate_unique=False, validate_constraints=False)
        cursor.save()
    return existing_cursor is None or existing_cursor.document_version_id != version.pk


def _mark_cursor(
    cursor: RestDocumentCursor, *, run: RestSyncRun, revision: str, state: str
) -> None:
    with connector_write(run):
        locked = RestDocumentCursor.objects.select_for_update().get(pk=cursor.pk)
        locked.external_revision = revision
        locked.last_seen_run = run
        locked.state = state
        locked.save(update_fields=["external_revision", "last_seen_run", "state", "updated_at"])


def _reusable_version(document: Document | None, checksum: str) -> DocumentVersion | None:
    if document is None or document.current_version < 1:
        return None
    return DocumentVersion.objects.filter(
        document=document, version=document.current_version, checksum=checksum
    ).first()


def _fail_run(run_id: int, *, organization_id: int, code: str, fetched_bytes: int) -> str:
    with transaction.atomic():
        set_tenant_context(organization_id)
        run = RestSyncRun.objects.select_for_update().get(pk=run_id)
        terminal = run.attempt >= run.max_attempts or code == "REST_POST_OUTCOME_UNKNOWN"
        run.status = RestSyncStatus.DEAD_LETTER if terminal else RestSyncStatus.RETRY
        run.error_code = str(code)[:64]
        run.snapshot_complete = False
        run.fetched_bytes = fetched_bytes
        run.finished_at = timezone.now() if terminal else None
        run.save(
            update_fields=[
                "status",
                "error_code",
                "snapshot_complete",
                "fetched_bytes",
                "finished_at",
                "updated_at",
            ]
        )
        _audit_run(
            run,
            "rest_sync.dead_letter" if terminal else "rest_sync.retry_scheduled",
            Outcome.FAILURE,
            reason=run.error_code,
            after={"attempt": run.attempt, "fetched_bytes": fetched_bytes},
        )
        return run.status


def _audit_run(
    run: RestSyncRun,
    action: str,
    outcome: str,
    *,
    reason: str = "",
    after: dict[str, object] | None = None,
) -> None:
    record_event(
        actor_type=ActorType.SYSTEM,
        actor_id="rest-worker",
        action=action,
        outcome=outcome,
        organization_id=run.organization_id,
        resource_type="rest_sync_run",
        resource_id=str(run.pk),
        reason=reason,
        after=after,
    )
