"""Document content-plane services (Phase 2 · P2).

Every state change and its audit event happen inside one transaction so an audit-write
failure fails closed with the data write (mirroring the Sprint 11 builder). Blob bytes go to
the object store; the database holds only metadata (checksum, mime, tenant-prefixed key,
counts). P4.1 adds the mandatory scenario↔document-set binding and forward-ready ACL grants
here; the deny-by-default retrieval predicate, resolver pinning, and RLS backstop that *enforce*
them arrive in P4.2/P4.3 (no served retrieval path changes yet).

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
from apps.catalog.models import Scenario
from apps.documents.models import (
    Document,
    DocumentLifecycle,
    DocumentSet,
    DocumentSetGrant,
    DocumentSetMembership,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    DocumentVersion,
    GrantPermission,
    GrantPrincipalType,
    ParseStatus,
    ScenarioDocumentSetBinding,
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

    from apps.ingestion.models import DocumentOcrJob

    derived_keys = list(
        DocumentOcrJob.objects.filter(document_version__document=document)
        .exclude(result_object_key="")
        .values_list("result_object_key", flat=True)
    )
    store = get_object_store()
    for version in versions:
        # Idempotent: deleting a missing key is a no-op; only a hard storage error aborts,
        # leaving DB metadata intact for a safe retry.
        store.delete(version.object_key)
    for object_key in derived_keys:
        store.delete(object_key)

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
            after={
                "versions_removed": len(versions),
                "derived_objects_removed": len(derived_keys),
            },
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


# --- Scenario ↔ document-set binding + ACL grants (deny-by-default, P4) --------


def pinned_document_set_version_ids(scenario: Scenario) -> list[int]:
    """Resolve a scenario's bindings to the published document-set version to pin (deny-by-default).

    For each bound document set, pin its latest published (``promotable``/``active``) version. A
    scenario with **no binding** resolves to an empty list — it retrieves nothing. Used by the
    release compiler; the resolver later expands each pinned version to its *active* index version
    (the pointer flip), so promotion/rollback take effect without recompiling.
    """
    set_ids = list(
        ScenarioDocumentSetBinding.objects.filter(scenario=scenario).values_list(
            "document_set_id", flat=True
        )
    )
    pinned: list[int] = []
    for set_id in set_ids:
        version = (
            DocumentSetVersion.objects.filter(
                document_set_id=set_id,
                status__in=[
                    DocumentSetVersionStatus.PROMOTABLE,
                    DocumentSetVersionStatus.ACTIVE,
                ],
            )
            .order_by("-version")
            .first()
        )
        if version is not None:
            pinned.append(version.id)
    return sorted(set(pinned))


@transaction.atomic
def bind_scenario_document_set(
    *, scenario: Scenario, document_set: DocumentSet, actor: str, request_id: str = ""
) -> ScenarioDocumentSetBinding:
    """Bind a scenario to a document set (same tenant, deny-by-default retrieval unit)."""
    organization_id = document_set.organization_id
    binding = ScenarioDocumentSetBinding(
        organization_id=organization_id,
        scenario=scenario,
        document_set=document_set,
        created_by=actor,
    )
    # ``clean`` forbids a cross-tenant scenario↔set link; the DB unique constraint (not
    # ``validate_unique``) reports a duplicate so it maps to a stable code.
    binding.full_clean(exclude=["created_by"], validate_unique=False, validate_constraints=False)
    try:
        binding.save()
    except IntegrityError as exc:
        raise DocumentError("DUPLICATE_BINDING", "scenario is already bound to this set") from exc
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.binding.create",
        outcome="success",
        organization_id=organization_id,
        resource_type="scenario_document_set_binding",
        resource_id=f"{binding.scenario_id}:{document_set.logical_id}",
        request_id=request_id,
    )
    return binding


@transaction.atomic
def unbind_scenario_document_set(
    binding: ScenarioDocumentSetBinding, *, actor: str, request_id: str = ""
) -> None:
    organization_id = binding.organization_id
    scenario_id = binding.scenario_id
    logical_id = binding.document_set.logical_id
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.binding.remove",
        outcome="success",
        organization_id=organization_id,
        resource_type="scenario_document_set_binding",
        resource_id=f"{scenario_id}:{logical_id}",
        request_id=request_id,
    )
    binding.delete()


@transaction.atomic
def grant_document_set(
    *,
    document_set: DocumentSet,
    principal_type: str,
    principal_ref: str,
    permission: str = GrantPermission.RETRIEVE,
    actor: str,
    request_id: str = "",
) -> DocumentSetGrant:
    """Add an ACL grant. Only ``consumer`` grants are enforced in WS1 (others are inert)."""
    if principal_type not in GrantPrincipalType.values:
        raise DocumentError("invalid_principal_type", "unsupported principal type")
    if permission not in GrantPermission.values:
        raise DocumentError("invalid_permission", "unsupported permission")
    principal_ref = (principal_ref or "").strip()
    if not principal_ref:
        raise DocumentError("principal_ref_required", "principal reference is required")
    grant = DocumentSetGrant(
        organization_id=document_set.organization_id,
        document_set=document_set,
        principal_type=principal_type,
        principal_ref=principal_ref,
        permission=permission,
    )
    grant.full_clean(validate_unique=False, validate_constraints=False)
    try:
        grant.save()
    except IntegrityError as exc:
        raise DocumentError("DUPLICATE_GRANT", "grant already exists") from exc
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.grant.create",
        outcome="success",
        organization_id=document_set.organization_id,
        resource_type="document_set_grant",
        resource_id=f"{document_set.logical_id}:{principal_type}:{principal_ref}",
        request_id=request_id,
    )
    return grant


@transaction.atomic
def revoke_document_set_grant(grant: DocumentSetGrant, *, actor: str, request_id: str = "") -> None:
    """Remove an ACL grant with fail-closed audit persistence."""
    organization_id = grant.organization_id
    resource_id = f"{grant.document_set.logical_id}:{grant.principal_type}:{grant.principal_ref}"
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.grant.remove",
        outcome="success",
        organization_id=organization_id,
        resource_type="document_set_grant",
        resource_id=resource_id,
        request_id=request_id,
    )
    grant.delete()
