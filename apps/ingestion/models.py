"""Tenant-owned ingestion sources, runs, staged indexes, and vector chunks."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.tenancy.models import Organization, TimeStampedModel

EMBEDDING_DIMENSIONS = 64

# pgvector HNSW dimension limits by column type (ADR-0003): an unsupported dimension for the
# chosen index type is rejected at ingestion start — never silently truncated.
VECTOR_MAX_DIMENSIONS = 2000
HALFVEC_MAX_DIMENSIONS = 4000


class SourceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class ConnectorType(models.TextChoices):
    HTTPS = "https", "Allowlisted HTTPS"
    S3 = "s3", "S3/MinIO object"
    CONFLUENCE_DC = "confluence_dc", "Confluence Data Center"
    GENERIC_REST = "generic_rest", "Governed generic REST"


class ConfluenceProfileStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class RestPullProfileStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class RestPullMethod(models.TextChoices):
    GET = "GET", "GET"
    POST = "POST", "POST (read-only contract)"


class RestPullAuthMode(models.TextChoices):
    NONE = "none", "None"
    BEARER = "bearer", "Bearer"
    API_KEY_HEADER = "api_key_header", "API key header"


class RestPullProfile(models.Model):
    """Immutable platform-owned destination and transport limits for generic REST."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    logical_id = models.CharField(max_length=128)
    revision = models.PositiveIntegerField()
    scheme = models.CharField(max_length=8, default="https")
    host = models.CharField(max_length=253)
    port = models.PositiveIntegerField(default=443)
    path_prefix = models.CharField(max_length=512, default="/")
    method = models.CharField(
        max_length=8, choices=RestPullMethod.choices, default=RestPullMethod.GET
    )
    auth_mode = models.CharField(
        max_length=24, choices=RestPullAuthMode.choices, default=RestPullAuthMode.NONE
    )
    secret_ref = models.CharField(max_length=160, blank=True)
    api_key_header_name = models.CharField(max_length=64, blank=True)
    timeout_seconds = models.PositiveIntegerField(default=30)
    max_response_bytes = models.PositiveIntegerField(default=5_000_000)
    max_total_bytes = models.PositiveBigIntegerField(default=100_000_000)
    max_requests = models.PositiveIntegerField(default=1_000)
    max_items = models.PositiveIntegerField(default=50_000)
    max_pages = models.PositiveIntegerField(default=1_000)
    max_retries = models.PositiveSmallIntegerField(default=2)
    max_decoded_item_bytes = models.PositiveIntegerField(default=25_000_000)
    status = models.CharField(
        max_length=16,
        choices=RestPullProfileStatus.choices,
        default=RestPullProfileStatus.ACTIVE,
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["logical_id", "revision"], name="uniq_rest_profile_logical_revision"
            )
        ]

    def __str__(self) -> str:
        return f"rest-profile:{self.logical_id}:r{self.revision}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            update_fields = set(kwargs.get("update_fields") or [])
            if not update_fields or not update_fields <= {"status"}:
                raise ValueError("RestPullProfile is immutable; only status may change")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("RestPullProfile is immutable and cannot be deleted")


class RestPullContractStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class RestPullContract(TimeStampedModel):
    """Tenant-authored immutable closed mapping contract; it never carries authority."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="rest_pull_contracts"
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    logical_id = models.CharField(max_length=128)
    revision = models.PositiveIntegerField()
    definition = models.JSONField()
    checksum = models.CharField(max_length=64, editable=False)
    status = models.CharField(
        max_length=16,
        choices=RestPullContractStatus.choices,
        default=RestPullContractStatus.ACTIVE,
    )
    created_by = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "logical_id", "revision"],
                name="uniq_rest_contract_org_logical_revision",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            update_fields = set(kwargs.get("update_fields") or [])
            if not update_fields or not update_fields <= {"status", "updated_at"}:
                raise ValueError("RestPullContract is immutable; only status may change")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("RestPullContract is immutable and cannot be deleted")


class ConfluenceProfile(models.Model):
    """Immutable platform catalog entry for one Confluence Data Center revision."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    logical_id = models.CharField(max_length=128)
    revision = models.PositiveIntegerField()
    provider = models.CharField(max_length=32, default="confluence_dc")
    scheme = models.CharField(max_length=8, default="https")
    host = models.CharField(max_length=253)
    port = models.PositiveIntegerField(default=443)
    context_path = models.CharField(max_length=512, blank=True)
    secret_ref = models.CharField(max_length=160)
    network_policy_id = models.CharField(max_length=128)
    timeout_seconds = models.PositiveIntegerField(default=30)
    page_size = models.PositiveSmallIntegerField(default=50)
    max_pages = models.PositiveIntegerField(default=5_000)
    max_depth = models.PositiveSmallIntegerField(default=50)
    max_requests = models.PositiveIntegerField(default=20_000)
    max_retries = models.PositiveSmallIntegerField(default=2)
    max_response_bytes = models.PositiveIntegerField(default=5_000_000)
    max_page_body_bytes = models.PositiveIntegerField(default=4_000_000)
    max_total_bytes = models.PositiveBigIntegerField(default=100_000_000)
    status = models.CharField(
        max_length=16,
        choices=ConfluenceProfileStatus.choices,
        default=ConfluenceProfileStatus.ACTIVE,
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["logical_id", "revision"],
                name="uniq_confluence_profile_logical_revision",
            )
        ]

    def __str__(self) -> str:
        return f"confluence-profile:{self.logical_id}:r{self.revision}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            update_fields = set(kwargs.get("update_fields") or [])
            if not update_fields or not update_fields <= {"status"}:
                raise ValueError("ConfluenceProfile is immutable; only status may change")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("ConfluenceProfile is immutable and cannot be deleted")


