from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.ingestion.models import OcrProfile, TenantOcrProfileGrant
from apps.ingestion.ocr_schema import validate_ocr_profile_fields
from apps.tenancy.models import Organization
from apps.tenancy.services import UserLike, is_platform_admin


class OcrProfileAuthorizationError(PermissionError):
    pass


def register_ocr_profile(*, actor: UserLike, **fields: Any) -> OcrProfile:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="ocr_profile.create",
            outcome=Outcome.DENY,
            resource_type="ocr_profile",
            reason="PLATFORM_ADMIN_REQUIRED",
        )
        raise OcrProfileAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    validate_ocr_profile_fields(**fields)
    with transaction.atomic():
        profile = OcrProfile.objects.create(created_by=actor_id, **fields)
        from apps.ingestion.connections import materialize_connection

        materialize_connection(profile=profile, actor=actor_id)
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="ocr_profile.create",
            outcome=Outcome.SUCCESS,
            resource_type="ocr_profile",
            resource_id=str(profile.public_id),
            after={
                "logical_id": profile.logical_id,
                "revision": profile.revision,
                "provider": profile.provider,
                "status": profile.status,
            },
        )
    return profile


def grant_ocr_profile(
    *, actor: UserLike, organization: Organization, ocr_profile: OcrProfile
) -> TenantOcrProfileGrant:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="ocr_profile.grant",
            outcome=Outcome.DENY,
            organization_id=organization.id,
            resource_type="ocr_profile",
            resource_id=str(ocr_profile.public_id),
            reason="PLATFORM_ADMIN_REQUIRED",
        )
        raise OcrProfileAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    with transaction.atomic():
        grant, _ = TenantOcrProfileGrant.objects.get_or_create(
            organization=organization,
            ocr_profile=ocr_profile,
            defaults={"created_by": actor_id},
        )
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="ocr_profile.grant",
            outcome=Outcome.SUCCESS,
            organization_id=organization.id,
            resource_type="ocr_profile",
            resource_id=str(ocr_profile.public_id),
        )
    return grant
