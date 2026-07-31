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
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.documents.models import (
    Document,
    DocumentLifecycle,
    DocumentSet,
    DocumentSetGrant,
    DocumentSetMembership,
    DocumentSetStatus,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    DocumentVersion,
    GrantPermission,
    GrantPrincipalType,
    ParseStatus,
    ScenarioDocumentSetBinding,
)
from apps.documents.storage import StorageError, build_object_key, get_object_store
from apps.identity.authorization import AuthoritySource, Capability, authorize
from apps.ingestion.models import Source
from apps.tenancy.identifiers import (
    MAX_ALLOCATION_ATTEMPTS,
    IdentifierAllocationError,
    allocate_identifier,
)
from apps.tenancy.models import Organization


class DocumentSetControlError(PermissionError):
    """Stable document-set operational control failure."""


def set_document_set_quarantine(
    *,
    document_set: DocumentSet,
    actor: object,
    quarantined: bool,
    reason: str,
) -> DocumentSet:
    """Quarantine or restore one set without conveying document-content authority."""

    bounded_reason = reason.strip()
    if not bounded_reason or len(bounded_reason) > 200:
        raise DocumentSetControlError("DOCUMENT_SET_CONTROL_REASON_INVALID")
    operations_decision = authorize(
        user=actor,
        capability=Capability.DOCUMENT_SET_OPERATIONS_MANAGE,
        organization=document_set.organization,
        document_set=document_set,
    )
    recovery_decision = authorize(
        user=actor,
        capability=Capability.PLATFORM_MANAGE,
    )
    decision = operations_decision if operations_decision.allowed else recovery_decision
    allowed_sources = {
        AuthoritySource.DOCUMENT_SET_RESPONSIBILITY,
        AuthoritySource.SUPERADMIN_RECOVERY,
    }
    if not decision.allowed or decision.source not in allowed_sources:
        record_event(
            actor_type="user",
            actor_id=str(getattr(actor, "pk", "")),
            action="document_set.quarantine" if quarantined else "document_set.restore",
            outcome="deny",
            organization_id=document_set.organization_id,
            resource_type="document_set",
            resource_id=str(document_set.public_id),
            reason="DOCUMENT_SET_CONTROL_FORBIDDEN",
        )
        raise DocumentSetControlError("DOCUMENT_SET_CONTROL_FORBIDDEN")
    with transaction.atomic():
        locked = DocumentSet.objects.select_for_update().get(
            pk=document_set.pk,
            organization_id=document_set.organization_id,
        )
        target = DocumentSetStatus.QUARANTINED if quarantined else DocumentSetStatus.ACTIVE
        if quarantined and locked.status == DocumentSetStatus.ARCHIVED:
            raise DocumentSetControlError("DOCUMENT_SET_ARCHIVED")
        if not quarantined and locked.status != DocumentSetStatus.QUARANTINED:
            raise DocumentSetControlError("DOCUMENT_SET_NOT_QUARANTINED")
        locked.status = target
        locked.save(update_fields=["status", "updated_at"])
        superadmin = decision.source == AuthoritySource.SUPERADMIN_RECOVERY
        record_event(
            actor_type="user",
            actor_id=str(getattr(actor, "pk", "")),
            action=(
                "superadmin.document_set_control"
                if superadmin
                else ("document_set.quarantine" if quarantined else "document_set.restore")
            ),
            outcome="success",
            organization_id=locked.organization_id,
            resource_type="document_set",
            resource_id=str(locked.public_id),
            reason=f"{'QUARANTINED' if quarantined else 'RESTORED'}:{decision.source}",
        )
    return locked


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
    document_set_version: DocumentSetVersion,
    source: Source | None = None,
    request_id: str = "",
) -> DocumentVersion:
    """Store ``data`` in the object store and record a new immutable ``DocumentVersion``.

    Creation and exact draft-set membership share one database transaction. The blob is written
    first; if the database or required audit write fails it is best-effort removed.
    """
    logical_id = _clean_text(logical_id, field="logical_id", max_length=128)
    title = (title or "").strip()[:500]
    mime_type = (mime_type or "application/octet-stream").strip().lower()[:128]
    _validate_upload(mime_type=mime_type, data=data)
    if source is not None and source.organization_id != organization.id:
        raise DocumentError("source_mismatch", "source must belong to the organization")
    if (
        document_set_version.organization_id != organization.id
        or document_set_version.status != DocumentSetVersionStatus.DRAFT
    ):
        raise DocumentError(
            "UNBOUND_DOCUMENT_DENIED", "documents must be uploaded into an exact draft set version"
        )
    if source is not None and source.document_set_id != document_set_version.document_set_id:
        raise DocumentError("SOURCE_SET_MISMATCH", "source and draft set must match")

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
            upsert_document_in_set_draft(
                set_version=document_set_version,
                document_version=version,
                actor=actor,
                request_id=request_id,
            )
            return version
    except IntegrityError as exc:
        _best_effort_delete(object_key)
        raise DocumentError("UPLOAD_CONFLICT", "concurrent upload conflict") from exc
    except Exception:
        _best_effort_delete(object_key)
        raise