class Source(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="sources")
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    connector_type = models.CharField(max_length=16, choices=ConnectorType.choices)
    connector_config = models.JSONField(default=dict)
    confluence_profile = models.ForeignKey(
        ConfluenceProfile,
        on_delete=models.PROTECT,
        related_name="sources",
        null=True,
        blank=True,
    )
    rest_profile = models.ForeignKey(
        RestPullProfile,
        on_delete=models.PROTECT,
        related_name="sources",
        null=True,
        blank=True,
    )
    rest_contract = models.ForeignKey(
        RestPullContract,
        on_delete=models.PROTECT,
        related_name="sources",
        null=True,
        blank=True,
    )
    document_set = models.ForeignKey(
        "documents.DocumentSet",
        on_delete=models.PROTECT,
        related_name="connector_sources",
        null=True,
        blank=True,
    )
    parser = models.CharField(max_length=32, default="text")
    chunker = models.CharField(max_length=32, default="fixed")
    embedder = models.CharField(max_length=32, default="deterministic")
    status = models.CharField(
        max_length=16, choices=SourceStatus.choices, default=SourceStatus.ACTIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "slug"], name="uniq_source_org_slug"),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        connector_type=ConnectorType.CONFLUENCE_DC,
                        confluence_profile__isnull=False,
                        document_set__isnull=False,
                        rest_profile__isnull=True,
                        rest_contract__isnull=True,
                    )
                    | (
                        ~models.Q(connector_type=ConnectorType.CONFLUENCE_DC)
                        & models.Q(confluence_profile__isnull=True)
                    )
                ),
                name="source_confluence_binding_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        connector_type=ConnectorType.GENERIC_REST,
                        rest_profile__isnull=False,
                        rest_contract__isnull=False,
                        document_set__isnull=False,
                        confluence_profile__isnull=True,
                    )
                    | (
                        ~models.Q(connector_type=ConnectorType.GENERIC_REST)
                        & models.Q(rest_profile__isnull=True, rest_contract__isnull=True)
                    )
                ),
                name="source_rest_binding_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        connector_type__in=[
                            ConnectorType.CONFLUENCE_DC,
                            ConnectorType.GENERIC_REST,
                        ],
                        document_set__isnull=False,
                    )
                    | (
                        ~models.Q(
                            connector_type__in=[
                                ConnectorType.CONFLUENCE_DC,
                                ConnectorType.GENERIC_REST,
                            ]
                        )
                        & models.Q(document_set__isnull=True)
                    )
                ),
                name="source_document_set_binding_consistent",
            ),
        ]

    def clean(self) -> None:
        if not isinstance(self.connector_config, dict):
            raise ValidationError({"connector_config": "must be a mapping"})
        forbidden = {"secret", "password", "token", "access_key", "secret_key"}
        if forbidden & {str(key).lower() for key in self.connector_config}:
            raise ValidationError({"connector_config": "inline credentials are forbidden"})
        allowed: dict[str, set[str]] = {
            ConnectorType.HTTPS: {"url"},
            ConnectorType.S3: {"bucket", "key"},
            ConnectorType.CONFLUENCE_DC: {
                "root_page_ids",
                "include_root",
                "excluded_page_ids",
            },
            ConnectorType.GENERIC_REST: {"inputs"},
        }
        unknown = set(self.connector_config) - allowed.get(self.connector_type, set())
        if unknown:
            raise ValidationError(
                {"connector_config": f"unsupported keys: {', '.join(sorted(unknown))}"}
            )
        if self.connector_type == ConnectorType.CONFLUENCE_DC:
            from apps.ingestion.confluence_schema import (
                ConfluenceValidationError,
                validate_confluence_source_config,
            )

            try:
                validate_confluence_source_config(self.connector_config)
            except ConfluenceValidationError as exc:
                raise ValidationError({"connector_config": str(exc)}) from exc
            if not self.confluence_profile_id or not self.document_set_id:
                raise ValidationError("Confluence source requires profile and document set")
            if self.document_set.organization_id != self.organization_id:  # type: ignore[union-attr]
                raise ValidationError("Confluence document set must belong to the organization")
        elif self.connector_type == ConnectorType.GENERIC_REST:
            from apps.ingestion.rest_schema import validate_source_inputs

            if not self.rest_profile_id or not self.rest_contract_id or not self.document_set_id:
                raise ValidationError(
                    "generic REST source requires profile, contract and document set"
                )
            if self.confluence_profile_id:
                raise ValidationError("generic REST source cannot have a Confluence profile")
            if self.rest_contract.organization_id != self.organization_id:  # type: ignore[union-attr]
                raise ValidationError("REST contract must belong to the organization")
            if self.document_set.organization_id != self.organization_id:  # type: ignore[union-attr]
                raise ValidationError("REST document set must belong to the organization")
            rest_contract = self.rest_contract
            if rest_contract is None:
                raise ValidationError("generic REST contract is required")
            try:
                validate_source_inputs(
                    rest_contract.definition, self.connector_config.get("inputs")
                )
            except ValueError as exc:
                raise ValidationError({"connector_config": str(exc)}) from exc
        elif (
            self.confluence_profile_id
            or self.rest_profile_id
            or self.rest_contract_id
            or self.document_set_id
        ):
            raise ValidationError("unbound source cannot have governed connector bindings")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.connector_type in {ConnectorType.CONFLUENCE_DC, ConnectorType.GENERIC_REST}:
            self.clean()
        if self.pk is not None:
            previous = (
                Source.objects.filter(pk=self.pk)
                .values(
                    "connector_type",
                    "confluence_profile_id",
                    "rest_profile_id",
                    "rest_contract_id",
                    "document_set_id",
                )
                .first()
            )
            if previous is not None and (
                previous["connector_type"]
                in {ConnectorType.CONFLUENCE_DC, ConnectorType.GENERIC_REST}
                or self.connector_type in {ConnectorType.CONFLUENCE_DC, ConnectorType.GENERIC_REST}
            ):
                binding = (
                    self.connector_type,
                    self.confluence_profile_id,
                    self.rest_profile_id,
                    self.rest_contract_id,
                    self.document_set_id,
                )
                previous_binding = (
                    previous["connector_type"],
                    previous["confluence_profile_id"],
                    previous["rest_profile_id"],
                    previous["rest_contract_id"],
                    previous["document_set_id"],
                )
                if binding != previous_binding:
                    raise ValueError("governed connector source binding is immutable")
        super().save(*args, **kwargs)

    @property
    def is_active(self) -> bool:
        return self.status == SourceStatus.ACTIVE


class IndexStatus(models.TextChoices):
    BUILDING = "building", "Building"
    PROMOTABLE = "promotable", "Promotable"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"
    FAILED = "failed", "Failed"


