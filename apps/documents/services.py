"""Document content-plane services (Phase 2 · P2).

Every state change and its audit event happen inside one transaction so an audit-write
failure fails closed with the data write (mirroring the Sprint 11 builder). Blob bytes go to
the object store; the database holds only metadata (checksum, mime, tenant-prefixed key,
counts). No retrieval behavior, scenario binding, ACL grant, or RLS is touched here — those
arrive in P4.

Removal has two levels: :func:`soft_delete_document` sets a tombstone (immediately excluded
from future retrieval by the P4 ``deleted_at`` predicate) and :func:`purge_document` is a
separate, elevated, audited physical delete of blobs + versions. Purge refuses content pinned
into a published document-set version (fail-closed against destroying a served corpus).
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.documents.models import (
    Document,
    DocumentLifecycle,
    DocumentSet,
    DocumentSetMembership,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    DocumentVersion,
    ParseStatus,
)
from apps.documents.storage import StorageError, build_object_key, get_object_store
from apps.ingestion.models import Source
from apps.tenancy.models import Organization


class DocumentError(ValueError):
    """A safe, content-free document error carrying a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _max_upload_bytes() -> int:
    return int(getattr(settings, "DOCUMENTS_MAX_UPLOAD_BYTES", 25_000_000))


def _allowed_mime_types() -> set[str]:
    return set(getattr(settings, "DOCUMENTS_ALLOWED_MIME_TYPES", ()))


def _validate_upload(*, mime_type: str, data: bytes) -> None:
    if not data:
        raise DocumentError("EMPTY_UPLOAD", "uploaded file is empty")
    if len(data) > _max_upload_bytes():
        raise DocumentError("UPLOAD_TOO_LARGE", "uploaded file exceeds the size limit")
    allowed = _allowed_mime_types()
    if allowed and mime_type not in allowed:
        raise DocumentError("MIME_TYPE_DENIED", "unsupported content type")


def _clean_text(value: str, *, field: str, max_length: int) -> str:
    value = (value or "").strip()
    if not value:
        raise DocumentError(f"{field}_required", f"{field} is required")
    if len(value) > max_length:
        raise DocumentError(f"{field}_too_long", f"{field} exceeds the length limit")
    return value


def upload_document(
    *,
    organization: Organization,
    logical_id: str,
    title: str,
    mime_type: str,
    data: bytes,
    actor: str,
    source: Source | None = None,
    request_id: str = "",
) -> DocumentVersion:
    """Store ``data`` in the object store and record a new immutable ``DocumentVersion``.

    Creates the ``Document`` on first upload for ``logical_id`` and advances its version on
    subsequent uploads. The blob is written before the DB rows; if the DB write fails, the
    orphaned blob is best-effort removed (unique random keys make orphans harmless otherwise).
    """
    logical_id = _clean_text(logical_id, field="logical_id", max_length=128)
    title = (title or "").strip()[:500]
    mime_type = (mime_type or "application/octet-stream").strip().lower()[:128]
    _validate_upload(mime_type=mime_type, data=data)
    if source is not None and source.organization_id != organization.id:
        raise DocumentError("source_mismatch", "source must belong to the organization")

    checksum = hashlib.sha256(data).hexdigest()
    object_key = build_object_key(organization_id=organization.id, document_logical_id=logical_id)

    store = get_object_store()
    store.put(object_key, data, content_type=mime_type)

    try:
        with transaction.atomic():
            document = (
                Document.objects.select_for_update()
                .filter(organization=organization, logical_id=logical_id)
                .first()
            )
            if document is None:
                document = Document(
                    organization=organization,
                    source=source,
                    logical_id=logical_id,
                    title=title,
                )
                document.full_clean(exclude=["current_version"])
                document.save()
            else:
                if document.is_tombstoned:
                    raise DocumentError("DOCUMENT_TOMBSTONED", "document is tombstoned")
                if title:
                    document.title = title

            version_number = document.current_version + 1
            version = DocumentVersion(
                organization=organization,
                document=document,
                version=version_number,
                checksum=checksum,
                mime_type=mime_type,
                object_key=object_key,
                byte_size=len(data),
                parser="",
                parse_status=ParseStatus.PENDING,
            )
            version.full_clean()
            version.save()

            document.current_version = version_number
            document.save(update_fields=["current_version", "title", "updated_at"])

            record_event(
                actor_type="user",
                actor_id=actor,
                action="documents.document.upload",
                outcome="success",
                organization_id=organization.id,
                resource_type="document_version",
                resource_id=f"{logical_id}:v{version_number}",
                reason=checksum,
                request_id=request_id,
                after={"byte_size": len(data), "mime_type": mime_type},
            )
            return version
    except IntegrityError as exc:
        _best_effort_delete(object_key)
        raise DocumentError("UPLOAD_CONFLICT", "concurrent upload conflict") from exc
    except Exception:
        _best_effort_delete(object_key)
        raise


def _best_effort_delete(object_key: str) -> None:
    try:
        get_object_store().delete(object_key)
    except StorageError:
        # The blob is orphaned but unreferenced; the retention/purge job (P3) reclaims it.
        pass


