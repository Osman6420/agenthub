"""Shared connection identity without duplicating profile configuration or grants."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum, validate_body
from apps.audit.services import record_event
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.models import (
    ConfluenceProfile,
    Connection,
    ConnectionKind,
    ConnectorType,
    EmbeddingProfile,
    McpResourceProfile,
    OcrProfile,
    RestPullProfile,
    Source,
)
from apps.orchestration.models import ModelProfile
from apps.tools.models import ToolDefinition

_REST_FIELDS = (
    "logical_id",
    "revision",
    "scheme",
    "host",
    "port",
    "path_prefix",
    "method",
    "auth_mode",
    "secret_ref",
    "api_key_header_name",
    "timeout_seconds",
    "max_response_bytes",
    "max_total_bytes",
    "max_requests",
    "max_items",
    "max_pages",
    "max_retries",
    "max_decoded_item_bytes",
)
_CONFLUENCE_FIELDS = (
    "logical_id",
    "revision",
    "provider",
    "scheme",
    "host",
    "port",
    "context_path",
    "secret_ref",
    "network_policy_id",
    "timeout_seconds",
    "page_size",
    "max_pages",
    "max_depth",
    "max_requests",
    "max_retries",
    "max_response_bytes",
    "max_page_body_bytes",
    "max_total_bytes",
)
_MCP_FIELDS = (
    "logical_id",
    "revision",
    "protocol_version",
    "destination",
    "resource_prefixes",
    "mime_types",
    "limits",
    "secret_ref",
)
_MODEL_FIELDS = (
    "logical_id",
    "revision",
    "provider",
    "scheme",
    "host",
    "port",
    "path",
    "model",
    "secret_ref",
    "timeout_seconds",
    "max_response_bytes",
    "max_output_tokens",
)
_EMBEDDING_FIELDS = (
    "logical_id",
    "revision",
    "provider",
    "scheme",
    "host",
    "port",
    "path",
    "model",
    "secret_ref",
    "dimensions",
    "index_type",
    "normalize",
    "distance_metric",
    "timeout_seconds",
    "max_response_bytes",
    "max_batch_size",
)
_OCR_FIELDS = (
    "logical_id",
    "revision",
    "provider",
    "scheme",
    "host",
    "port",
    "base_path",
    "secret_ref",
    "timeout_seconds",
    "poll_interval_seconds",
    "max_poll_attempts",
    "max_upload_bytes",
    "max_pages",
    "max_result_bytes",
)
Profile = (
    RestPullProfile
    | ConfluenceProfile
    | McpResourceProfile
    | ModelProfile
    | EmbeddingProfile
    | OcrProfile
    | ToolDefinition
)
_PROFILE_TYPES = (
    (ConnectionKind.REST_PULL, "rest_profile", RestPullProfile),
    (ConnectionKind.CONFLUENCE, "confluence_profile", ConfluenceProfile),
    (ConnectionKind.MCP_RESOURCE, "mcp_resource_profile", McpResourceProfile),
    (ConnectionKind.MODEL, "model_profile", ModelProfile),
    (ConnectionKind.EMBEDDING, "embedding_profile", EmbeddingProfile),
    (ConnectionKind.OCR, "ocr_profile", OcrProfile),
    (ConnectionKind.TOOL, "tool_definition", ToolDefinition),
)


def _profile_field(profile: Profile) -> str:
    for _, field, model in _PROFILE_TYPES:
        if isinstance(profile, model):
            return field
    raise ConnectionError("CONNECTION_KIND_UNSUPPORTED")


class ConnectionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _profile_identity(profile: Profile) -> tuple[str, str]:
    """Validate the existing typed config; never resolve or copy its credential."""
    from apps.ingestion.confluence_schema import validate_confluence_profile_fields
    from apps.ingestion.rest_services import _canonical_destination, _validate_profile_fields

    try:
        if isinstance(profile, RestPullProfile):
            payload = {name: getattr(profile, name) for name in _REST_FIELDS}
            _validate_profile_fields(payload)
            canonical = _canonical_destination(
                f"{profile.scheme}://{profile.host}:{profile.port}", profile.path_prefix
            )
            if canonical != (profile.scheme, profile.host, profile.port, profile.path_prefix):
                raise ConnectionError("CONNECTION_PROFILE_INVALID")
            kind = ConnectionKind.REST_PULL
        elif isinstance(profile, ConfluenceProfile):
            payload = {name: getattr(profile, name) for name in _CONFLUENCE_FIELDS}
            validate_confluence_profile_fields(**payload)
            kind = ConnectionKind.CONFLUENCE
        elif isinstance(profile, McpResourceProfile):
            from apps.ingestion.mcp_schema import validate_mcp_profile

            payload = {name: getattr(profile, name) for name in _MCP_FIELDS}
            validate_mcp_profile(payload)
            kind = ConnectionKind.MCP_RESOURCE
        elif isinstance(profile, ModelProfile):
            from apps.orchestration.profile_schema import validate_profile_fields

            payload = {name: getattr(profile, name) for name in _MODEL_FIELDS}
            validate_profile_fields(**payload)
            kind = ConnectionKind.MODEL
        elif isinstance(profile, EmbeddingProfile):
            from apps.ingestion.embedding_schema import validate_embedding_profile_fields

            payload = {name: getattr(profile, name) for name in _EMBEDDING_FIELDS}
            validate_embedding_profile_fields(**payload)
            kind = ConnectionKind.EMBEDDING
        elif isinstance(profile, OcrProfile):
            from apps.ingestion.ocr_schema import validate_ocr_profile_fields

            payload = {name: getattr(profile, name) for name in _OCR_FIELDS}
            validate_ocr_profile_fields(**payload)
            kind = ConnectionKind.OCR
        elif isinstance(profile, ToolDefinition):
            validate_body(ArtifactType.TOOL_DEFINITION, profile.manifest)
            spec = profile.manifest["spec"]
            if (
                compute_checksum(profile.manifest) != profile.checksum
                or profile.protocol != spec["protocol"]
                or profile.risk != spec["risk"]
                or profile.side_effecting != spec["side_effecting"]
                or profile.organization.slug not in spec["allowed_organizations"]
            ):
                raise ConnectionError("CONNECTION_PROFILE_INVALID")
            payload = {
                "organization_id": profile.organization_id,
                "logical_id": profile.logical_id,
                "revision": profile.version,
                "manifest_checksum": profile.checksum,
            }
            kind = ConnectionKind.TOOL
        else:
            raise ConnectionError("CONNECTION_KIND_UNSUPPORTED")
        return kind, compute_checksum(
            {"contract": "connection-profile/v1", "kind": kind, "config": payload}
        )
    except (ValueError, TypeError, AttributeError, McpResourceError):
        raise ConnectionError("CONNECTION_PROFILE_INVALID") from None


def verify_connection(connection: Connection) -> Profile:
    """Resolve exact immutable lineage; visibility of this record grants no use permission."""
    profile: Any = None
    populated = [
        (kind, model, getattr(connection, f"{field}_id"))
        for kind, field, model in _PROFILE_TYPES
        if getattr(connection, f"{field}_id") is not None
    ]
    if len(populated) == 1 and populated[0][0] == connection.kind:
        _, model, pk = populated[0]
        profile = model.objects.filter(pk=pk).first()
    if profile is None:
        raise ConnectionError("CONNECTION_PROFILE_UNRESOLVED")
    kind, checksum = _profile_identity(profile)
    if (
        connection.kind != kind
        or connection.logical_id != profile.logical_id
        or connection.revision != _profile_revision(profile)
        or connection.organization_id != _profile_organization(profile)
        or connection.profile_checksum != checksum
    ):
        raise ConnectionError("CONNECTION_PROFILE_MISMATCH")
    return profile


def _profile_revision(profile: Profile) -> int:
    return profile.version if isinstance(profile, ToolDefinition) else profile.revision


def _profile_organization(profile: Profile) -> int | None:
    return profile.organization_id if isinstance(profile, ToolDefinition) else None


@transaction.atomic
def materialize_connection(
    *, profile: Profile, actor: str, require_active: bool = False
) -> Connection:
    """Internal exact-profile mapping after canonical profile/source authorization.

    This cannot register a destination or grant access. Locking the existing profile
    serializes concurrent materialization and subsequent protected source binding.
    """
    if (
        not isinstance(profile, tuple(model for _, _, model in _PROFILE_TYPES))
        or profile.pk is None
    ):
        raise ConnectionError("CONNECTION_PROFILE_UNRESOLVED")
    field = _profile_field(profile)
    existing = Connection.objects.filter(**{f"{field}_id": profile.pk}).first()
    if existing is not None:
        current = verify_connection(existing)
        if require_active and current.status != "active":
            raise ConnectionError("CONNECTION_PROFILE_DISABLED")
        return existing
    # Only profile registration/migration needs this writer path. A normal app
    # role reads the migration-materialized identity without locking global catalogs.
    profiles = type(profile).objects.all()
    if not isinstance(profile, ToolDefinition):
        profiles = profiles.select_for_update()
    # Tool bodies are SQL-sealed before mapping. Their existing INSERT-only app
    # role needs no UPDATE grant just to acquire a row lock. The unique relation
    # serializes concurrent inserts; verify the winning exact identity below.
    current_profile = profiles.filter(pk=profile.pk).first()
    if current_profile is None:
        raise ConnectionError("CONNECTION_PROFILE_UNRESOLVED")
    profile = current_profile
    if require_active and profile.status != "active":
        raise ConnectionError("CONNECTION_PROFILE_DISABLED")
    kind, checksum = _profile_identity(profile)
    field = _profile_field(profile)
    try:
        connection, created = Connection.objects.get_or_create(
            **{field: profile},
            defaults={
                "kind": kind,
                "logical_id": profile.logical_id,
                "revision": _profile_revision(profile),
                "organization_id": _profile_organization(profile),
                "profile_checksum": checksum,
                "created_by": actor,
            },
        )
    except ValidationError:
        # save() calls full_clean(): a concurrent winner can become visible
        # between get_or_create's lookup and its uniqueness validation. Django
        # retries IntegrityError, but not this pre-insert ValidationError.
        winner = Connection.objects.filter(**{f"{field}_id": profile.pk}).first()
        if winner is None:
            raise
        connection, created = winner, False
    verify_connection(connection)
    if created:
        record_event(
            actor_type="system",
            actor_id=actor,
            action="connection.identity.materialized",
            outcome="success",
            organization_id=connection.organization_id,
            resource_type="connection",
            resource_id=str(connection.public_id),
            reason="EXACT_PROFILE_REVISION",
            after={
                "kind": kind,
                "profile_id": str(
                    profile.pk if isinstance(profile, ToolDefinition) else profile.public_id
                ),
            },
        )
    return connection


def verify_source_connection(source: Source) -> Profile | None:
    """Permit explicit legacy absence; reject any mismatched new source pointer."""
    if source.connection_id is None:
        return None
    connection = Connection.objects.filter(pk=source.connection_id).first()
    if connection is None:
        raise ConnectionError("CONNECTION_UNRESOLVED")
    profile = verify_connection(connection)
    if not (
        (
            source.connector_type == ConnectorType.GENERIC_REST
            and isinstance(profile, RestPullProfile)
            and source.rest_profile_id == profile.pk
        )
        or (
            source.connector_type == ConnectorType.CONFLUENCE_DC
            and isinstance(profile, ConfluenceProfile)
            and source.confluence_profile_id == profile.pk
        )
        or (
            source.connector_type == ConnectorType.MCP_RESOURCE
            and isinstance(profile, McpResourceProfile)
        )
    ):
        raise ConnectionError("SOURCE_CONNECTION_MISMATCH")
    return profile


@transaction.atomic
def _attach_source_connection(*, source: Source, actor: Any, request_id: str = "") -> Source:
    """Explicitly map one legacy source; preserve its profile, config, cursors and status."""
    from apps.tenancy.context import set_tenant_context
    from apps.tenancy.models import Organization
    from apps.tenancy.services import can_manage_documents

    set_tenant_context(source.organization_id)
    Organization.objects.select_for_update().get(pk=source.organization_id)
    locked = (
        Source.objects.select_for_update(of=("self",))
        .select_related("document_set")
        .filter(pk=source.pk, organization_id=source.organization_id)
        .first()
    )
    if (
        locked is None
        or locked.document_set is None
        or not can_manage_documents(actor, source.organization_id, document_set=locked.document_set)
    ):
        raise ConnectionError("SOURCE_CONNECTION_FORBIDDEN")
    if locked.connection_id is not None:
        verify_source_connection(locked)
        return locked
    if locked.connector_type == ConnectorType.GENERIC_REST:
        identity = Connection.objects.filter(rest_profile_id=locked.rest_profile_id).first()
    elif locked.connector_type == ConnectorType.CONFLUENCE_DC:
        identity = Connection.objects.filter(
            confluence_profile_id=locked.confluence_profile_id
        ).first()
    else:
        raise ConnectionError("CONNECTION_KIND_UNSUPPORTED")
    if identity is None:
        raise ConnectionError("CONNECTION_PROFILE_NOT_MAPPED")
    locked.connection = identity
    verify_source_connection(locked)
    locked.save(update_fields=["connection", "updated_at"])
    record_event(
        actor_type="user",
        actor_id=str(actor.pk),
        action="source.connection.attached",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="source",
        resource_id=str(locked.pk),
        reason="EXACT_PROFILE_REVISION",
        request_id=request_id,
        after={"connection_id": str(identity.public_id)},
    )
    return locked


def attach_source_connection(*, source: Source, actor: Any, request_id: str = "") -> Source:
    """Keep a denied mapping auditable after rolling back its mutation transaction."""
    from apps.tenancy.context import set_tenant_context

    try:
        return _attach_source_connection(source=source, actor=actor, request_id=request_id)
    except ConnectionError as exc:
        if exc.code == "SOURCE_CONNECTION_FORBIDDEN":
            with transaction.atomic():
                set_tenant_context(source.organization_id)
                record_event(
                    actor_type="user",
                    actor_id=str(getattr(actor, "pk", "anonymous")),
                    action="source.connection.attached",
                    outcome="deny",
                    organization_id=source.organization_id,
                    resource_type="source",
                    resource_id=str(source.pk),
                    reason=exc.code,
                    request_id=request_id,
                )
        raise