class IndexVersion(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="index_versions"
    )
    # Sprint 5 source-scoped path (legacy). Nullable so a Phase 2 P3 index version can instead be
    # scoped to a document-set version + embedding profile (ADR-0003 retrieval trust unit).
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="index_versions", null=True, blank=True
    )
    document_set_version = models.ForeignKey(
        "documents.DocumentSetVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="index_versions",
    )
    embedding_profile = models.ForeignKey(
        "ingestion.EmbeddingProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="index_versions",
    )
    # Snapshot of the store's fixed geometry so the DAL never has to join a (possibly disabled)
    # profile to know the column type. "vector"/"halfvec"; dimensions <= profile.max_dimensions.
    dimensions = models.PositiveIntegerField(null=True, blank=True)
    index_type = models.CharField(max_length=16, blank=True)
    # True once the per-IndexVersion physical vector store has been provisioned and written.
    store_ready = models.BooleanField(default=False)
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16, choices=IndexStatus.choices, default=IndexStatus.BUILDING
    )
    document_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    pipeline_fingerprint = models.CharField(max_length=64, blank=True)
    parent_index_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_index_versions",
    )
    embedded_document_count = models.PositiveIntegerField(default=0)
    embedded_chunk_count = models.PositiveIntegerField(default=0)
    reused_document_count = models.PositiveIntegerField(default=0)
    reused_chunk_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "version"], name="uniq_index_source_version"),
            models.UniqueConstraint(
                fields=["document_set_version", "embedding_profile", "version"],
                name="uniq_index_docsetver_profile_version",
                condition=models.Q(document_set_version__isnull=False),
            ),
        ]

    def clean(self) -> None:
        if self.source_id and self.organization_id != self.source.organization_id:  # type: ignore[union-attr]
            raise ValidationError("index organization must match source organization")
        if (
            self.document_set_version_id
            and self.document_set_version.organization_id != self.organization_id  # type: ignore[union-attr]
        ):
            raise ValidationError("index organization must match document-set-version organization")
        if self.parent_index_version_id:
            parent = self.parent_index_version
            if parent is None or parent.organization_id != self.organization_id:
                raise ValidationError("parent index must belong to the organization")


class RunStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    RETRY = "retry", "Retry"
    SUCCEEDED = "succeeded", "Succeeded"
    DEAD_LETTER = "dead_letter", "Dead letter"


class IngestionRun(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="ingestion_runs"
    )
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=16, choices=RunStatus.choices, default=RunStatus.QUEUED)
    attempt = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    error_code = models.CharField(max_length=64, blank=True)
    index_version = models.OneToOneField(
        IndexVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="run"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def clean(self) -> None:
        if self.source_id and self.organization_id != self.source.organization_id:
            raise ValidationError("run organization must match source organization")
        if self.max_attempts < 1:
            raise ValidationError({"max_attempts": "must be at least 1"})


class TenantConfluenceProfileGrant(models.Model):
    """Platform approval for one profile, tenant, and exact document set."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="confluence_profile_grants"
    )
    document_set = models.ForeignKey(
        "documents.DocumentSet",
        on_delete=models.CASCADE,
        related_name="confluence_profile_grants",
    )
    confluence_profile = models.ForeignKey(
        ConfluenceProfile, on_delete=models.PROTECT, related_name="tenant_document_set_grants"
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "document_set", "confluence_profile"],
                name="uniq_tenant_docset_confluence_grant",
            )
        ]

    def __str__(self) -> str:
        return (
            f"confluence-grant:{self.organization_id}:"
            f"{self.document_set_id}:{self.confluence_profile_id}"
        )

    def clean(self) -> None:
        if self.document_set_id and self.document_set.organization_id != self.organization_id:
            raise ValidationError("Confluence grant document set must belong to the organization")


class TenantRestPullProfileGrant(models.Model):
    """Platform approval for one REST profile, tenant, and exact document set."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="rest_pull_profile_grants"
    )
    document_set = models.ForeignKey(
        "documents.DocumentSet", on_delete=models.CASCADE, related_name="rest_pull_profile_grants"
    )
    rest_profile = models.ForeignKey(
        RestPullProfile, on_delete=models.PROTECT, related_name="tenant_document_set_grants"
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "document_set", "rest_profile"],
                name="uniq_tenant_docset_rest_grant",
            )
        ]

    def __str__(self) -> str:
        return f"rest-grant:{self.organization_id}:{self.document_set_id}:{self.rest_profile_id}"

    def clean(self) -> None:
        if self.document_set_id and self.document_set.organization_id != self.organization_id:
            raise ValidationError("REST grant document set must belong to the organization")


class RestSyncStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    RETRY = "retry", "Retry"
    SUCCEEDED = "succeeded", "Succeeded"
    DEAD_LETTER = "dead_letter", "Dead letter"


