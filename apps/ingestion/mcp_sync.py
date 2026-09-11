"""Resource snapshots use the common ingestion job, document services and candidate assembly."""

from __future__ import annotations

import hashlib

from django.db.models import Q

from apps.documents.models import Document, DocumentLifecycle, DocumentVersion
from apps.documents.services import get_or_create_manual_draft, upload_document
from apps.ingestion.connector_jobs import (
    cleanup_connector_uploads,
    complete_connector_snapshot,
    connector_write,
)
from apps.ingestion.mcp_resources import (
    McpResourceClient,
    McpResourceDocument,
    McpResourceError,
    McpResourceLimits,
)
from apps.ingestion.mcp_services import validate_mcp_source
from apps.ingestion.models import ResourceSnapshot, SourceDocumentCursor, StagedIndexBuildJob
from apps.ingestion.snapshot import create_material_candidate
from apps.tools.secrets_resolver import EnvSecretResolver, SecretResolutionError


def make_client(run: ResourceSnapshot) -> McpResourceClient:
    def authorize() -> None:
        with connector_write(run):
            pass

    with connector_write(run):
        source, profile = validate_mcp_source(run.source)
    try:
        credential = EnvSecretResolver().resolve(profile.secret_ref) if profile.secret_ref else ""
    except SecretResolutionError:
        raise McpResourceError("MCP_RESOURCE_CREDENTIAL_UNAVAILABLE") from None
    return McpResourceClient(
        destination=profile.destination,
        resource_prefixes=tuple(source.connector_config["resource_prefixes"]),
        mime_types=tuple(profile.mime_types),
        limits=McpResourceLimits(**profile.limits),
        credential=credential,
        before_request=authorize,
    )


def execute_snapshot(run: ResourceSnapshot) -> None:
    client = make_client(run)
    discovered = changed = unchanged = 0
    for item in client.iter_documents():
        changed_item = _persist(run, item)
        discovered += 1
        changed += int(changed_item)
        unchanged += int(not changed_item)
        with connector_write(run):
            ResourceSnapshot.objects.filter(pk=run.pk).update(
                discovered_count=discovered,
                changed_count=changed,
                unchanged_count=unchanged,
                fetched_bytes=client.fetched_bytes,
            )
            StagedIndexBuildJob.objects.filter(pk=run.job_id).update(documents_completed=discovered)
    if not client.snapshot_complete:
        raise McpResourceError("MCP_RESOURCE_SNAPSHOT_INCOMPLETE")
    with connector_write(run):
        missing = SourceDocumentCursor.objects.filter(
            source_id=run.source_id, state="active"
        ).exclude(Q(last_seen_job_id=run.job_id, last_seen_attempt=run.attempt))
        missing_count = missing.count()
        missing.update(state="missing")
        docset = run.source.document_set
        if docset is None:
            raise McpResourceError("MCP_RESOURCE_COLLECTION_REQUIRED")
        active_ids = SourceDocumentCursor.objects.filter(
            source_id=run.source_id,
            state="active",
            last_seen_job_id=run.job_id,
            last_seen_attempt=run.attempt,
            document__lifecycle_state=DocumentLifecycle.ACTIVE,
            document__deleted_at__isnull=True,
        ).values_list("document_version_id", flat=True)
        candidate = create_material_candidate(
            document_set=docset,
            source_id=run.source_id,
            source_document_version_ids=active_ids,
            actor="mcp-resource-worker",
        )
        complete_connector_snapshot(run)
        ResourceSnapshot.objects.filter(pk=run.pk).update(
            snapshot_complete=True,
            material_change=candidate is not None,
            candidate_set_version=candidate,
            discovered_count=discovered,
            changed_count=changed,
            unchanged_count=unchanged,
            missing_count=missing_count,
            fetched_bytes=client.fetched_bytes,
        )


def _persist(run: ResourceSnapshot, item: McpResourceDocument) -> bool:
    created_keys: list[str] = []
    try:
        with connector_write(run):
            return _persist_locked(run, item, created_keys)
    except Exception:
        cleanup_connector_uploads(organization_id=run.organization_id, created_keys=created_keys)
        raise


def _persist_locked(
    run: ResourceSnapshot, item: McpResourceDocument, created_keys: list[str]
) -> bool:
    source = run.source
    identity = hashlib.sha256(item.uri.encode("utf-8")).hexdigest()
    checksum = hashlib.sha256(item.content).hexdigest()
    cursor = (
        SourceDocumentCursor.objects.select_related("document", "document_version")
        .filter(
            source=source,
            external_id_hash=identity,
        )
        .first()
    )
    if cursor is not None and cursor.external_id != item.uri:
        raise McpResourceError("MCP_RESOURCE_IDENTITY_CONFLICT")
    logical_id = f"mcp-{source.pk}-{identity}"
    document = Document.objects.filter(
        organization_id=run.organization_id, logical_id=logical_id
    ).first()
    if document is not None and (
        document.source_id != source.pk
        or document.lifecycle_state != DocumentLifecycle.ACTIVE
        or document.deleted_at is not None
    ):
        raise McpResourceError("MCP_RESOURCE_DOCUMENT_UNAVAILABLE")
    if cursor is not None and (document is None or document.pk != cursor.document_id):
        raise McpResourceError("MCP_RESOURCE_DOCUMENT_LINEAGE_INVALID")
    version = None
    if document is not None:
        version = DocumentVersion.objects.filter(
            document=document,
            version=document.current_version,
            checksum=checksum,
            mime_type=item.mime_type,
        ).first()
    if version is None:
        if source.document_set is None:
            raise McpResourceError("MCP_RESOURCE_COLLECTION_REQUIRED")
        draft = get_or_create_manual_draft(
            document_set=source.document_set, actor="mcp-resource-worker"
        )
        version = upload_document(
            organization=source.organization,
            logical_id=logical_id,
            title=item.title,
            mime_type=item.mime_type,
            data=item.content,
            actor="mcp-resource-worker",
            document_set_version=draft,
            source=source,
        )
        created_keys.append(version.object_key)
    elif document is not None and document.title != item.title:
        document.title = item.title
        document.save(update_fields=["title", "updated_at"])
    changed = cursor is None or cursor.document_version_id != version.pk
    if cursor is None:
        cursor = SourceDocumentCursor(
            organization_id=run.organization_id,
            source=source,
            external_id=item.uri,
            external_id_hash=identity,
            document=version.document,
        )
    cursor.document_version = version
    cursor.content_checksum = checksum
    cursor.last_seen_job_id = run.job_id
    cursor.last_seen_attempt = run.attempt
    cursor.state = "active"
    cursor.save()
    return changed