def upload_console_document(
    *,
    organization: Organization,
    title: str,
    mime_type: str,
    data: bytes,
    actor: str,
    request_id: str = "",
) -> DocumentVersion:
    """Standalone console uploads are intentionally closed by Phase 2.8 Part 5."""
    raise DocumentError("UNBOUND_DOCUMENT_DENIED", "documents must be uploaded from a document set")


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


def create_console_document_set(
    *, organization: Organization, name: str, actor: str, request_id: str = ""
) -> DocumentSet:
    """Create a console document set with a server-owned logical ID."""
    for _attempt in range(MAX_ALLOCATION_ATTEMPTS):
        logical_id = allocate_identifier(
            name,
            fallback="document-set",
            max_length=128,
            exists=lambda value: DocumentSet.objects.filter(
                organization=organization, logical_id=value
            ).exists(),
        )
        try:
            with transaction.atomic():
                return create_document_set(
                    organization=organization,
                    logical_id=logical_id,
                    name=name,
                    actor=actor,
                    request_id=request_id,
                )
        except DocumentError as exc:
            if exc.code == "duplicate_logical_id":
                continue
            raise
        except IntegrityError:
            if DocumentSet.objects.filter(
                organization=organization, logical_id=logical_id
            ).exists():
                continue
            raise
    raise IdentifierAllocationError


@transaction.atomic
def create_document_set_version(
    *, document_set: DocumentSet, actor: str, request_id: str = ""
) -> DocumentSetVersion:
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
def get_or_create_manual_draft(
    *, document_set: DocumentSet, actor: str, request_id: str = ""
) -> DocumentSetVersion:
    """Return the newest author draft or create one from the latest published snapshot.

    Connector-owned draft candidates are deliberately excluded: a manual upload must not mutate a
    snapshot that an in-flight connector automation run may publish or index.
    """
    from apps.ingestion.models import ConfluenceSyncRun, RestSyncRun

    locked_set = DocumentSet.objects.select_for_update().get(pk=document_set.pk)
    connector_draft_ids = list(
        ConfluenceSyncRun.objects.filter(
            source__document_set=locked_set, candidate_set_version__isnull=False
        ).values_list("candidate_set_version_id", flat=True)
    ) + list(
        RestSyncRun.objects.filter(
            source__document_set=locked_set, candidate_set_version__isnull=False
        ).values_list("candidate_set_version_id", flat=True)
    )
    draft = (
        locked_set.versions.filter(status=DocumentSetVersionStatus.DRAFT)
        .exclude(pk__in=connector_draft_ids)
        .order_by("-version")
        .first()
    )
    if draft is not None:
        return draft

    baseline = (
        locked_set.versions.filter(
            status__in=[
                DocumentSetVersionStatus.PROMOTABLE,
                DocumentSetVersionStatus.ACTIVE,
                DocumentSetVersionStatus.SUPERSEDED,
            ]
        )
        .order_by("-version")
        .first()
    )
    draft = create_document_set_version(document_set=locked_set, actor=actor, request_id=request_id)
    if baseline is not None:
        for membership in baseline.memberships.order_by("ordinal", "id").select_related(
            "document_version"
        ):
            add_document_to_set_version(
                set_version=draft,
                document_version=membership.document_version,
                ordinal=membership.ordinal,
                actor=actor,
                request_id=request_id,
            )
    return draft


