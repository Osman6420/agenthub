"""Tenant-owned ingestion sources, runs, staged indexes, and vector chunks."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.tenancy.models import Organization, TimeStampedModel

EMBEDDING_DIMENSIONS = 64


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
    FAILED = "failed", "Failed"


class IndexVersion(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="index_versions"
    )
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="index_versions")
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16, choices=IndexStatus.choices, default=IndexStatus.BUILDING
    )
    document_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "version"], name="uniq_index_source_version")
        ]

    def clean(self) -> None:
        if self.source_id and self.organization_id != self.source.organization_id:
            raise ValidationError("index organization must match source organization")


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
