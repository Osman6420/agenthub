"""Tenant-owned ingestion sources, runs, staged indexes, and vector chunks."""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from pgvector.django import HnswIndex, VectorField

from apps.tenancy.models import Organization, TimeStampedModel

EMBEDDING_DIMENSIONS = 64

# pgvector HNSW dimension limits by column type (ADR-0003): unsupported declared store geometry is
# rejected at ingestion start and never truncated. ADR-0017 only adapts overlong provider output.
VECTOR_MAX_DIMENSIONS = 2000
HALFVEC_MAX_DIMENSIONS = 4000


class RestSetupDraft(TimeStampedModel):
    """Private setup checkpoint; never a connection grant or runnable source."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    document_set = models.ForeignKey("documents.DocumentSet", on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    payload = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    expires_at = models.DateTimeField()
    payload_purged_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_source = models.ForeignKey("Source", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "owner", "expires_at"], name="rest_draft_owner_expiry"
            ),
            models.Index(
                fields=["organization", "expires_at", "id"],
                condition=models.Q(payload_purged_at__isnull=True, completed_source__isnull=True),
                name="rest_draft_retention_queue",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(revision__gte=1), name="rest_draft_revision_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(completed_source__isnull=True) | models.Q(payload={}),
                name="rest_draft_completed_payload_empty",
            ),
            models.CheckConstraint(
                condition=models.Q(payload_purged_at__isnull=True)
                | models.Q(
                    payload={},
                    name="",
                    completed_source__isnull=True,
                    payload_purged_at__gte=models.F("expires_at"),
                ),
                name="rest_draft_purged_payload_empty",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if (
                any(
                    getattr(self, key) != getattr(old, key)
                    for key in (
                        "public_id",
                        "organization_id",
                        "document_set_id",
                        "owner_id",
                        "expires_at",
                    )
                )
                or old.completed_source_id is not None
                or old.payload_purged_at is not None
            ):
                raise ValueError("REST_SETUP_DRAFT_BINDING_IMMUTABLE")
        if self.payload_purged_at is not None and (
            self.pk is None
            or self.payload != {}
            or self.name != ""
            or self.completed_source_id is not None
            or not self.expires_at <= self.payload_purged_at <= timezone.now()
        ):
            raise ValueError("REST_SETUP_DRAFT_PURGE_INVALID")
        if self.document_set.organization_id != self.organization_id:
            raise ValueError("REST_SETUP_DRAFT_SCOPE_INVALID")
        if self.completed_source_id and (
            self.completed_source is None
            or self.completed_source.organization_id != self.organization_id
            or self.completed_source.document_set_id != self.document_set_id
            or self.completed_source.connector_type != "generic_rest"
            or self.completed_source.slug != f"rest-{self.public_id.hex}"
            or self.payload
        ):
            raise ValueError("REST_SETUP_DRAFT_SOURCE_INVALID")
        super().save(*args, **kwargs)


class SourceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class ConnectorType(models.TextChoices):
    HTTPS = "https", "Allowlisted HTTPS"
    S3 = "s3", "S3/MinIO object"
    CONFLUENCE_DC = "confluence_dc", "Confluence Data Center"
    GENERIC_REST = "generic_rest", "Governed generic REST"
    MCP_RESOURCE = "mcp_resource", "MCP belge kaynağı"


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


class McpResourceProfile(models.Model):
    """Immutable resource-only endpoint, platform scope and transport limits."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    logical_id = models.CharField(max_length=128)
    revision = models.PositiveIntegerField()
    protocol_version = models.CharField(max_length=16, default="2025-06-18")
    destination = models.JSONField()
    resource_prefixes = models.JSONField()
    mime_types = models.JSONField()
    limits = models.JSONField(default=dict, blank=True)
    secret_ref = models.CharField(max_length=160, blank=True)
    status = models.CharField(
        max_length=16, choices=SourceStatus.choices, default=SourceStatus.ACTIVE
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["logical_id", "revision"], name="uniq_mcp_resource_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(revision__gte=1), name="mcp_resource_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"mcp-resource-profile:{self.logical_id}:r{self.revision}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            if set(kwargs.get("update_fields") or []) != {"status"}:
                raise ValueError("McpResourceProfile is immutable; only status may change")
        else:
            self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("McpResourceProfile is immutable")

    def clean(self) -> None:
        from apps.ingestion.mcp_schema import validate_mcp_profile

        validate_mcp_profile(
            {
                name: getattr(self, name)
                for name in (
                    "logical_id",
                    "revision",
                    "protocol_version",
                    "destination",
                    "resource_prefixes",
                    "mime_types",
                    "limits",
                    "secret_ref",
                )
            }
        )


class TenantMcpResourceGrant(models.Model):
    """Revocable exact profile/tenant/collection approval; no tool authority."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    document_set = models.ForeignKey("documents.DocumentSet", on_delete=models.PROTECT)
    profile = models.ForeignKey(McpResourceProfile, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=True)
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "document_set", "profile"], name="uniq_mcp_resource_grant"
            )
        ]

    def __str__(self) -> str:
        return f"mcp-resource-grant:{self.organization_id}:{self.document_set_id}:{self.profile_id}"

    def clean(self) -> None:
        if self.document_set_id and self.document_set.organization_id != self.organization_id:
            raise ValidationError("MCP_RESOURCE_GRANT_SCOPE_INVALID")


class ConnectionKind(models.TextChoices):
    REST_PULL = "rest_pull", "REST veri bağlantısı"
    CONFLUENCE = "confluence_dc", "Confluence veri bağlantısı"
    MCP_RESOURCE = "mcp_resource", "MCP belge bağlantısı"
    MODEL = "model", "Yanıt modeli bağlantısı"
    EMBEDDING = "embedding", "Arama modeli bağlantısı"
    OCR = "ocr", "Metin okuma bağlantısı"
    TOOL = "tool", "Araç bağlantısı"


class Connection(models.Model):
    """One immutable identity over an exact governed profile or tenant tool revision.

    Profiles and their existing tenant/set grants remain authoritative; this
    record does not carry credentials, duplicate transport settings or grant access.
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, null=True, blank=True, related_name="connections"
    )
    tool_definition = models.OneToOneField(
        "tools.ToolDefinition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connection_identity",
    )
    model_profile = models.OneToOneField(
        "orchestration.ModelProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connection_identity",
    )
    embedding_profile = models.OneToOneField(
        "EmbeddingProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connection_identity",
    )
    ocr_profile = models.OneToOneField(
        "OcrProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connection_identity",
    )
    mcp_resource_profile = models.OneToOneField(
        McpResourceProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connection_identity",
    )
    kind = models.CharField(max_length=24, choices=ConnectionKind.choices)
    logical_id = models.CharField(max_length=128)
    revision = models.PositiveIntegerField()
    profile_checksum = models.CharField(max_length=64, editable=False)
    rest_profile = models.OneToOneField(
        RestPullProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connection_identity",
    )
    confluence_profile = models.OneToOneField(
        ConfluenceProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connection_identity",
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "logical_id", "revision"],
                condition=models.Q(organization__isnull=True),
                name="uniq_connection_kind_revision",
            ),
            models.UniqueConstraint(
                fields=["organization", "kind", "logical_id", "revision"],
                condition=models.Q(organization__isnull=False),
                name="uniq_connection_org_revision",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="rest_pull",
                        organization__isnull=True,
                        tool_definition__isnull=True,
                        model_profile__isnull=True,
                        embedding_profile__isnull=True,
                        ocr_profile__isnull=True,
                        rest_profile__isnull=False,
                        confluence_profile__isnull=True,
                        mcp_resource_profile__isnull=True,
                    )
                    | models.Q(
                        kind="confluence_dc",
                        organization__isnull=True,
                        tool_definition__isnull=True,
                        model_profile__isnull=True,
                        embedding_profile__isnull=True,
                        ocr_profile__isnull=True,
                        rest_profile__isnull=True,
                        confluence_profile__isnull=False,
                        mcp_resource_profile__isnull=True,
                    )
                    | models.Q(
                        kind="mcp_resource",
                        organization__isnull=True,
                        tool_definition__isnull=True,
                        model_profile__isnull=True,
                        embedding_profile__isnull=True,
                        ocr_profile__isnull=True,
                        rest_profile__isnull=True,
                        confluence_profile__isnull=True,
                        mcp_resource_profile__isnull=False,
                    )
                    | models.Q(
                        kind="model",
                        organization__isnull=True,
                        tool_definition__isnull=True,
                        rest_profile__isnull=True,
                        confluence_profile__isnull=True,
                        mcp_resource_profile__isnull=True,
                        model_profile__isnull=False,
                        embedding_profile__isnull=True,
                        ocr_profile__isnull=True,
                    )
                    | models.Q(
                        kind="embedding",
                        organization__isnull=True,
                        tool_definition__isnull=True,
                        rest_profile__isnull=True,
                        confluence_profile__isnull=True,
                        mcp_resource_profile__isnull=True,
                        model_profile__isnull=True,
                        embedding_profile__isnull=False,
                        ocr_profile__isnull=True,
                    )
                    | models.Q(
                        kind="ocr",
                        organization__isnull=True,
                        tool_definition__isnull=True,
                        rest_profile__isnull=True,
                        confluence_profile__isnull=True,
                        mcp_resource_profile__isnull=True,
                        model_profile__isnull=True,
                        embedding_profile__isnull=True,
                        ocr_profile__isnull=False,
                    )
                    | models.Q(
                        kind="tool",
                        organization__isnull=False,
                        tool_definition__isnull=False,
                        rest_profile__isnull=True,
                        confluence_profile__isnull=True,
                        mcp_resource_profile__isnull=True,
                        model_profile__isnull=True,
                        embedding_profile__isnull=True,
                        ocr_profile__isnull=True,
                    )
                ),
                name="connection_profile_kind_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(revision__gte=1), name="connection_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"connection:{self.kind}:{self.logical_id}:r{self.revision}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise ValueError("Connection is immutable")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("Connection is immutable")

    def clean(self) -> None:
        from apps.ingestion.connections import ConnectionError, verify_connection

        try:
            verify_connection(self)
        except ConnectionError as exc:
            raise ValidationError(str(exc)) from exc


