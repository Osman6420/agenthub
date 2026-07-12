"""Content-plane data model (Phase 2 · Workstream 1 · P2).

Tenant-owned document content as first-class, independently managed objects — distinct
from the index *build* artifact (``apps.ingestion.IndexedDocument``). Lineage:

    Source -> Document -> DocumentVersion -> Blob(object store)
    DocumentSet -> DocumentSetVersion -> DocumentSetMembership

Every model carries a mandatory ``organization`` (tenant) FK. Following the document-plane
design, ``tenant_id`` is mandatory and never mutated on any row; the denormalized column on
child models makes the future PostgreSQL ``FORCE ROW LEVEL SECURITY`` policy (ADR-0004, P4) a
single-column predicate and lets ``clean()`` reject any cross-tenant parent/child link now.

P2 is content plane + storage only: no retrieval behavior change, no scenario binding, no ACL
grant enforcement, and no RLS yet (those arrive in P4). ``DocumentVersion`` is immutable once
written; ``DocumentSetVersion`` membership is frozen at publish.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.tenancy.models import Organization, TimeStampedModel


class DocumentLifecycle(models.TextChoices):
    ACTIVE = "active", "Active"
    TOMBSTONED = "tombstoned", "Tombstoned"


class Document(TimeStampedModel):
    """A tenant's canonical, managed content object (its versions hold the bytes)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="content_documents"
    )
    # Provenance. ``upload`` documents have no connector source (system-originated), so this
    # is nullable; ``SET_NULL`` keeps the document if its source is later removed.
    source = models.ForeignKey(
        "ingestion.Source",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_documents",
    )
    logical_id = models.CharField(max_length=128)
    title = models.CharField(max_length=500, blank=True)
    # Highest version number written so far (0 = none yet). Advanced under a row lock.
    current_version = models.PositiveIntegerField(default=0)
    lifecycle_state = models.CharField(
        max_length=16, choices=DocumentLifecycle.choices, default=DocumentLifecycle.ACTIVE
    )
    # Soft-delete tombstone timestamp; retrieval excludes ``deleted_at IS NOT NULL`` (P4).
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "logical_id"], name="uniq_document_org_logical"
            )
        ]
        indexes = [models.Index(fields=["organization", "lifecycle_state"])]
        ordering = ["-updated_at"]

    def clean(self) -> None:
        if (
            self.source_id and self.source.organization_id != self.organization_id  # type: ignore[union-attr]
        ):
            raise ValidationError("document source must belong to the same organization")

    @property
    def is_tombstoned(self) -> bool:
        return self.lifecycle_state == DocumentLifecycle.TOMBSTONED

    def __str__(self) -> str:
        return f"document:{self.organization_id}:{self.logical_id}"


class ParseStatus(models.TextChoices):
    # P2 stores bytes only; real parsing (pdf/docx/xlsx -> markdown) arrives in P7.
    PENDING = "pending", "Pending"
    PARSED = "parsed", "Parsed"
    FAILED = "failed", "Failed"


class DocumentVersion(TimeStampedModel):
    """An immutable snapshot of one document's bytes (stored in the object store)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="document_versions"
    )
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    checksum = models.CharField(max_length=64)  # sha-256 hex of the stored bytes
    mime_type = models.CharField(max_length=128)
    # Opaque, tenant-prefixed object-store key. Never surfaced beyond tenant scope.
    object_key = models.CharField(max_length=512)
    byte_size = models.PositiveBigIntegerField(default=0)
    parser = models.CharField(max_length=32, blank=True)
    parse_status = models.CharField(
        max_length=16, choices=ParseStatus.choices, default=ParseStatus.PENDING
    )
    # Counts only (never content) — element/page metadata for later parsing telemetry.
    element_count = models.PositiveIntegerField(default=0)
    page_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["document", "version"], name="uniq_document_version"),
            models.UniqueConstraint(fields=["object_key"], name="uniq_document_object_key"),
        ]
        ordering = ["document_id", "version"]

    def clean(self) -> None:
        if self.document_id and self.document.organization_id != self.organization_id:
            raise ValidationError("document version organization must match its document")

    def __str__(self) -> str:
        return f"document-version:{self.document_id}:v{self.version}"


class DocumentSetStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class DocumentSet(TimeStampedModel):
    """The logical ACL/retrieval unit (bound to scenarios and served in P4)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="document_sets"
    )
    logical_id = models.CharField(max_length=128)
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16, choices=DocumentSetStatus.choices, default=DocumentSetStatus.ACTIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "logical_id"], name="uniq_document_set_org_logical"
            )
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"document-set:{self.organization_id}:{self.logical_id}"


class DocumentSetVersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    BUILDING = "building", "Building"
    PROMOTABLE = "promotable", "Promotable"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"


