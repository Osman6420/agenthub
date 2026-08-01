"""Platform-admin services for the embedding-profile catalog and per-tenant grants.

Registration and grants are platform-operator actions (ADR-0002: tenants cannot create free
endpoints/profiles), audited without endpoint/secret content. Mirrors
``apps.orchestration.services.register_model_profile``.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.ingestion.embedding_schema import validate_embedding_profile_fields
from apps.ingestion.models import (
    EmbeddingProfile,
    EmbeddingProfileStatus,
    TenantEmbeddingProfileGrant,
)
from apps.tenancy.models import Organization
from apps.tenancy.services import UserLike, is_platform_admin


class EmbeddingProfileAuthorizationError(PermissionError):
    pass


def register_embedding_profile(*, actor: UserLike, **fields: Any) -> EmbeddingProfile:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="embedding_profile.create",
            outcome=Outcome.DENY,
            resource_type="embedding_profile",
            reason="PLATFORM_ADMIN_REQUIRED",
        )
        raise EmbeddingProfileAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    validate_embedding_profile_fields(**fields)
    with transaction.atomic():
        profile = EmbeddingProfile.objects.create(created_by=actor_id, **fields)
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="embedding_profile.create",
            outcome=Outcome.SUCCESS,
            resource_type="embedding_profile",
            resource_id=str(profile.public_id),
            after={
                "logical_id": profile.logical_id,
                "revision": profile.revision,
                "provider": profile.provider,
                "dimensions": profile.dimensions,
                "index_type": profile.index_type,
                "status": profile.status,
            },
        )
    return profile


def grant_embedding_profile(
    *, actor: UserLike, organization: Organization, embedding_profile: EmbeddingProfile
) -> TenantEmbeddingProfileGrant:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="embedding_profile.grant",
            outcome=Outcome.DENY,
            organization_id=organization.id,
            resource_type="embedding_profile",
            resource_id=str(embedding_profile.public_id),
            reason="PLATFORM_ADMIN_REQUIRED",
        )
        raise EmbeddingProfileAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    with transaction.atomic():
        locked = EmbeddingProfile.objects.select_for_update().get(pk=embedding_profile.pk)
        if locked.status != EmbeddingProfileStatus.ACTIVE:
            record_event(
                actor_type=ActorType.USER,
                actor_id=actor_id,
                action="embedding_profile.grant",
                outcome=Outcome.DENY,
                organization_id=organization.id,
                resource_type="embedding_profile",
                resource_id=str(locked.public_id),
                reason="EMBEDDING_PROFILE_DISABLED",
            )
            raise EmbeddingProfileAuthorizationError("EMBEDDING_PROFILE_DISABLED")
        grant, _created = TenantEmbeddingProfileGrant.objects.get_or_create(
            organization=organization,
            embedding_profile=locked,
            defaults={"created_by": actor_id},
        )
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="embedding_profile.grant",
            outcome=Outcome.SUCCESS,
            organization_id=organization.id,
            resource_type="embedding_profile",
            resource_id=str(locked.public_id),
        )
    return grant


@transaction.atomic
def disable_embedding_profile(
    *, actor: UserLike, embedding_profile: EmbeddingProfile
) -> EmbeddingProfile:
    """Disable one immutable embedding-profile revision while retaining grants and lineage."""

    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="embedding_profile.disable",
            outcome=Outcome.DENY,
            resource_type="embedding_profile",
            resource_id=str(embedding_profile.public_id),
            reason="PLATFORM_ADMIN_REQUIRED",
        )
        raise EmbeddingProfileAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    locked = EmbeddingProfile.objects.select_for_update().get(pk=embedding_profile.pk)
    if locked.status != EmbeddingProfileStatus.DISABLED:
        locked.status = EmbeddingProfileStatus.DISABLED
        locked.save(update_fields=["status"])
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="embedding_profile.disable",
            outcome=Outcome.SUCCESS,
            resource_type="embedding_profile",
            resource_id=str(locked.public_id),
        )
    return locked