class Source(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="sources")
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    connector_type = models.CharField(max_length=16, choices=ConnectorType.choices)
    connector_config = models.JSONField(default=dict)
    connection = models.ForeignKey(
        Connection, on_delete=models.PROTECT, null=True, blank=True, related_name="sources"
    )
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
                            ConnectorType.MCP_RESOURCE,
                        ],
                        document_set__isnull=False,
                    )
                    | (
                        ~models.Q(
                            connector_type__in=[
                                ConnectorType.CONFLUENCE_DC,
                                ConnectorType.GENERIC_REST,
                                ConnectorType.MCP_RESOURCE,
                            ]
                        )
                        & models.Q(document_set__isnull=True)
                    )
                ),
                name="source_document_set_binding_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(connector_type=ConnectorType.MCP_RESOURCE)
                    | models.Q(connection__isnull=False, document_set__isnull=False)
                ),
                name="source_mcp_binding_required",
            ),
        ]

    def clean(self) -> None:
        if (
            self.pk is not None
            and self.connection_id is None
            and Source.objects.filter(pk=self.pk, connection__isnull=False).exists()
        ):
            raise ValidationError("SOURCE_CONNECTION_DOWNGRADE")
        if self.connection_id is not None:
            from apps.ingestion.connections import ConnectionError, verify_source_connection

            try:
                verify_source_connection(self)
            except ConnectionError as exc:
                raise ValidationError(str(exc)) from exc
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
            ConnectorType.MCP_RESOURCE: {"resource_prefixes"},
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
        elif self.connector_type == ConnectorType.MCP_RESOURCE:
            from apps.ingestion.mcp_schema import validate_mcp_source_config

            if self.connection is None or self.document_set is None:
                raise ValidationError("MCP_RESOURCE_SOURCE_BINDING_REQUIRED")
            profile = self.connection.mcp_resource_profile
            if profile is None or self.document_set.organization_id != self.organization_id:
                raise ValidationError("MCP_RESOURCE_SOURCE_SCOPE_INVALID")
            validate_mcp_source_config(self.connector_config, profile.resource_prefixes)
        elif (
            self.confluence_profile_id
            or self.rest_profile_id
            or self.rest_contract_id
            or self.document_set_id
        ):
            raise ValidationError("unbound source cannot have governed connector bindings")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.connector_type in {
            ConnectorType.CONFLUENCE_DC,
            ConnectorType.GENERIC_REST,
            ConnectorType.MCP_RESOURCE,
        }:
            self.clean()
        if self.pk is not None:
            if SourceConfigurationRevision.objects.filter(source_id=self.pk).exists():
                sealed = Source.objects.get(pk=self.pk)
                if any(
                    getattr(self, field.attname) != getattr(sealed, field.attname)
                    for field in self._meta.concrete_fields
                    if field.name not in {"status", "updated_at"}
                ):
                    raise ValueError("SOURCE_REVISION_CONFIG_IMMUTABLE")
            previous = (
                Source.objects.filter(pk=self.pk)
                .values(
                    "connector_type",
                    "confluence_profile_id",
                    "rest_profile_id",
                    "rest_contract_id",
                    "document_set_id",
                    "connection_id",
                )
                .first()
            )
            if previous is not None and (
                previous["connector_type"]
                in {
                    ConnectorType.CONFLUENCE_DC,
                    ConnectorType.GENERIC_REST,
                    ConnectorType.MCP_RESOURCE,
                }
                or self.connector_type
                in {
                    ConnectorType.CONFLUENCE_DC,
                    ConnectorType.GENERIC_REST,
                    ConnectorType.MCP_RESOURCE,
                }
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
                if (
                    self.connector_type == ConnectorType.MCP_RESOURCE
                    and previous["connection_id"] != self.connection_id
                ):
                    raise ValueError("MCP_RESOURCE_SOURCE_BINDING_IMMUTABLE")
        super().save(*args, **kwargs)

    @property
    def is_active(self) -> bool:
        return self.status == SourceStatus.ACTIVE


class SourceConfigurationRevision(models.Model):
    """Immutable source configuration lineage; one selected writer per family."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    root_source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="revisions")
    source = models.OneToOneField(
        Source, on_delete=models.PROTECT, related_name="configuration_revision"
    )
    number = models.PositiveIntegerField()
    checksum = models.CharField(max_length=64)
    base_token = models.CharField(max_length=64, blank=True)
    schedule_config = models.JSONField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["root_source", "number"], name="source_revision_number"
            ),
            models.UniqueConstraint(
                fields=["root_source"],
                condition=models.Q(is_current=True),
                name="source_revision_current",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1), name="source_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"source:{self.root_source_id}:r{self.number}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            previous = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field.attname) != getattr(previous, field.attname)
                for field in self._meta.concrete_fields
                if field.name != "is_current"
            ):
                raise ValueError("SOURCE_REVISION_IMMUTABLE")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("SOURCE_REVISION_IMMUTABLE")


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
    chunking_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="chunked_index_versions",
    )
    retrieval_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retrieval_index_versions",
    )
    summary_model_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="summarized_index_versions",
    )
    summary_prompt_contract = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="summary_prompt_index_versions",
    )
    # Snapshot of the store's fixed geometry so the DAL never has to join a (possibly disabled)
    # profile to know the column type. "vector"/"halfvec"; dimensions <= profile.max_dimensions.
    dimensions = models.PositiveIntegerField(null=True, blank=True)
    index_type = models.CharField(max_length=16, blank=True)
    # True once the per-IndexVersion physical vector store has been provisioned and written.
    store_ready = models.BooleanField(default=False)
    # Existing generations stay on their original storage until a verified backfill.
    storage_layout = models.CharField(
        max_length=24,
        choices=[("legacy", "Legacy"), ("shared_v1", "Shared v1")],
        default="legacy",
        db_default="legacy",
    )
    storage_state = models.CharField(
        max_length=16,
        choices=[("new", "New"), ("open", "Open"), ("sealed", "Sealed"), ("retired", "Retired")],
        default="new",
        db_default="new",
    )
    build_request = models.ForeignKey(
        "StagedIndexBuildJob",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attempt_generations",
    )
    build_attempt = models.PositiveSmallIntegerField(null=True, blank=True)
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
                fields=["build_request", "build_attempt"],
                name="uniq_index_build_attempt",
                condition=models.Q(build_request__isnull=False),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(build_request__isnull=True, build_attempt__isnull=True)
                    | models.Q(
                        build_request__isnull=False,
                        build_attempt__isnull=False,
                        build_attempt__gt=0,
                    )
                ),
                name="index_build_attempt_binding",
            ),
            models.UniqueConstraint(
                fields=["document_set_version", "embedding_profile", "version"],
                name="uniq_index_docsetver_profile_version",
                condition=models.Q(document_set_version__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["document_set_version"],
                name="uniq_active_index_per_set_version",
                condition=models.Q(
                    document_set_version__isnull=False,
                    status=IndexStatus.ACTIVE,
                ),
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
        for artifact, expected_type in (
            (self.chunking_profile, "chunking_profile"),
            (self.retrieval_profile, "retrieval_profile"),
            (self.summary_model_profile, "model_profile"),
            (self.summary_prompt_contract, "prompt_template"),
        ):
            if artifact is not None and (
                artifact.organization_id != self.organization_id or artifact.type != expected_type
            ):
                raise ValidationError("index profile provenance is invalid")


class DocumentSetPreparationProfile(TimeStampedModel):
    """Exact, tenant-owned preparation policy used after a set version is published."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="document_preparation_profiles"
    )
    document_set = models.OneToOneField(
        "documents.DocumentSet", on_delete=models.CASCADE, related_name="preparation_profile"
    )
    embedding_profile = models.ForeignKey(
        "ingestion.EmbeddingProfile",
        on_delete=models.PROTECT,
        related_name="document_preparation_profiles",
    )
    chunking_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        related_name="document_preparation_chunking_profiles",
    )
    # Deprecated as a primary control: query-time retrieval now comes from the executing
    # Retrieve node's binding. Existing values are retained as historical provenance, so the
    # column is only relaxed to nullable and never rewritten.
    retrieval_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="document_preparation_retrieval_profiles",
    )
    ocr_profile = models.ForeignKey(
        "ingestion.OcrProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="document_preparation_profiles",
    )
    summary_model_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="document_preparation_summary_models",
    )
    summary_prompt_contract = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="document_preparation_summary_prompts",
    )
    auto_prepare = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["organization", "auto_prepare"])]

    def clean(self) -> None:
        if self.document_set_id and self.document_set.organization_id != self.organization_id:
            raise ValidationError("preparation profile organization must match its document set")
        if (
            self.embedding_profile_id
            and not self.embedding_profile.tenant_grants.filter(
                organization_id=self.organization_id
            ).exists()
        ):
            raise ValidationError("embedding profile is not granted to this organization")
        if self.ocr_profile_id:
            ocr_profile = self.ocr_profile
            if (
                ocr_profile is None
                or not ocr_profile.tenant_grants.filter(
                    organization_id=self.organization_id
                ).exists()
            ):
                raise ValidationError("OCR profile is not granted to this organization")
        for artifact, expected_type in (
            (self.chunking_profile, "chunking_profile"),
            (self.retrieval_profile, "retrieval_profile"),
            (self.summary_model_profile, "model_profile"),
            (self.summary_prompt_contract, "prompt_template"),
        ):
            if artifact is not None and (
                artifact.organization_id != self.organization_id or artifact.type != expected_type
            ):
                raise ValidationError("preparation artifact profile is invalid")
        if bool(self.summary_model_profile_id) != bool(self.summary_prompt_contract_id):
            raise ValidationError("summary model and prompt must be configured together")


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
            ConnectorType.MCP_RESOURCE,
        }:
            raise ValidationError("schedule source connector is unsupported")
        if (
            self.source_id
            and self.source.connector_type == ConnectorType.MCP_RESOURCE
            and self.automation_mode
            not in {
                ScheduleAutomationMode.DRAFT_ONLY,
                ScheduleAutomationMode.STAGE_ONLY,
                ScheduleAutomationMode.PROMOTE_IF_SAFE,
            }
        ):
            raise ValidationError("MCP schedule automation mode is unsupported")
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