class DocumentSetVersion(TimeStampedModel):
    """An immutable published snapshot of a document set's membership.

    ``embedding_profile`` and staged blue/green index wiring arrive in P3; ``built_index_version``
    is present but optional so P2 can create versions without an index build.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="document_set_versions"
    )
    document_set = models.ForeignKey(DocumentSet, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        choices=DocumentSetVersionStatus.choices,
        default=DocumentSetVersionStatus.DRAFT,
    )
    built_index_version = models.ForeignKey(
        "ingestion.IndexVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_set_versions",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document_set", "version"], name="uniq_document_set_version"
            )
        ]
        ordering = ["document_set_id", "version"]

    def clean(self) -> None:
        if self.document_set_id and self.document_set.organization_id != self.organization_id:
            raise ValidationError("document-set version organization must match its set")
        if (
            self.built_index_version_id
            and self.built_index_version.organization_id != self.organization_id  # type: ignore[union-attr]
        ):
            raise ValidationError("built index version must belong to the same organization")

    @property
    def is_frozen(self) -> bool:
        return self.status != DocumentSetVersionStatus.DRAFT

    def __str__(self) -> str:
        return f"document-set-version:{self.document_set_id}:v{self.version}"


class DocumentSetMembership(TimeStampedModel):
    """Pins one exact ``DocumentVersion`` into a set version (immutable once published)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="document_set_memberships"
    )
    document_set_version = models.ForeignKey(
        DocumentSetVersion, on_delete=models.CASCADE, related_name="memberships"
    )
    # PROTECT so a pinned content version cannot be purged out from under a published set.
    document_version = models.ForeignKey(
        DocumentVersion, on_delete=models.PROTECT, related_name="memberships"
    )
    ordinal = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document_set_version", "document_version"],
                name="uniq_membership_setversion_docversion",
            )
        ]
        ordering = ["document_set_version_id", "ordinal"]

    def clean(self) -> None:
        if (
            self.document_set_version_id
            and self.document_set_version.organization_id != self.organization_id
        ):
            raise ValidationError("membership organization must match its set version")
        # Cross-tenant defense: a set may only pin content owned by the same tenant.
        if (
            self.document_version_id
            and self.document_version.organization_id != self.organization_id
        ):
            raise ValidationError(
                "membership document version must belong to the same organization"
            )

    def __str__(self) -> str:
        return f"membership:{self.document_set_version_id}:{self.document_version_id}"


class ScenarioDocumentSetBinding(TimeStampedModel):
    """Mandatory scenario ↔ document-set binding (the deny-by-default retrieval unit).

    A retrieval scenario retrieves **only** from the document sets it is explicitly bound to,
    within its tenant. A scenario with no binding retrieves nothing. At release-compile time
    (P4.2) each binding resolves to a specific published ``DocumentSetVersion``; the enforcement
    predicate + RLS backstop land in P4.2/P4.3. Here we model the binding and forbid a
    cross-tenant scenario↔set link.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="scenario_document_set_bindings"
    )
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.CASCADE, related_name="document_set_bindings"
    )
    document_set = models.ForeignKey(
        DocumentSet, on_delete=models.CASCADE, related_name="scenario_bindings"
    )
    created_by = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "document_set"], name="uniq_scenario_document_set_binding"
            )
        ]
        ordering = ["organization_id", "scenario_id", "document_set_id"]

    def clean(self) -> None:
        if self.document_set_id and self.document_set.organization_id != self.organization_id:
            raise ValidationError("binding document set must belong to the same organization")
        # Scenario tenancy is derived through its project; a scenario may only bind a set in
        # its own tenant (cross-tenant retrieval defense).
        if self.scenario_id and self.scenario.organization_id != self.organization_id:
            raise ValidationError("binding scenario must belong to the same organization")

    def __str__(self) -> str:
        return f"binding:{self.scenario_id}:{self.document_set_id}"


class GrantPrincipalType(models.TextChoices):
    CONSUMER = "consumer", "Consumer"
    SERVICE = "service", "Service"
    USER = "user", "User"
    GROUP = "group", "Group"


class GrantPermission(models.TextChoices):
    RETRIEVE = "retrieve", "Retrieve"


class DocumentSetGrant(TimeStampedModel):
    """Forward-ready ACL grant on a document set.

    **Workstream 1 (P4) enforces only ``consumer`` grants via the scenario binding**; ``service``/
    ``user``/``group`` rows may exist but are inert until the personal-MCP workstream (WS4). The
    ``principal_ref`` is an opaque reference (e.g. a consumer's public id), not an FK, because the
    principal namespace varies by ``principal_type``.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="document_set_grants"
    )
    document_set = models.ForeignKey(DocumentSet, on_delete=models.CASCADE, related_name="grants")
    principal_type = models.CharField(max_length=16, choices=GrantPrincipalType.choices)
    principal_ref = models.CharField(max_length=255)
    permission = models.CharField(
        max_length=16, choices=GrantPermission.choices, default=GrantPermission.RETRIEVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document_set", "principal_type", "principal_ref", "permission"],
                name="uniq_document_set_grant",
            )
        ]
        ordering = ["document_set_id", "principal_type", "principal_ref"]

    def clean(self) -> None:
        if self.document_set_id and self.document_set.organization_id != self.organization_id:
            raise ValidationError("grant document set must belong to the same organization")

    def __str__(self) -> str:
        return f"grant:{self.document_set_id}:{self.principal_type}:{self.principal_ref}"
