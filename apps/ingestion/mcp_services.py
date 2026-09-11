"""Resource-only MCP catalog, exact collection approval and source admission."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db import transaction

from apps.audit.services import record_event
from apps.documents.models import DocumentSet, DocumentSetStatus
from apps.ingestion.connections import materialize_connection, verify_source_connection
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.mcp_schema import validate_mcp_source_config
from apps.ingestion.models import (
    Connection,
    ConnectorType,
    McpResourceProfile,
    Source,
    SourceStatus,
    TenantMcpResourceGrant,
)
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization, OrganizationStatus
from apps.tenancy.services import can_manage_documents, is_platform_admin


def _audited[T](
    action: str,
    actor: Any,
    org_id: int | None,
    operation: Callable[[], T],
    target_id: str = "",
) -> T:
    """Success and mutation commit together; denied requests survive their rollback."""

    def audit(outcome: str, reason: str = "", result: Any = None) -> None:
        record_event(
            actor_type="user",
            actor_id=str(getattr(actor, "pk", "anonymous")),
            organization_id=org_id,
            action=action,
            outcome=outcome,
            reason=reason,
            resource_type="mcp_resource",
            resource_id=str(
                getattr(result, "public_id", getattr(result, "pk", None)) or target_id or "new"
            ),
            after={
                key: str(getattr(result, key))
                for key in ("document_set_id", "profile_id", "connection_id")
                if getattr(result, key, None) is not None
            },
        )

    try:
        with transaction.atomic():
            if org_id is not None:
                set_tenant_context(org_id)
            result = operation()
            audit("success", result=result)
            return result
    except McpResourceError as exc:
        with transaction.atomic():
            if org_id is not None:
                set_tenant_context(org_id)
            audit("deny", exc.code)
        raise


def _require_platform(actor: Any) -> None:
    if not is_platform_admin(actor):
        raise McpResourceError("MCP_RESOURCE_PLATFORM_ADMIN_REQUIRED")


def _lock_org(organization_id: int) -> Organization:
    organization = Organization.objects.select_for_update(no_key=True).get(pk=organization_id)
    if organization.status != OrganizationStatus.ACTIVE:
        raise McpResourceError("MCP_RESOURCE_ORGANIZATION_DISABLED")
    return organization


def register_mcp_resource_profile(*, actor: Any, **fields: Any) -> McpResourceProfile:
    def create() -> McpResourceProfile:
        _require_platform(actor)
        from apps.ingestion.mcp_schema import validate_mcp_profile

        validate_mcp_profile(fields)
        profile = McpResourceProfile.objects.create(created_by=str(actor.pk), **fields)
        materialize_connection(profile=profile, actor=str(actor.pk), require_active=True)
        return profile

    return _audited("mcp_resource.profile.created", actor, None, create)


def disable_mcp_resource_profile(*, actor: Any, profile: McpResourceProfile) -> McpResourceProfile:
    def disable() -> McpResourceProfile:
        _require_platform(actor)
        locked = McpResourceProfile.objects.select_for_update().get(pk=profile.pk)
        locked.status = SourceStatus.DISABLED
        locked.save(update_fields=["status"])
        return locked

    return _audited("mcp_resource.profile.disabled", actor, None, disable, str(profile.public_id))


def set_mcp_resource_grant(
    *,
    actor: Any,
    organization: Organization,
    document_set: DocumentSet,
    profile: McpResourceProfile,
    enabled: bool,
) -> TenantMcpResourceGrant:
    def change() -> TenantMcpResourceGrant:
        _require_platform(actor)
        if type(enabled) is not bool:
            raise McpResourceError("MCP_RESOURCE_GRANT_INVALID")
        _lock_org(organization.pk)
        docset = DocumentSet.objects.filter(pk=document_set.pk, organization=organization).first()
        if docset is None:
            raise McpResourceError("MCP_RESOURCE_GRANT_SCOPE_INVALID")
        locked = McpResourceProfile.objects.select_for_update().get(pk=profile.pk)
        if enabled and (
            locked.status != SourceStatus.ACTIVE or docset.status != DocumentSetStatus.ACTIVE
        ):
            raise McpResourceError("MCP_RESOURCE_PROFILE_OR_COLLECTION_DISABLED")
        grant, _ = TenantMcpResourceGrant.objects.update_or_create(
            organization=organization,
            document_set=docset,
            profile=locked,
            defaults={"enabled": enabled},
            create_defaults={"enabled": enabled, "created_by": str(actor.pk)},
        )
        return grant

    return _audited(
        "mcp_resource.grant.enabled" if enabled else "mcp_resource.grant.revoked",
        actor,
        organization.pk,
        change,
    )


def validate_mcp_source(source: Source) -> tuple[Source, McpResourceProfile]:
    """Fresh tenant-scoped authority. Caller keeps this inside a short transaction."""
    current = (
        Source.objects.select_related("document_set", "organization")
        .filter(
            pk=source.pk,
            organization_id=source.organization_id,
            connector_type=ConnectorType.MCP_RESOURCE,
        )
        .first()
    )
    if current is None or current.status != SourceStatus.ACTIVE:
        raise McpResourceError("MCP_RESOURCE_SOURCE_DISABLED_OR_INVALID")
    if (
        current.organization.status != OrganizationStatus.ACTIVE
        or current.document_set is None
        or current.document_set.status != DocumentSetStatus.ACTIVE
    ):
        raise McpResourceError("MCP_RESOURCE_COLLECTION_DISABLED")
    profile = verify_source_connection(current)
    if not isinstance(profile, McpResourceProfile) or profile.status != SourceStatus.ACTIVE:
        raise McpResourceError("MCP_RESOURCE_PROFILE_DISABLED")
    if not TenantMcpResourceGrant.objects.filter(
        organization_id=current.organization_id,
        document_set_id=current.document_set_id,
        profile=profile,
        enabled=True,
    ).exists():
        raise McpResourceError("MCP_RESOURCE_PROFILE_NOT_GRANTED")
    validate_mcp_source_config(current.connector_config, profile.resource_prefixes)
    return current, profile


def create_mcp_resource_source(
    *,
    actor: Any,
    organization: Organization,
    document_set: DocumentSet,
    profile: McpResourceProfile,
    slug: str,
    name: str,
    resource_prefixes: list[str],
) -> Source:
    def create() -> Source:
        _lock_org(organization.pk)
        docset = DocumentSet.objects.filter(pk=document_set.pk, organization=organization).first()
        if docset is None or not can_manage_documents(actor, organization.pk, document_set=docset):
            raise McpResourceError("MCP_RESOURCE_SOURCE_FORBIDDEN")
        identity = Connection.objects.filter(mcp_resource_profile_id=profile.pk).first()
        if identity is None:
            raise McpResourceError("MCP_RESOURCE_PROFILE_UNRESOLVED")
        existing = Source.objects.filter(organization=organization, slug=slug).first()
        if existing is not None:
            if (
                existing.connection_id != identity.pk
                or existing.document_set_id != docset.pk
                or existing.name != name
                or existing.connector_config != {"resource_prefixes": resource_prefixes}
            ):
                raise McpResourceError("MCP_RESOURCE_SOURCE_CONFLICT")
            validate_mcp_source(existing)
            return existing
        source = Source(
            organization=organization,
            document_set=docset,
            connection=identity,
            connector_type=ConnectorType.MCP_RESOURCE,
            connector_config={"resource_prefixes": resource_prefixes},
            slug=slug,
            name=name,
        )
        source.full_clean()
        source.save()
        validate_mcp_source(source)
        return source

    return _audited("mcp_resource.source.created", actor, organization.pk, create)