class SharedVectorChunk(models.Model):
    """One fixed, tenant-scoped store with distinct managed and legacy identities.

    PostgreSQL migration triggers also enforce generation/document ownership,
    physical vector dimensions and immutable, open-generation-only writes.
    """

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    index_version = models.ForeignKey(
        IndexVersion, on_delete=models.PROTECT, related_name="shared_chunks"
    )
    document_version = models.ForeignKey(
        "documents.DocumentVersion", on_delete=models.PROTECT, null=True, blank=True
    )
    indexed_document = models.ForeignKey(
        IndexedDocument, on_delete=models.PROTECT, null=True, blank=True
    )
    ordinal = models.PositiveIntegerField()
    chunk_kind = models.CharField(
        max_length=16, choices=[("content", "Content"), ("summary", "Summary")], default="content"
    )
    text = models.TextField()
    embedding = VectorField()
    dimensions = models.PositiveIntegerField()
    representation = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(document_version__isnull=False, indexed_document__isnull=True)
                    | models.Q(document_version__isnull=True, indexed_document__isnull=False)
                ),
                name="shared_chunk_exact_document",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(representation="vector", dimensions__in=[64, 768, 1536])
                    | models.Q(representation="halfvec", dimensions__in=[3072, 4000])
                ),
                name="shared_chunk_geometry",
            ),
            models.CheckConstraint(
                condition=models.Q(chunk_kind__in=["content", "summary"]),
                name="shared_chunk_kind",
            ),
            models.UniqueConstraint(
                fields=["index_version", "document_version", "ordinal", "chunk_kind"],
                condition=models.Q(document_version__isnull=False),
                name="shared_chunk_managed_identity",
            ),
            models.UniqueConstraint(
                fields=["index_version", "indexed_document", "ordinal", "chunk_kind"],
                condition=models.Q(indexed_document__isnull=False),
                name="shared_chunk_legacy_identity",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "index_version", "document_version"],
                name="shared_chunk_scope",
            )
        ]

    def __str__(self) -> str:
        return f"shared-chunk:{self.index_version_id}:{self.pk}"


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