class RestSyncRun(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="rest_sync_runs"
    )
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="rest_sync_runs")
    rest_profile = models.ForeignKey(
        RestPullProfile, on_delete=models.PROTECT, related_name="sync_runs"
    )
    rest_contract = models.ForeignKey(
        RestPullContract, on_delete=models.PROTECT, related_name="sync_runs"
    )
    status = models.CharField(
        max_length=16, choices=RestSyncStatus.choices, default=RestSyncStatus.QUEUED
    )
    attempt = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    error_code = models.CharField(max_length=64, blank=True)
    snapshot_complete = models.BooleanField(default=False)
    material_change = models.BooleanField(default=False)
    discovered_count = models.PositiveIntegerField(default=0)
    changed_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)
    fetched_bytes = models.PositiveBigIntegerField(default=0)
    candidate_set_version = models.ForeignKey(
        "documents.DocumentSetVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rest_sync_runs",
    )
    schedule = models.ForeignKey(
        "ConnectorSyncSchedule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rest_runs",
    )
    schedule_slot = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "schedule_slot"],
                condition=models.Q(schedule__isnull=False, schedule_slot__isnull=False),
                name="uniq_rest_schedule_slot",
            )
        ]

    def clean(self) -> None:
        if self.source_id and self.source.organization_id != self.organization_id:
            raise ValidationError("REST run source must belong to the organization")
        if self.source_id and (
            self.source.rest_profile_id != self.rest_profile_id
            or self.source.rest_contract_id != self.rest_contract_id
        ):
            raise ValidationError("REST run bindings must match its source")
        if not 1 <= self.max_attempts <= 3:
            raise ValidationError({"max_attempts": "must be between 1 and 3"})


class RestDocumentCursor(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="rest_document_cursors"
    )
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="rest_document_cursors"
    )
    external_id = models.CharField(max_length=256)
    external_revision = models.CharField(max_length=256, blank=True)
    content_checksum = models.CharField(max_length=64)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.CASCADE, related_name="rest_cursors"
    )
    document_version = models.ForeignKey(
        "documents.DocumentVersion", on_delete=models.PROTECT, related_name="rest_cursors"
    )
    last_seen_run = models.ForeignKey(
        RestSyncRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="seen_cursors"
    )
    state = models.CharField(
        max_length=16,
        choices=[("active", "Active"), ("missing", "Missing")],
        default="active",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"], name="uniq_rest_source_external_id"
            )
        ]

    def clean(self) -> None:
        if self.source_id and self.source.organization_id != self.organization_id:
            raise ValidationError("REST cursor source must belong to the organization")
        if self.document_id and self.document.organization_id != self.organization_id:
            raise ValidationError("REST cursor document must belong to the organization")
        if self.document_version_id and (
            self.document_version.organization_id != self.organization_id
            or self.document_version.document_id != self.document_id
        ):
            raise ValidationError("REST cursor version must belong to its document and tenant")


class ScheduleAutomationMode(models.TextChoices):
    DRAFT_ONLY = "draft_only", "Draft only"
    STAGE_ONLY = "stage_only", "Publish and build staged index"
    PROMOTE_IF_SAFE = "promote_if_safe", "Promote after existing gates pass"


class ConnectorAutomationStatus(models.TextChoices):
    IDLE = "idle", "Idle"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class ConnectorSyncSchedule(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="connector_sync_schedules"
    )
    source = models.OneToOneField(Source, on_delete=models.CASCADE, related_name="sync_schedule")
    interval_seconds = models.PositiveIntegerField(default=86_400)
    enabled = models.BooleanField(default=False)
    next_run_at = models.DateTimeField()
    last_slot_at = models.DateTimeField(null=True, blank=True)
    automation_mode = models.CharField(
        max_length=24,
        choices=ScheduleAutomationMode.choices,
        default=ScheduleAutomationMode.DRAFT_ONLY,
    )
    embedding_profile = models.ForeignKey(
        "EmbeddingProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connector_schedules",
    )
    ocr_profile = models.ForeignKey(
        "OcrProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connector_schedules",
    )
    configured_by = models.CharField(max_length=255)
    promotion_approved_by = models.CharField(max_length=255, blank=True)
    last_automation_candidate = models.ForeignKey(
        "documents.DocumentSetVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="connector_automation_schedules",
    )
    automation_status = models.CharField(
        max_length=16,
        choices=ConnectorAutomationStatus.choices,
        default=ConnectorAutomationStatus.IDLE,
    )
    automation_error_code = models.CharField(max_length=64, blank=True)

    def clean(self) -> None:
        if self.source_id and self.source.organization_id != self.organization_id:
            raise ValidationError("schedule source must belong to the organization")
        if self.source_id and self.source.connector_type not in {
            ConnectorType.CONFLUENCE_DC,
            ConnectorType.GENERIC_REST,
        }:
            raise ValidationError("schedule source connector is unsupported")
        if not 900 <= self.interval_seconds <= 604_800:
            raise ValidationError({"interval_seconds": "must be between 900 and 604800"})
        if (
            self.automation_mode != ScheduleAutomationMode.DRAFT_ONLY
            and not self.embedding_profile_id
        ):
            raise ValidationError("staging automation requires an embedding profile")
        if (
            self.automation_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE
            and not self.promotion_approved_by
        ):
            raise ValidationError("automatic promotion requires release-manager approval")


