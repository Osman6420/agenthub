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


class Source(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="sources")
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    connector_type = models.CharField(max_length=16, choices=ConnectorType.choices)
    connector_config = models.JSONField(default=dict)
    parser = models.CharField(max_length=32, default="text")
    chunker = models.CharField(max_length=32, default="fixed")
    embedder = models.CharField(max_length=32, default="deterministic")
    status = models.CharField(
        max_length=16, choices=SourceStatus.choices, default=SourceStatus.ACTIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "slug"], name="uniq_source_org_slug")
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
        }
        unknown = set(self.connector_config) - allowed.get(self.connector_type, set())
        if unknown:
            raise ValidationError(
                {"connector_config": f"unsupported keys: {', '.join(sorted(unknown))}"}
            )

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