@transaction.atomic
def soft_delete_document(document: Document, *, actor: str, request_id: str = "") -> Document:
    """Tombstone a document (idempotent). Bytes remain until an auditable purge."""
    locked = Document.objects.select_for_update().get(pk=document.pk)
    if locked.is_tombstoned:
        return locked
    locked.lifecycle_state = DocumentLifecycle.TOMBSTONED
    locked.deleted_at = timezone.now()
    locked.save(update_fields=["lifecycle_state", "deleted_at", "updated_at"])
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.document.soft_delete",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="document",
        resource_id=locked.logical_id,
        request_id=request_id,
    )
    return locked


def purge_document(document: Document, *, actor: str, request_id: str = "") -> int:
    """Physically delete a document's blobs and versions (elevated, audited, fail-closed).

    Refuses if any version is pinned into a document-set version (``DOCUMENT_IN_USE``). Blob
    deletion runs before the metadata delete and is idempotent, so a retry after a transient
    storage error converges. Returns the number of versions removed.
    """
    versions = list(DocumentVersion.objects.filter(document=document))
    if DocumentSetMembership.objects.filter(document_version__document=document).exists():
        raise DocumentError("DOCUMENT_IN_USE", "document is pinned into a document set")

    store = get_object_store()
    for version in versions:
        # Idempotent: deleting a missing key is a no-op; only a hard storage error aborts,
        # leaving DB metadata intact for a safe retry.
        store.delete(version.object_key)

    logical_id = document.logical_id
    organization_id = document.organization_id
    with transaction.atomic():
        # Audit inside the transaction so an audit-write failure rolls the delete back.
        record_event(
            actor_type="user",
            actor_id=actor,
            action="documents.document.purge",
            outcome="success",
            organization_id=organization_id,
            resource_type="document",
            resource_id=logical_id,
            reason="physical_purge",
            request_id=request_id,
            after={"versions_removed": len(versions)},
        )
        Document.objects.filter(pk=document.pk).delete()
    return len(versions)


# --- Document sets (logical retrieval unit; binding/serving arrive in P4) -----


@transaction.atomic
def create_document_set(
    *, organization: Organization, logical_id: str, name: str, actor: str, request_id: str = ""
) -> DocumentSet:
    logical_id = _clean_text(logical_id, field="logical_id", max_length=128)
    name = _clean_text(name, field="name", max_length=200)
    if DocumentSet.objects.filter(organization=organization, logical_id=logical_id).exists():
        raise DocumentError("duplicate_logical_id", "a document set with this id already exists")
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id=logical_id, name=name
    )
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.set.create",
        outcome="success",
        organization_id=organization.id,
        resource_type="document_set",
        resource_id=logical_id,
        request_id=request_id,
    )
    return document_set


@transaction.atomic
def create_document_set_version(
    *, document_set: DocumentSet, actor: str, request_id: str = ""
) -> DocumentSetVersion:
    from django.db.models import Max

    locked = DocumentSet.objects.select_for_update().get(pk=document_set.pk)
    latest = locked.versions.aggregate(value=Max("version"))["value"] or 0
    version = DocumentSetVersion.objects.create(
        organization_id=locked.organization_id,
        document_set=locked,
        version=latest + 1,
        status=DocumentSetVersionStatus.DRAFT,
    )
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.set_version.create",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="document_set_version",
        resource_id=f"{locked.logical_id}:v{version.version}",
        request_id=request_id,
    )
    return version


@transaction.atomic
def add_document_to_set_version(
    *,
    set_version: DocumentSetVersion,
    document_version: DocumentVersion,
    ordinal: int = 0,
    actor: str,
    request_id: str = "",
) -> DocumentSetMembership:
    locked = DocumentSetVersion.objects.select_for_update().get(pk=set_version.pk)
    if locked.is_frozen:
        raise DocumentError("SET_VERSION_FROZEN", "published set versions are immutable")
    membership = DocumentSetMembership(
        organization_id=locked.organization_id,
        document_set_version=locked,
        document_version=document_version,
        ordinal=max(0, int(ordinal)),
    )
    # ``clean`` enforces same-tenant set-version and document-version (cross-tenant defense).
    membership.full_clean()
    try:
        membership.save()
    except IntegrityError as exc:
        raise DocumentError("DUPLICATE_MEMBERSHIP", "document already in set version") from exc
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.set_version.add_member",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="document_set_version",
        resource_id=f"{locked.document_set.logical_id}:v{locked.version}",
        request_id=request_id,
        after={"document_version_id": document_version.pk},
    )
    return membership


@transaction.atomic
def publish_document_set_version(
    *, set_version: DocumentSetVersion, actor: str, request_id: str = ""
) -> DocumentSetVersion:
    """Freeze a draft set version's membership (marks it promotable).

    P2 only freezes membership; building/eval/pointer-flip promotion of a real index is P3/P4.
    """
    locked = DocumentSetVersion.objects.select_for_update().get(pk=set_version.pk)
    if locked.is_frozen:
        raise DocumentError("SET_VERSION_FROZEN", "set version is already published")
    if not locked.memberships.exists():
        raise DocumentError("SET_VERSION_EMPTY", "set version has no members")
    locked.status = DocumentSetVersionStatus.PROMOTABLE
    locked.save(update_fields=["status", "updated_at"])
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.set_version.publish",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="document_set_version",
        resource_id=f"{locked.document_set.logical_id}:v{locked.version}",
        request_id=request_id,
    )
    return locked