class ConnectorSchedulePromotionTarget(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="connector_promotion_targets"
    )
    schedule = models.ForeignKey(
        ConnectorSyncSchedule, on_delete=models.CASCADE, related_name="promotion_targets"
    )
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.CASCADE, related_name="connector_promotion_targets"
    )
    approved_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "scenario"], name="uniq_connector_schedule_scenario"
            )
        ]

    def __str__(self) -> str:
        return f"connector-promotion-target:{self.schedule_id}:{self.scenario_id}"

    def clean(self) -> None:
        if self.schedule_id and self.schedule.organization_id != self.organization_id:
            raise ValidationError("promotion target schedule must belong to the organization")
        if self.scenario_id and self.scenario.project.organization_id != self.organization_id:
            raise ValidationError("promotion target scenario must belong to the organization")


class ConfluenceSyncStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    RETRY = "retry", "Retry"
    SUCCEEDED = "succeeded", "Succeeded"
    DEAD_LETTER = "dead_letter", "Dead letter"


class ConfluenceSyncRun(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="confluence_sync_runs"
    )
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="confluence_sync_runs"
    )
    confluence_profile = models.ForeignKey(
        ConfluenceProfile, on_delete=models.PROTECT, related_name="sync_runs"
    )
    status = models.CharField(
        max_length=16, choices=ConfluenceSyncStatus.choices, default=ConfluenceSyncStatus.QUEUED
    )
    attempt = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    error_code = models.CharField(max_length=64, blank=True)
    snapshot_complete = models.BooleanField(default=False)
    material_change = models.BooleanField(default=False)
    discovered_count = models.PositiveIntegerField(default=0)
    changed_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)
    fetched_bytes = models.PositiveBigIntegerField(default=0)
    candidate_set_version = models.ForeignKey(
        "documents.DocumentSetVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confluence_sync_runs",
    )
    schedule = models.ForeignKey(
        ConnectorSyncSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confluence_runs",
    )
    schedule_slot = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "schedule_slot"],
                condition=models.Q(schedule__isnull=False, schedule_slot__isnull=False),
                name="uniq_confluence_schedule_slot",
            )
        ]

    def clean(self) -> None:
        if self.source_id and self.source.organization_id != self.organization_id:
            raise ValidationError("Confluence run source must belong to the organization")
        if self.source_id and self.source.confluence_profile_id != self.confluence_profile_id:
            raise ValidationError("Confluence run profile must match its source")
        if (
            self.candidate_set_version_id
            and self.candidate_set_version.organization_id != self.organization_id  # type: ignore[union-attr]
        ):
            raise ValidationError("Confluence candidate must belong to the organization")
        if not 1 <= self.max_attempts <= 3:
            raise ValidationError({"max_attempts": "must be between 1 and 3"})


class ConfluenceCursorState(models.TextChoices):
    ACTIVE = "active", "Active"
    MISSING = "missing", "Missing"


