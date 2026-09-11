"""Typed MCP/Confluence configuration revisions on the shared source family."""

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max

from apps.ingestion.confluence import ConfluenceError
from apps.ingestion.confluence_schema import (
    ConfluenceValidationError,
    normalize_confluence_source_config,
)
from apps.ingestion.confluence_services import (
    ConfluenceAuthorizationError,
    ConfluenceServiceError,
    create_confluence_source,
)
from apps.ingestion.connections import verify_connection
from apps.ingestion.connector_jobs import source_checksum
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.mcp_schema import validate_mcp_source_config
from apps.ingestion.mcp_services import create_mcp_resource_source
from apps.ingestion.models import (
    ConfluenceProfile,
    Connection,
    McpResourceProfile,
    Source,
    SourceConfigurationRevision,
    TenantConfluenceProfileGrant,
    TenantMcpResourceGrant,
)
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError
from apps.ingestion.rest_setup_schedule import setup_preparation_policy
from apps.ingestion.revision_schedule import validate_revision_schedule
from apps.ingestion.source_revisions import (
    REVISION_ERRORS,
    _audit,
    _authorize,
    configuration_token,
    revision_for,
    schedule_for_edit,
)
from apps.tenancy.context import set_tenant_context
from apps.tenancy.services import UserLike

RESOURCE_REVISION_ERRORS = (
    *REVISION_ERRORS,
    ConfluenceError,
    ConfluenceValidationError,
    ConfluenceAuthorizationError,
    ConfluenceServiceError,
    McpResourceError,
)


def reviewed_configuration(source: Source, profile_id: UUID, config: dict[str, Any]):
    """Read current exact grant and validate a closed, typed configuration."""
    profile: McpResourceProfile | ConfluenceProfile | None
    if source.connector_type == "mcp_resource":
        profile = McpResourceProfile.objects.filter(public_id=profile_id, status="active").first()
        if (
            profile is None
            or not TenantMcpResourceGrant.objects.filter(
                organization_id=source.organization_id,
                document_set_id=source.document_set_id,
                profile=profile,
                enabled=True,
            ).exists()
        ):
            raise RestAuthorizationError("SOURCE_REVISION_PROFILE_NOT_GRANTED")
        normalized = {
            "resource_prefixes": list(validate_mcp_source_config(config, profile.resource_prefixes))
        }
        mapping = Connection.objects.filter(mcp_resource_profile=profile).first()
    elif source.connector_type == "confluence_dc":
        profile = ConfluenceProfile.objects.filter(public_id=profile_id, status="active").first()
        if (
            profile is None
            or not TenantConfluenceProfileGrant.objects.filter(
                organization_id=source.organization_id,
                document_set_id=source.document_set_id,
                confluence_profile=profile,
            ).exists()
        ):
            raise RestAuthorizationError("SOURCE_REVISION_PROFILE_NOT_GRANTED")
        normalized = normalize_confluence_source_config(config)
        mapping = Connection.objects.filter(confluence_profile=profile).first()
    else:
        raise RestServiceError("SOURCE_REVISION_UNAVAILABLE")
    if mapping is None:
        raise RestServiceError("SOURCE_CONNECTION_REQUIRED")
    if verify_connection(mapping).status != "active":
        raise RestServiceError("SOURCE_REVISION_PROFILE_NOT_GRANTED")
    return profile, normalized, mapping


def create_resource_revision(
    *,
    actor: UserLike,
    source: Source,
    expected: str,
    profile_id: UUID,
    intent: UUID,
    name: str,
    config: dict[str, Any],
    schedule: dict[str, Any] | None = None,
) -> Source:
    try:
        with transaction.atomic():
            source = _authorize(actor, source)
            if (
                not isinstance(intent, UUID)
                or not isinstance(name, str)
                or not 1 <= len(name) <= 200
            ):
                raise RestServiceError("SOURCE_REVISION_INVALID")
            profile, normalized, mapping = reviewed_configuration(source, profile_id, config)
            validate_revision_schedule(schedule)
            if source.document_set is None:
                raise RestServiceError("SOURCE_REVISION_UNAVAILABLE")
            if schedule and "preparation" in schedule:
                setup_preparation_policy(
                    source.document_set, expected=schedule["preparation"], lock=True
                )
            root = revision_for(source)
            root_id = root.root_source_id if root else source.pk
            slug = f"revision-{intent.hex}"
            existing = (
                SourceConfigurationRevision.objects.select_related("source")
                .filter(
                    organization_id=source.organization_id,
                    root_source_id=root_id,
                    source__slug=slug,
                )
                .first()
            )
            if existing is not None:
                saved = existing.source
                if (
                    existing.created_by != str(actor.pk)
                    or existing.base_token != expected
                    or saved.name != name
                    or saved.connection_id != mapping.pk
                    or saved.connector_config != normalized
                    or existing.schedule_config != schedule
                    or existing.checksum != source_checksum(saved)
                ):
                    raise RestServiceError("SOURCE_REVISION_INTENT_CONFLICT")
                return saved
            if expected != configuration_token(source):
                raise RestServiceError("SOURCE_REVISION_CHANGED")
            if root is None:
                SourceConfigurationRevision.objects.create(
                    organization_id=source.organization_id,
                    root_source=source,
                    source=source,
                    number=1,
                    checksum=source_checksum(source),
                    is_current=True,
                    schedule_config=schedule_for_edit(source),
                    created_by=str(actor.pk),
                )
            if isinstance(profile, McpResourceProfile):
                candidate = create_mcp_resource_source(
                    actor=actor,
                    organization=source.organization,
                    document_set=source.document_set,
                    profile=profile,
                    slug=slug,
                    name=name,
                    resource_prefixes=normalized["resource_prefixes"],
                )
            else:
                candidate = create_confluence_source(
                    actor=actor,
                    organization=source.organization,
                    document_set=source.document_set,
                    confluence_profile=profile,
                    slug=slug,
                    name=name,
                    connector_config=normalized,
                )
            number = (
                SourceConfigurationRevision.objects.filter(root_source_id=root_id).aggregate(
                    value=Max("number")
                )["value"]
                or 1
            ) + 1
            SourceConfigurationRevision.objects.create(
                organization_id=source.organization_id,
                root_source_id=root_id,
                source=candidate,
                number=number,
                checksum=source_checksum(candidate),
                base_token=expected,
                schedule_config=schedule,
                created_by=str(actor.pk),
            )
            _audit(actor, candidate, "created", after={"root_source": root_id, "number": number})
            return candidate
    except RESOURCE_REVISION_ERRORS as exc:
        with transaction.atomic():
            set_tenant_context(source.organization_id)
            _audit(
                actor,
                source,
                "created",
                outcome="deny",
                reason=getattr(exc, "code", "SOURCE_REVISION_DENIED"),
            )
        raise
