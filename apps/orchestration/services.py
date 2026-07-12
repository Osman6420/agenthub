from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.orchestration.models import ModelProfile
from apps.orchestration.profile_schema import validate_profile_fields
from apps.tenancy.services import UserLike, is_platform_admin


class ModelProfileAuthorizationError(PermissionError):
    pass


def register_model_profile(*, actor: UserLike, **fields: Any) -> ModelProfile:
    actor_id = str(getattr(actor, "pk", "anonymous"))
    if not is_platform_admin(actor):
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="model_profile.create",
            outcome=Outcome.DENY,
            resource_type="model_profile",
            reason="PLATFORM_ADMIN_REQUIRED",
        )
        raise ModelProfileAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    validate_profile_fields(**fields)
    with transaction.atomic():
        profile = ModelProfile.objects.create(created_by=actor_id, **fields)
        record_event(
            actor_type=ActorType.USER,
            actor_id=actor_id,
            action="model_profile.create",
            outcome=Outcome.SUCCESS,
            resource_type="model_profile",
            resource_id=str(profile.public_id),
            after={
                "logical_id": profile.logical_id,
                "revision": profile.revision,
                "provider": profile.provider,
                "status": profile.status,
            },
        )
    return profile
