"""Governed profile, grant, source, and sync-run services for Confluence Data Center."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.documents.models import DocumentSet, DocumentSetStatus
from apps.ingestion.confluence_schema import (
    canonicalize_confluence_base_url,
    normalize_confluence_source_config,
    validate_confluence_profile_fields,
)
from apps.ingestion.models import (
    ConfluenceProfile,
    ConfluenceProfileStatus,
    ConfluenceSyncRun,
    ConnectorType,
    Source,
    SourceStatus,
    TenantConfluenceProfileGrant,
)
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import UserLike, can_author_scenarios, is_platform_admin
from apps.tools.egress import EgressDenied, validate_private_network_policy


class ConfluenceAuthorizationError(PermissionError):
    pass


class ConfluenceServiceError(ValueError):
    pass


def register_confluence_profile(
    *, actor: UserLike, base_url: str, **fields: Any
) -> ConfluenceProfile:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        _audit_profile_denial(actor_id, "confluence_profile.create", "PLATFORM_ADMIN_REQUIRED")
        raise ConfluenceAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    canonical = canonicalize_confluence_base_url(base_url)
    profile_fields = {
        **fields,
        "provider": "confluence_dc",
        "scheme": canonical.scheme,
        "host": canonical.host,
        "port": canonical.port,
        "context_path": canonical.context_path,
    }
    validate_confluence_profile_fields(**profile_fields)
    try:
        validate_private_network_policy(
            profile_fields["network_policy_id"], settings.CONFLUENCE_NETWORK_POLICIES
        )
    except EgressDenied as exc:
        raise ConfluenceServiceError(exc.code) from exc
    with transaction.atomic():
        try:
            profile = ConfluenceProfile.objects.create(created_by=actor_id, **profile_fields)
        except IntegrityError as exc:
            raise ConfluenceServiceError("CONFLUENCE_PROFILE_CONFLICT") from exc
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="confluence_profile.create",
            outcome=Outcome.SUCCESS,
            resource_type="confluence_profile",
            resource_id=str(profile.public_id),
            after={
                "logical_id": profile.logical_id,
                "revision": profile.revision,
                "provider": profile.provider,
                "status": profile.status,
            },
        )
    return profile


@transaction.atomic
def disable_confluence_profile(
    *, actor: UserLike, confluence_profile: ConfluenceProfile
) -> ConfluenceProfile:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        _audit_profile_denial(
            actor_id,
            "confluence_profile.disable",
            "PLATFORM_ADMIN_REQUIRED",
            resource_id=str(confluence_profile.public_id),
        )
        raise ConfluenceAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    locked = ConfluenceProfile.objects.select_for_update().get(pk=confluence_profile.pk)
    if locked.status != ConfluenceProfileStatus.DISABLED:
        locked.status = ConfluenceProfileStatus.DISABLED
        locked.save(update_fields=["status"])
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="confluence_profile.disable",
            outcome=Outcome.SUCCESS,
            resource_type="confluence_profile",
            resource_id=str(locked.public_id),
        )
    return locked


def grant_confluence_profile(
    *,
    actor: UserLike,
    organization: Organization,
    document_set: DocumentSet,
    confluence_profile: ConfluenceProfile,
) -> TenantConfluenceProfileGrant:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        _audit_profile_denial(
            actor_id,
            "confluence_profile.grant",
            "PLATFORM_ADMIN_REQUIRED",
            organization_id=organization.id,
            resource_id=str(confluence_profile.public_id),
        )
        raise ConfluenceAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    if document_set.organization_id != organization.id:
        _audit_profile_denial(
            actor_id,
            "confluence_profile.grant",
            "CONFLUENCE_DOCUMENT_SET_TENANT_MISMATCH",
            organization_id=organization.id,
            resource_id=str(confluence_profile.public_id),
        )
        raise ConfluenceServiceError("CONFLUENCE_DOCUMENT_SET_TENANT_MISMATCH")
    if confluence_profile.status != ConfluenceProfileStatus.ACTIVE:
        _audit_profile_denial(
            actor_id,
            "confluence_profile.grant",
            "CONFLUENCE_PROFILE_DISABLED",
            organization_id=organization.id,
            resource_id=str(confluence_profile.public_id),
        )
        raise ConfluenceServiceError("CONFLUENCE_PROFILE_DISABLED")
    with transaction.atomic():
        set_tenant_context(organization.id)
        grant = TenantConfluenceProfileGrant(
            organization=organization,
            document_set=document_set,
            confluence_profile=confluence_profile,
            created_by=actor_id,
        )
        grant.full_clean(validate_unique=False, validate_constraints=False)
        try:
            grant, _created = TenantConfluenceProfileGrant.objects.get_or_create(
                organization=organization,
                document_set=document_set,
                confluence_profile=confluence_profile,
                defaults={"created_by": actor_id},
            )
        except IntegrityError as exc:
            raise ConfluenceServiceError("CONFLUENCE_GRANT_CONFLICT") from exc
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="confluence_profile.grant",
            outcome=Outcome.SUCCESS,
            organization_id=organization.id,
            resource_type="confluence_profile",
            resource_id=str(confluence_profile.public_id),
            after={"document_set_id": document_set.pk},
        )
    return grant


def create_confluence_source(
    *,
    actor: UserLike,
    organization: Organization,
    document_set: DocumentSet,
    confluence_profile: ConfluenceProfile,
    slug: str,
    name: str,
    connector_config: dict[str, Any],
) -> Source:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not can_author_scenarios(actor, organization.id):
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="confluence_source.create",
            outcome=Outcome.DENY,
            organization_id=organization.id,
            resource_type="source",
            reason="SCENARIO_AUTHOR_REQUIRED",
        )
        raise ConfluenceAuthorizationError("SCENARIO_AUTHOR_REQUIRED")
    if document_set.organization_id != organization.id:
        _audit_source_denial(
            actor_id,
            organization.id,
            "CONFLUENCE_DOCUMENT_SET_TENANT_MISMATCH",
        )
        raise ConfluenceServiceError("CONFLUENCE_DOCUMENT_SET_TENANT_MISMATCH")
    if document_set.status != DocumentSetStatus.ACTIVE:
        _audit_source_denial(actor_id, organization.id, "CONFLUENCE_DOCUMENT_SET_DISABLED")
        raise ConfluenceServiceError("CONFLUENCE_DOCUMENT_SET_DISABLED")
    if confluence_profile.status != ConfluenceProfileStatus.ACTIVE:
        _audit_source_denial(actor_id, organization.id, "CONFLUENCE_PROFILE_DISABLED")
        raise ConfluenceServiceError("CONFLUENCE_PROFILE_DISABLED")
    with transaction.atomic():
        set_tenant_context(organization.id)
        granted = TenantConfluenceProfileGrant.objects.filter(
            organization=organization,
            document_set=document_set,
            confluence_profile=confluence_profile,
        ).exists()
    if not granted:
        _audit_source_denial(actor_id, organization.id, "CONFLUENCE_PROFILE_NOT_GRANTED")
        raise ConfluenceAuthorizationError("CONFLUENCE_PROFILE_NOT_GRANTED")
    normalized = normalize_confluence_source_config(connector_config)
    source = Source(
        organization=organization,
        slug=slug,
        name=name,
        connector_type=ConnectorType.CONFLUENCE_DC,
        connector_config=normalized,
        confluence_profile=confluence_profile,
        document_set=document_set,
        status=SourceStatus.ACTIVE,
    )
    source.full_clean(validate_unique=False, validate_constraints=False)
    with transaction.atomic():
        try:
            source.save()
        except IntegrityError as exc:
            raise ConfluenceServiceError("CONFLUENCE_SOURCE_CONFLICT") from exc
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="confluence_source.create",
            outcome=Outcome.SUCCESS,
            organization_id=organization.id,
            resource_type="source",
            resource_id=str(source.pk),
            after={
                "connector_type": ConnectorType.CONFLUENCE_DC,
                "document_set_id": document_set.pk,
                "profile_id": str(confluence_profile.public_id),
                "root_count": len(normalized["root_page_ids"]),
                "excluded_count": len(normalized["excluded_page_ids"]),
            },
        )
    return source


def create_confluence_sync_run(
    *, actor: UserLike, source: Source, max_attempts: int = 3, request_id: str = ""
) -> ConfluenceSyncRun:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if source.connector_type != ConnectorType.CONFLUENCE_DC or not source.confluence_profile_id:
        raise ConfluenceServiceError("CONFLUENCE_SOURCE_REQUIRED")
    if not can_author_scenarios(actor, source.organization_id):
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="confluence_sync.queue",
            outcome=Outcome.DENY,
            organization_id=source.organization_id,
            resource_type="source",
            resource_id=str(source.pk),
            reason="SCENARIO_AUTHOR_REQUIRED",
            request_id=request_id,
        )
        raise ConfluenceAuthorizationError("SCENARIO_AUTHOR_REQUIRED")
    if not source.is_active:
        raise ConfluenceServiceError("SOURCE_DISABLED")
    run = ConfluenceSyncRun(
        organization_id=source.organization_id,
        source=source,
        confluence_profile_id=source.confluence_profile_id,
        max_attempts=max_attempts,
    )
    with transaction.atomic():
        set_tenant_context(source.organization_id)
        run.full_clean()
        run.save()
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="confluence_sync.queue",
            outcome=Outcome.SUCCESS,
            organization_id=source.organization_id,
            resource_type="confluence_sync_run",
            resource_id=str(run.pk),
            request_id=request_id,
        )
    return run


def _audit_profile_denial(
    actor_id: str,
    action: str,
    reason: str,
    *,
    organization_id: int | None = None,
    resource_id: str = "",
) -> None:
    record_event(
        actor_type=ActorType.USER,
        actor_id=actor_id,
        action=action,
        outcome=Outcome.DENY,
        organization_id=organization_id,
        resource_type="confluence_profile",
        resource_id=resource_id,
        reason=reason,
    )


def _audit_source_denial(actor_id: str, organization_id: int, reason: str) -> None:
    record_event(
        actor_type=ActorType.USER,
        actor_id=actor_id,
        action="confluence_source.create",
        outcome=Outcome.DENY,
        organization_id=organization_id,
        resource_type="source",
        reason=reason,
    )