class ConfluenceDocumentCursor(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="confluence_document_cursors"
    )
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="confluence_document_cursors"
    )
    external_page_id = models.CharField(max_length=64)
    root_page_id = models.CharField(max_length=64)
    external_version = models.PositiveBigIntegerField()
    external_updated_at = models.DateTimeField(null=True, blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.CASCADE, related_name="confluence_cursors"
    )
    document_version = models.ForeignKey(
        "documents.DocumentVersion",
        on_delete=models.PROTECT,
        related_name="confluence_cursors",
    )
    last_seen_run = models.ForeignKey(
        ConfluenceSyncRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="seen_cursors",
    )
    state = models.CharField(
        max_length=16, choices=ConfluenceCursorState.choices, default=ConfluenceCursorState.ACTIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_page_id"],
                name="uniq_confluence_source_external_page",
            )
        ]

    def clean(self) -> None:
        if self.source_id and self.source.organization_id != self.organization_id:
            raise ValidationError("Confluence cursor source must belong to the organization")
        if self.document_id and self.document.organization_id != self.organization_id:
            raise ValidationError("Confluence cursor document must belong to the organization")
        if self.document_version_id:
            if self.document_version.organization_id != self.organization_id:
                raise ValidationError("Confluence cursor version must belong to the organization")
            if self.document_version.document_id != self.document_id:
                raise ValidationError("Confluence cursor version must belong to its document")
        if self.last_seen_run_id:
            last_seen_run = self.last_seen_run
            if last_seen_run is None or last_seen_run.organization_id != self.organization_id:
                raise ValidationError("Confluence cursor run must belong to the organization")


class IndexedDocument(TimeStampedModel):
    """A *build* artifact: the content that entered one immutable ``IndexVersion``.

    This is not the tenant's managed content object — that is the content-plane
    ``apps.documents.Document`` (Phase 2 P2). This model records what a specific index
    build ingested (source URI, checksum, title) so retrieved chunks can cite it. It was
    renamed from ``Document`` to free that name for the content plane; the rename is a
    ``RenameModel`` that preserves rows, primary keys, and FK relationships.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="documents"
    )
    index_version = models.ForeignKey(
        IndexVersion, on_delete=models.CASCADE, related_name="documents"
    )
    source_uri = models.TextField()
    title = models.CharField(max_length=500, blank=True)
    checksum = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["index_version", "source_uri"], name="uniq_document_index_uri"
            )
        ]


class Chunk(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="chunks")
    index_version = models.ForeignKey(IndexVersion, on_delete=models.CASCADE, related_name="chunks")
    document = models.ForeignKey(IndexedDocument, on_delete=models.CASCADE, related_name="chunks")
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "ordinal"], name="uniq_chunk_document_ordinal"
            )
        ]
        indexes = [
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]


class EmbeddingIndexType(models.TextChoices):
    VECTOR = "vector", "vector (D<=2000)"
    HALFVEC = "halfvec", "halfvec (D<=4000)"


class EmbeddingProfileStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class EmbeddingProfile(models.Model):
    """Platform-managed, immutable, revisioned embedding-egress configuration.

    Mirrors the P1 ``ModelProfile`` catalog (ADR-0002/0005): artifacts and the runtime reference
    a profile **by id only** — endpoint/host/scheme/secret/TLS are never author/tenant-supplied.
    Adds the embedding-specific ``dimensions``/``index_type``/``normalize`` that fix the physical
    per-``IndexVersion`` vector store (ADR-0003). A used profile is never modified in place; any
    change to provider/model/dimensions/index_type creates a new revision.
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    logical_id = models.CharField(max_length=128)
    revision = models.PositiveIntegerField()
    provider = models.CharField(max_length=64, default="openai_compatible")
    scheme = models.CharField(max_length=8, default="https")
    host = models.CharField(max_length=253)
    port = models.PositiveIntegerField(default=443)
    path = models.CharField(max_length=512, default="/v1/embeddings")
    model = models.CharField(max_length=200)
    secret_ref = models.CharField(max_length=160)
    dimensions = models.PositiveIntegerField()
    index_type = models.CharField(
        max_length=16, choices=EmbeddingIndexType.choices, default=EmbeddingIndexType.VECTOR
    )
    normalize = models.BooleanField(default=True)
    distance_metric = models.CharField(max_length=16, default="cosine")
    timeout_seconds = models.PositiveIntegerField(default=30)
    max_response_bytes = models.PositiveIntegerField(default=5_000_000)
    max_batch_size = models.PositiveIntegerField(default=64)
    status = models.CharField(
        max_length=16,
        choices=EmbeddingProfileStatus.choices,
        default=EmbeddingProfileStatus.ACTIVE,
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["logical_id", "revision"],
                name="uniq_embedding_profile_logical_revision",
            )
        ]

    def __str__(self) -> str:
        return f"embedding-profile:{self.logical_id}:r{self.revision}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            update_fields = set(kwargs.get("update_fields") or [])
            if not update_fields or not update_fields <= {"status"}:
                raise ValueError("EmbeddingProfile is immutable; only status may change")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("EmbeddingProfile is immutable and cannot be deleted")

    @property
    def max_dimensions(self) -> int:
        return (
            HALFVEC_MAX_DIMENSIONS
            if self.index_type == EmbeddingIndexType.HALFVEC
            else VECTOR_MAX_DIMENSIONS
        )