class StagedIndexBuildJobStatus(models.TextChoices):
    DISPATCH_PENDING = "dispatch_pending", "Dispatch pending"
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    RETRY_WAIT = "retry_wait", "Retry waiting"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    RECONCILIATION_REQUIRED = "reconciliation_required", "Reconciliation required"


class IngestionJobKind(models.TextChoices):
    INDEX_BUILD = "index_build", "Veri hazırlama"
    REST_SYNC = "rest_sync", "REST veri yenileme"
    CONFLUENCE_SYNC = "confluence_sync", "Confluence veri yenileme"
    MCP_RESOURCE_SYNC = "mcp_resource_sync", "MCP belge yenileme"


class StagedIndexBuildJob(TimeStampedModel):
    """Shared ingestion request authority; legacy table/name and build IDs are preserved."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="staged_index_build_jobs"
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(
        max_length=24,
        choices=IngestionJobKind.choices,
        default=IngestionJobKind.INDEX_BUILD,
        db_default=IngestionJobKind.INDEX_BUILD,
    )
    source = models.ForeignKey(
        Source, on_delete=models.PROTECT, null=True, blank=True, related_name="ingestion_jobs"
    )
    rest_sync_run = models.OneToOneField(
        RestSyncRun, on_delete=models.PROTECT, null=True, blank=True, related_name="ingestion_job"
    )
    confluence_sync_run = models.OneToOneField(
        ConfluenceSyncRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_job",
    )
    source_config_checksum = models.CharField(max_length=64, blank=True, default="", editable=False)
    preparation_job = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="source_jobs"
    )
    document_set_version = models.ForeignKey(
        "documents.DocumentSetVersion",
        on_delete=models.PROTECT,
        related_name="index_build_jobs",
        null=True,
        blank=True,
    )
    embedding_profile = models.ForeignKey(
        EmbeddingProfile,
        on_delete=models.PROTECT,
        related_name="index_build_jobs",
        null=True,
        blank=True,
    )
    ocr_profile = models.ForeignKey(
        OcrProfile,
        on_delete=models.PROTECT,
        related_name="index_build_jobs",
        null=True,
        blank=True,
    )
    chunking_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="index_build_jobs_as_chunking_profile",
    )
    retrieval_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="index_build_jobs_as_retrieval_profile",
    )
    summary_model_profile = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="index_build_jobs_as_summary_model",
    )
    summary_prompt_contract = models.ForeignKey(
        "artifacts.ArtifactVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="index_build_jobs_as_summary_prompt",
    )
    result_index_version = models.OneToOneField(
        IndexVersion,
        on_delete=models.PROTECT,
        related_name="build_job",
        null=True,
        blank=True,
    )
    request_checksum = models.CharField(max_length=64, editable=False)
    pipeline_fingerprint = models.CharField(max_length=64, editable=False)
    requested_by = models.CharField(max_length=255)
    request_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=32,
        choices=StagedIndexBuildJobStatus.choices,
        default=StagedIndexBuildJobStatus.DISPATCH_PENDING,
    )
    attempt = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    documents_completed = models.PositiveIntegerField(default=0)
    chunks_completed = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    dispatch_attempted_at = models.DateTimeField(null=True, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="index_build",
                        document_set_version__isnull=False,
                        embedding_profile__isnull=False,
                        source__isnull=True,
                        rest_sync_run__isnull=True,
                        confluence_sync_run__isnull=True,
                        source_config_checksum="",
                    )
                    | (
                        models.Q(
                            document_set_version__isnull=True,
                            embedding_profile__isnull=True,
                            ocr_profile__isnull=True,
                            chunking_profile__isnull=True,
                            retrieval_profile__isnull=True,
                            summary_model_profile__isnull=True,
                            summary_prompt_contract__isnull=True,
                            result_index_version__isnull=True,
                            source__isnull=False,
                            source_config_checksum__regex=r"^[0-9a-f]{64}$",
                        )
                        & (
                            models.Q(
                                kind="rest_sync",
                                rest_sync_run__isnull=False,
                                confluence_sync_run__isnull=True,
                            )
                            | models.Q(
                                kind="confluence_sync",
                                rest_sync_run__isnull=True,
                                confluence_sync_run__isnull=False,
                            )
                            | models.Q(
                                kind="mcp_resource_sync",
                                rest_sync_run__isnull=True,
                                confluence_sync_run__isnull=True,
                            )
                        )
                    )
                ),
                name="ingestion_job_typed_target",
            ),
            models.CheckConstraint(
                condition=models.Q(preparation_job__isnull=True) | ~models.Q(kind="index_build"),
                name="ingestion_preparation_parent_kind",
            ),
            models.UniqueConstraint(
                fields=["source"],
                condition=models.Q(
                    source__isnull=False,
                    status__in=[
                        "dispatch_pending",
                        "queued",
                        "running",
                        "retry_wait",
                        "reconciliation_required",
                    ],
                ),
                name="uniq_active_ingestion_source_job",
            ),
            # BUG-004: scoped to active statuses only -- a terminal (cancelled/failed) job must
            # never permanently block a fresh request for the same checksum. An unconditional
            # unique constraint here made the combination unrecoverable without a manual DB edit.
            models.UniqueConstraint(
                fields=["organization", "request_checksum"],
                condition=models.Q(
                    status__in=[
                        StagedIndexBuildJobStatus.DISPATCH_PENDING,
                        StagedIndexBuildJobStatus.QUEUED,
                        StagedIndexBuildJobStatus.RUNNING,
                        StagedIndexBuildJobStatus.RETRY_WAIT,
                        StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED,
                    ]
                ),
                name="uniq_staged_job_org_request_checksum",
            ),
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "document_set_version",
                    "embedding_profile",
                    "pipeline_fingerprint",
                ],
                condition=models.Q(
                    status__in=[
                        StagedIndexBuildJobStatus.DISPATCH_PENDING,
                        StagedIndexBuildJobStatus.QUEUED,
                        StagedIndexBuildJobStatus.RUNNING,
                        StagedIndexBuildJobStatus.RETRY_WAIT,
                        StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED,
                    ]
                ),
                name="uniq_active_staged_index_build",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1, max_attempts__lte=10),
                name="staged_job_max_attempts_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt__lte=models.F("max_attempts")),
                name="staged_job_attempt_within_max",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            immutable = (
                StagedIndexBuildJob.objects.filter(pk=self.pk)
                .values(
                    "kind",
                    "source_id",
                    "rest_sync_run_id",
                    "confluence_sync_run_id",
                    "source_config_checksum",
                    "organization_id",
                    "document_set_version_id",
                    "embedding_profile_id",
                    "ocr_profile_id",
                    "chunking_profile_id",
                    "retrieval_profile_id",
                    "summary_model_profile_id",
                    "summary_prompt_contract_id",
                    "request_checksum",
                    "pipeline_fingerprint",
                    "requested_by",
                    "preparation_job_id",
                )
                .first()
            )
            current = {
                "kind": self.kind,
                "source_id": self.source_id,
                "rest_sync_run_id": self.rest_sync_run_id,
                "confluence_sync_run_id": self.confluence_sync_run_id,
                "source_config_checksum": self.source_config_checksum,
                "organization_id": self.organization_id,
                "document_set_version_id": self.document_set_version_id,
                "embedding_profile_id": self.embedding_profile_id,
                "ocr_profile_id": self.ocr_profile_id,
                "chunking_profile_id": self.chunking_profile_id,
                "retrieval_profile_id": self.retrieval_profile_id,
                "summary_model_profile_id": self.summary_model_profile_id,
                "summary_prompt_contract_id": self.summary_prompt_contract_id,
                "request_checksum": self.request_checksum,
                "pipeline_fingerprint": self.pipeline_fingerprint,
                "requested_by": self.requested_by,
            }
            if immutable is not None:
                previous_preparation = immutable["preparation_job_id"]
                if (
                    previous_preparation is not None
                    and previous_preparation != self.preparation_job_id
                ):
                    raise ValueError("INGESTION_PREPARATION_LINK_IMMUTABLE")
                if {
                    key: value for key, value in immutable.items() if key != "preparation_job_id"
                } != current:
                    raise ValueError("staged build request lineage is immutable")
        if self.preparation_job_id is not None:
            evidence = (
                self.rest_sync_run
                if self.kind == IngestionJobKind.REST_SYNC
                else self.confluence_sync_run
                if self.kind == IngestionJobKind.CONFLUENCE_SYNC
                else getattr(self, "resource_snapshot", None)
                if self.kind == IngestionJobKind.MCP_RESOURCE_SYNC
                else None
            )
            target = self.preparation_job
            if (
                self.status != StagedIndexBuildJobStatus.SUCCEEDED
                or evidence is None
                or not evidence.snapshot_complete
                or evidence.candidate_set_version_id is None
                or target is None
                or target.kind != IngestionJobKind.INDEX_BUILD
                or target.organization_id != self.organization_id
                or target.document_set_version_id != evidence.candidate_set_version_id
            ):
                raise ValueError("INGESTION_PREPARATION_LINK_INVALID")
        super().save(*args, **kwargs)


class ResourceSnapshot(TimeStampedModel):
    """Protocol evidence only; the owning common job is the sole state authority."""

    job = models.OneToOneField(
        StagedIndexBuildJob,
        primary_key=True,
        on_delete=models.PROTECT,
        related_name="resource_snapshot",
    )
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    attempt = models.PositiveSmallIntegerField(default=0)
    snapshot_complete = models.BooleanField(default=False)
    material_change = models.BooleanField(default=False)
    discovered_count = models.PositiveIntegerField(default=0)
    changed_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)
    fetched_bytes = models.PositiveBigIntegerField(default=0)
    candidate_set_version = models.ForeignKey(
        "documents.DocumentSetVersion", null=True, blank=True, on_delete=models.PROTECT
    )
    schedule = models.ForeignKey(
        ConnectorSyncSchedule,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resource_runs",
    )
    schedule_slot = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(schedule__isnull=True, schedule_slot__isnull=True)
                    | models.Q(schedule__isnull=False, schedule_slot__isnull=False)
                ),
                name="mcp_snapshot_schedule_pair",
            ),
            models.UniqueConstraint(
                fields=["schedule", "schedule_slot"],
                condition=models.Q(schedule__isnull=False),
                name="mcp_snapshot_schedule_slot_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"resource-snapshot:{self.job_id}"

    @property
    def source(self) -> Source:
        if self.job.source is None:
            raise ValueError("RESOURCE_SNAPSHOT_SOURCE_REQUIRED")
        return self.job.source

    @source.setter
    def source(self, value: Source) -> None:
        self.job.source = value

    @property
    def source_id(self) -> int:
        return self.source.pk

    @property
    def status(self) -> str:
        return self.job.status


class SourceDocumentCursor(TimeStampedModel):
    """Opaque resource identity and last successfully observed attempt; no job state."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="resource_cursors")
    external_id = models.CharField(max_length=2048)
    external_id_hash = models.CharField(max_length=64)
    content_checksum = models.CharField(max_length=64)
    document = models.ForeignKey("documents.Document", on_delete=models.PROTECT)
    document_version = models.ForeignKey("documents.DocumentVersion", on_delete=models.PROTECT)
    last_seen_job = models.ForeignKey(StagedIndexBuildJob, on_delete=models.PROTECT)
    last_seen_attempt = models.PositiveSmallIntegerField()
    state = models.CharField(
        max_length=16, choices=ConfluenceCursorState.choices, default=ConfluenceCursorState.ACTIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id_hash"], name="uniq_source_resource_identity"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["active", "missing"]),
                name="resource_cursor_state_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"resource-cursor:{self.source_id}:{self.pk}"


class StagedIndexBuildOutbox(TimeStampedModel):
    """Identifier-only durable dispatch intent committed with its owning job."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="staged_index_build_outbox"
    )
    job = models.OneToOneField(StagedIndexBuildJob, on_delete=models.CASCADE, related_name="outbox")
    request_checksum = models.CharField(max_length=64, editable=False)
    available_at = models.DateTimeField()
    published_at = models.DateTimeField(null=True, blank=True)
    publish_attempts = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True)
    completion_published_at = models.DateTimeField(null=True, blank=True)
    completion_available_at = models.DateTimeField(null=True, blank=True)
    completion_publish_attempts = models.PositiveIntegerField(default=0)
    completion_error_code = models.CharField(max_length=64, blank=True)


class IngestionWorkerHeartbeat(TimeStampedModel):
    """Platform operational evidence; values are opaque and contain no endpoints or secrets."""

    instance_id = models.UUIDField(unique=True)
    queue_role = models.CharField(max_length=32, default="ingestion")
    service_revision = models.CharField(max_length=64)
    contract_revision = models.PositiveSmallIntegerField()
    config_fingerprint = models.CharField(max_length=64)
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(queue_role="ingestion"), name="worker_heartbeat_ingestion_role"
            )
        ]
