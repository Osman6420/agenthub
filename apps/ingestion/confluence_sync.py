"""Recoverable Confluence snapshot sync into draft document-set candidates."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.documents.models import Document, DocumentLifecycle, DocumentVersion
from apps.documents.services import (
    DocumentError,
    get_or_create_manual_draft,
    upload_document,
)
from apps.ingestion.confluence import ConfluenceDataCenterClient, ConfluenceError, ConfluencePage
from apps.ingestion.models import (
    ConfluenceCursorState,
    ConfluenceDocumentCursor,
    ConfluenceProfile,
    ConfluenceProfileStatus,
    ConfluenceSyncRun,
    ConfluenceSyncStatus,
    ConnectorType,
    SourceStatus,
    TenantConfluenceProfileGrant,
)
from apps.ingestion.services import source_lock
from apps.ingestion.snapshot import create_material_candidate
from apps.ingestion.vector_store import set_tenant_context


class ConfluenceSyncClient(Protocol):
    @property
    def fetched_bytes(self) -> int: ...

    def iter_pages(
        self,
        profile: ConfluenceProfile,
        *,
        root_page_ids: list[str],
        include_root: bool,
        excluded_page_ids: set[str],
    ) -> Iterator[ConfluencePage]: ...

    def get_page_body(
        self, profile: ConfluenceProfile, page_id: str, root_page_id: str
    ) -> tuple[ConfluencePage, bytes]: ...


def execute_confluence_sync(
    run_id: int,
    *,
    organization_id: int,
    client: ConfluenceSyncClient | None = None,
) -> str:
    run = _claim_run(run_id, organization_id=organization_id)
    if run is None:
        return "not_claimed"
    confluence = client or ConfluenceDataCenterClient()
    try:
        _validate_runtime_grant(run)
        with source_lock(run.source_id) as acquired:
            if not acquired:
                raise ConfluenceError("SOURCE_BUSY")
            _execute_snapshot(run, confluence)
    except (ConfluenceError, DocumentError) as exc:
        code = getattr(exc, "code", str(exc))
        return _fail_run(
            run.pk,
            organization_id=organization_id,
            code=str(code),
            fetched_bytes=confluence.fetched_bytes,
        )
    except Exception:
        return _fail_run(
            run.pk,
            organization_id=organization_id,
            code="CONFLUENCE_INTERNAL_ERROR",
            fetched_bytes=confluence.fetched_bytes,
        )
    return ConfluenceSyncStatus.SUCCEEDED


def _claim_run(run_id: int, *, organization_id: int) -> ConfluenceSyncRun | None:
    with transaction.atomic():
        set_tenant_context(organization_id)
        run = (
            ConfluenceSyncRun.objects.select_for_update(of=("self",))
            .select_related("source", "source__document_set", "confluence_profile")
            .filter(pk=run_id, organization_id=organization_id)
            .first()
        )
        if run is None:
            return None
        if run.status not in {ConfluenceSyncStatus.QUEUED, ConfluenceSyncStatus.RETRY}:
            return None
        run.status = ConfluenceSyncStatus.RUNNING
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
        record_event(
            actor_type=ActorType.SYSTEM,
            actor_id="confluence-worker",
            action="confluence_sync.started",
            outcome=Outcome.SUCCESS,
            organization_id=run.organization_id,
            resource_type="confluence_sync_run",
            resource_id=str(run.pk),
            after={"attempt": run.attempt},
        )
        return run


def _validate_runtime_grant(run: ConfluenceSyncRun) -> None:
    source = run.source
    profile = run.confluence_profile
    if source.connector_type != ConnectorType.CONFLUENCE_DC:
        raise ConfluenceError("CONFLUENCE_SOURCE_REQUIRED")
    if source.status != SourceStatus.ACTIVE:
        raise ConfluenceError("SOURCE_DISABLED")
    if profile.status != ConfluenceProfileStatus.ACTIVE:
        raise ConfluenceError("CONFLUENCE_PROFILE_DISABLED")
    if source.confluence_profile_id != profile.id or not source.document_set_id:
        raise ConfluenceError("CONFLUENCE_SOURCE_BINDING_INVALID")
    with transaction.atomic():
        set_tenant_context(run.organization_id)
        if not TenantConfluenceProfileGrant.objects.filter(
            organization_id=run.organization_id,
            document_set_id=source.document_set_id,
            confluence_profile_id=profile.id,
        ).exists():
            raise ConfluenceError("CONFLUENCE_PROFILE_NOT_GRANTED")


def _execute_snapshot(run: ConfluenceSyncRun, client: ConfluenceSyncClient) -> None:
    source = run.source
    profile = run.confluence_profile
    config = source.connector_config
    discovered = 0
    changed = 0
    unchanged = 0
    for page in client.iter_pages(
        profile,
        root_page_ids=list(config["root_page_ids"]),
        include_root=bool(config["include_root"]),
        excluded_page_ids=set(config["excluded_page_ids"]),
    ):
        discovered += 1
        with transaction.atomic():
            set_tenant_context(run.organization_id)
            cursor = ConfluenceDocumentCursor.objects.filter(
                source=source, external_page_id=page.page_id
            ).first()
        if cursor is not None and cursor.external_version == page.version:
            with transaction.atomic():
                set_tenant_context(run.organization_id)
                cursor.root_page_id = page.root_page_id
                cursor.external_updated_at = page.updated_at
                cursor.last_seen_run = run
                cursor.state = ConfluenceCursorState.ACTIVE
                cursor.save(
                    update_fields=[
                        "root_page_id",
                        "external_updated_at",
                        "last_seen_run",
                        "state",
                        "updated_at",
                    ]
                )
            unchanged += 1
        else:
            body_page, body = client.get_page_body(profile, page.page_id, page.root_page_id)
            if _persist_changed_page(run, body_page, body, cursor):
                changed += 1
            else:
                unchanged += 1
        with transaction.atomic():
            set_tenant_context(run.organization_id)
            ConfluenceSyncRun.objects.filter(pk=run.pk).update(
                discovered_count=discovered,
                changed_count=changed,
                unchanged_count=unchanged,
                fetched_bytes=client.fetched_bytes,
            )

    with transaction.atomic():
        set_tenant_context(run.organization_id)
        missing = ConfluenceDocumentCursor.objects.filter(
            source=source, state=ConfluenceCursorState.ACTIVE
        ).exclude(last_seen_run=run)
        missing_count = missing.count()
        missing.update(state=ConfluenceCursorState.MISSING)
        document_set = source.document_set
        if document_set is None:
            raise ConfluenceError("CONFLUENCE_SOURCE_BINDING_INVALID")
        active_cursors = list(
            ConfluenceDocumentCursor.objects.filter(
                source=source,
                state=ConfluenceCursorState.ACTIVE,
                last_seen_run=run,
                document__deleted_at__isnull=True,
            )
            .select_related("document_version")
            .order_by("external_page_id")
        )
        candidate = create_material_candidate(
            document_set=document_set,
            source_id=source.pk,
            source_document_version_ids=(cursor.document_version_id for cursor in active_cursors),
            actor="confluence-worker",
        )
        locked = ConfluenceSyncRun.objects.select_for_update().get(pk=run.pk)
        locked.status = ConfluenceSyncStatus.SUCCEEDED
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
        record_event(
            actor_type=ActorType.SYSTEM,
            actor_id="confluence-worker",
            action="confluence_sync.succeeded",
            outcome=Outcome.SUCCESS,
            organization_id=locked.organization_id,
            resource_type="confluence_sync_run",
            resource_id=str(locked.pk),
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


def _persist_changed_page(
    run: ConfluenceSyncRun,
    page: ConfluencePage,
    body: bytes,
    existing_cursor: ConfluenceDocumentCursor | None,
) -> bool:
    source = run.source
    logical_id = f"confluence-{source.pk}-{page.page_id}"
    checksum = hashlib.sha256(body).hexdigest()
    document = Document.objects.filter(
        organization_id=run.organization_id, logical_id=logical_id
    ).first()
    if document is not None:
        if document.source_id != source.id:
            raise ConfluenceError("CONFLUENCE_DOCUMENT_ID_CONFLICT")
        if document.lifecycle_state != DocumentLifecycle.ACTIVE:
            raise ConfluenceError("CONFLUENCE_DOCUMENT_TOMBSTONED")
    reusable = _reusable_crash_version(document, existing_cursor, checksum)
    if reusable is None:
        if source.document_set is None:
            raise ConfluenceError("CONFLUENCE_SOURCE_SET_REQUIRED")
        draft = get_or_create_manual_draft(
            document_set=source.document_set,
            actor="confluence-worker",
        )
        version = upload_document(
            organization=source.organization,
            logical_id=logical_id,
            title=page.title,
            mime_type="text/html",
            data=body,
            actor="confluence-worker",
            document_set_version=draft,
            source=source,
        )
        document = version.document
        material_change = True
    else:
        version = reusable
        document = reusable.document
        if page.title and document.title != page.title:
            document.title = page.title
            document.save(update_fields=["title", "updated_at"])
        material_change = (
            existing_cursor is None or existing_cursor.document_version_id != version.pk
        )

    with transaction.atomic():
        set_tenant_context(run.organization_id)
        cursor = (
            ConfluenceDocumentCursor.objects.select_for_update()
            .filter(source=source, external_page_id=page.page_id)
            .first()
        )
        if cursor is None:
            cursor = ConfluenceDocumentCursor(
                organization_id=run.organization_id,
                source=source,
                external_page_id=page.page_id,
                root_page_id=page.root_page_id,
                external_version=page.version,
                external_updated_at=page.updated_at,
                document=document,
                document_version=version,
                last_seen_run=run,
                state=ConfluenceCursorState.ACTIVE,
            )
        else:
            cursor.root_page_id = page.root_page_id
            cursor.external_version = page.version
            cursor.external_updated_at = page.updated_at
            cursor.document = document
            cursor.document_version = version
            cursor.last_seen_run = run
            cursor.state = ConfluenceCursorState.ACTIVE
        cursor.full_clean(validate_unique=False, validate_constraints=False)
        cursor.save()
    return material_change


def _reusable_crash_version(
    document: Document | None,
    cursor: ConfluenceDocumentCursor | None,
    checksum: str,
) -> DocumentVersion | None:
    if document is None or document.current_version < 1:
        return None
    latest = DocumentVersion.objects.filter(
        document=document, version=document.current_version, checksum=checksum
    ).first()
    if latest is None:
        return None
    return latest


def _fail_run(run_id: int, *, organization_id: int, code: str, fetched_bytes: int) -> str:
    with transaction.atomic():
        set_tenant_context(organization_id)
        run = ConfluenceSyncRun.objects.select_for_update().get(pk=run_id)
        if run.organization_id != organization_id:
            raise ConfluenceError("CONFLUENCE_RUN_TENANT_MISMATCH")
        terminal = run.attempt >= run.max_attempts
        run.status = ConfluenceSyncStatus.DEAD_LETTER if terminal else ConfluenceSyncStatus.RETRY
        run.error_code = code[:64]
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
        record_event(
            actor_type=ActorType.SYSTEM,
            actor_id="confluence-worker",
            action=(
                "confluence_sync.dead_letter" if terminal else "confluence_sync.retry_scheduled"
            ),
            outcome=Outcome.FAILURE,
            organization_id=run.organization_id,
            resource_type="confluence_sync_run",
            resource_id=str(run.pk),
            reason=run.error_code,
            after={"attempt": run.attempt, "fetched_bytes": fetched_bytes},
        )
        return run.status