@transaction.atomic
def upsert_document_in_set_draft(
    *,
    set_version: DocumentSetVersion,
    document_version: DocumentVersion,
    actor: str,
    request_id: str = "",
) -> DocumentSetMembership:
    """Pin the exact uploaded version, replacing the same logical document in a draft."""
    locked = DocumentSetVersion.objects.select_for_update().get(pk=set_version.pk)
    if locked.is_frozen:
        raise DocumentError("SET_VERSION_FROZEN", "published set versions are immutable")
    if document_version.organization_id != locked.organization_id:
        raise DocumentError("DOCUMENT_TENANT_MISMATCH", "document must belong to the set tenant")

    existing = list(
        locked.memberships.select_for_update()
        .filter(document_version__document_id=document_version.document_id)
        .order_by("ordinal", "id")
    )
    for membership in existing:
        if membership.document_version_id == document_version.pk and len(existing) == 1:
            return membership
    max_ordinal = locked.memberships.aggregate(value=Max("ordinal"))["value"]
    ordinal = (
        existing[0].ordinal if existing else (max_ordinal + 1 if max_ordinal is not None else 0)
    )
    before_ids = [item.document_version_id for item in existing]
    if existing:
        locked.memberships.filter(pk__in=[item.pk for item in existing]).delete()
    membership = DocumentSetMembership(
        organization_id=locked.organization_id,
        document_set_version=locked,
        document_version=document_version,
        ordinal=ordinal,
    )
    membership.full_clean()
    membership.save()
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.set_version.upsert_member",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="document_set_version",
        resource_id=f"{locked.document_set.logical_id}:v{locked.version}",
        request_id=request_id,
        before={"document_version_ids": before_ids},
        after={"document_version_id": document_version.pk},
    )
    return membership


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
    existing = locked.memberships.filter(document_version=document_version).first()
    if existing is not None:
        return existing
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
def remove_document_from_set_draft(
    *,
    set_version: DocumentSetVersion,
    membership_id: int,
    actor: str,
    request_id: str = "",
) -> None:
    """Remove one exact membership from a mutable draft without touching document bytes."""
    locked = DocumentSetVersion.objects.select_for_update().get(pk=set_version.pk)
    if locked.is_frozen:
        raise DocumentError("SET_VERSION_FROZEN", "published set versions are immutable")
    membership = (
        DocumentSetMembership.objects.select_for_update()
        .filter(
            pk=membership_id,
            document_set_version=locked,
            organization_id=locked.organization_id,
        )
        .select_related("document_version__document")
        .first()
    )
    if membership is None:
        raise DocumentError("MEMBERSHIP_NOT_FOUND", "membership is not in this draft")
    document_version_id = membership.document_version_id
    membership.delete()
    record_event(
        actor_type="user",
        actor_id=actor,
        action="documents.set_version.remove_member",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="document_set_version",
        resource_id=f"{locked.document_set.logical_id}:v{locked.version}",
        request_id=request_id,
        before={"document_version_id": document_version_id},
    )


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
    from apps.ingestion.preparation import enqueue_auto_preparation

    transaction.on_commit(
        lambda: enqueue_auto_preparation(
            document_set_version_id=locked.pk,
            organization_id=locked.organization_id,
        )
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
    from apps.documents.models import ScenarioDocumentSetGrant, ScenarioDocumentSetGrantStatus

    granted_set_ids = ScenarioDocumentSetGrant.objects.filter(
        scenario=scenario,
        permission=GrantPermission.RETRIEVE,
        status=ScenarioDocumentSetGrantStatus.GRANTED,
        revoked_at__isnull=True,
    ).values_list("document_set_id", flat=True)
    set_ids = list(
        ScenarioDocumentSetBinding.objects.filter(
            scenario=scenario,
            document_set_id__in=granted_set_ids,
        ).values_list("document_set_id", flat=True)
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