class TenantEmbeddingProfileGrant(models.Model):
    """Allowlists a platform ``EmbeddingProfile`` to one tenant (tenants cannot self-create)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="embedding_profile_grants"
    )
    embedding_profile = models.ForeignKey(
        EmbeddingProfile, on_delete=models.CASCADE, related_name="tenant_grants"
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "embedding_profile"],
                name="uniq_tenant_embedding_grant",
            )
        ]

    def __str__(self) -> str:
        return f"embedding-grant:{self.organization_id}:{self.embedding_profile_id}"


class OcrProfileStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class OcrProfile(models.Model):
    """Platform-managed immutable OCR API destination and operational bounds."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    logical_id = models.CharField(max_length=128)
    revision = models.PositiveIntegerField()
    provider = models.CharField(max_length=64, default="async_markdown_ocr")
    scheme = models.CharField(max_length=8, default="https")
    host = models.CharField(max_length=253)
    port = models.PositiveIntegerField(default=443)
    base_path = models.CharField(max_length=512, default="/api/v1")
    secret_ref = models.CharField(max_length=160)
    timeout_seconds = models.PositiveIntegerField(default=30)
    poll_interval_seconds = models.PositiveSmallIntegerField(default=2)
    max_poll_attempts = models.PositiveIntegerField(default=150)
    max_upload_bytes = models.PositiveBigIntegerField(default=52_428_800)
    max_pages = models.PositiveIntegerField(default=500)
    max_result_bytes = models.PositiveIntegerField(default=10_000_000)
    status = models.CharField(
        max_length=16, choices=OcrProfileStatus.choices, default=OcrProfileStatus.ACTIVE
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["logical_id", "revision"], name="uniq_ocr_profile_logical_revision"
            )
        ]

    def __str__(self) -> str:
        return f"ocr-profile:{self.logical_id}:r{self.revision}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            update_fields = set(kwargs.get("update_fields") or [])
            if not update_fields or not update_fields <= {"status"}:
                raise ValueError("OcrProfile is immutable; only status may change")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("OcrProfile is immutable and cannot be deleted")


class TenantOcrProfileGrant(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="ocr_profile_grants"
    )
    ocr_profile = models.ForeignKey(
        OcrProfile, on_delete=models.CASCADE, related_name="tenant_grants"
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "ocr_profile"], name="uniq_tenant_ocr_grant"
            )
        ]

    def __str__(self) -> str:
        return f"ocr-grant:{self.organization_id}:{self.ocr_profile_id}"


class OcrJobStatus(models.TextChoices):
    SUBMITTING = "submitting", "Submitting"
    SUBMITTED = "submitted", "Submitted"
    OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"
    RESULT_PERSISTED = "result_persisted", "Result persisted"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    FAILED = "failed", "Failed"


class DocumentOcrJob(TimeStampedModel):
    """Recoverable OCR lineage; ACK is sent only after result object persistence."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="document_ocr_jobs"
    )
    document_version = models.ForeignKey(
        "documents.DocumentVersion", on_delete=models.CASCADE, related_name="ocr_jobs"
    )
    ocr_profile = models.ForeignKey(OcrProfile, on_delete=models.PROTECT, related_name="jobs")
    job_id = models.UUIDField(unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=24, choices=OcrJobStatus.choices, default=OcrJobStatus.SUBMITTING
    )
    result_object_key = models.CharField(max_length=512, blank=True)
    result_checksum = models.CharField(max_length=64, blank=True)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document_version", "ocr_profile"],
                name="uniq_document_ocr_profile_job",
            )
        ]

    def clean(self) -> None:
        if self.document_version_id and (
            self.document_version.organization_id != self.organization_id
        ):
            raise ValidationError("OCR job document version must belong to the organization")
