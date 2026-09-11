"""Atomic REST setup on the existing catalog, contract and source authorities."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import Outcome
from apps.documents.models import DocumentSet, DocumentSetStatus
from apps.ingestion.models import RestPullProfile, Source, TenantRestPullProfileGrant
from apps.ingestion.rest_schema import (
    RestContractError,
    canonical_contract_json,
    validate_contract,
    validate_source_inputs,
)
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    _audit,
    configure_sync_schedule,
    create_rest_contract,
    create_rest_source,
)
from apps.ingestion.rest_setup_drafts import complete_setup_draft, lock_setup_draft
from apps.ingestion.rest_setup_schedule import setup_preparation_policy, validate_setup_schedule
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import UserLike, can_manage_documents


def create_rest_setup(
    *,
    actor: UserLike,
    document_set: DocumentSet,
    profile_id: UUID,
    intent: UUID,
    name: str,
    definition: dict[str, Any],
    inputs: dict[str, Any],
    schedule: dict[str, Any] | None = None,
    draft_revision: int | None = None,
) -> Source:
    try:
        return _create_rest_setup(
            actor=actor,
            document_set=document_set,
            profile_id=profile_id,
            intent=intent,
            name=name,
            definition=definition,
            inputs=inputs,
            schedule=schedule,
            draft_revision=draft_revision,
        )
    except (RestAuthorizationError, RestServiceError, RestContractError) as exc:
        with transaction.atomic():
            set_tenant_context(document_set.organization_id)
            _audit(
                "rest_source.setup",
                str(getattr(actor, "pk", "anonymous")),
                Outcome.DENY,
                organization_id=document_set.organization_id,
                resource_id=str(document_set.public_id),
                reason=getattr(exc, "code", "REST_SETUP_DENIED"),
            )
        raise


def _create_rest_setup(
    *,
    actor: UserLike,
    document_set: DocumentSet,
    profile_id: UUID,
    intent: UUID,
    name: str,
    definition: dict[str, Any],
    inputs: dict[str, Any],
    schedule: dict[str, Any] | None,
    draft_revision: int | None,
) -> Source:
    """Persist one exact intent; neither dispatch nor remote reads occur here.

    The organization lock serializes setup and access transitions. Replays
    reauthorize and match every configuration field before returning the source.
    Profile/grant checks are live reads; job admission independently rechecks them.
    """
    definition = validate_contract(definition)
    normalized = validate_source_inputs(definition, inputs)
    validate_setup_schedule(schedule)
    if (
        schedule is not None
        and "preparation" in schedule
        and not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False)
    ):
        raise RestServiceError("REST_SETUP_PREPARATION_UNAVAILABLE")
    if not isinstance(intent, UUID) or not isinstance(name, str) or not 1 <= len(name) <= 200:
        raise RestServiceError("REST_SETUP_INVALID")
    checksum = hashlib.sha256(canonical_contract_json(definition).encode()).hexdigest()
    slug = f"rest-{intent.hex}"
    with transaction.atomic():
        set_tenant_context(document_set.organization_id)
        organization = Organization.objects.select_for_update(no_key=True).get(
            pk=document_set.organization_id
        )
        current = DocumentSet.objects.get(pk=document_set.pk, organization=organization)
        if not organization.is_active or not can_manage_documents(
            actor, organization.pk, document_set=current
        ):
            raise RestAuthorizationError("DOCUMENT_SET_MANAGER_REQUIRED")
        if current.status != DocumentSetStatus.ACTIVE:
            raise RestServiceError("REST_DOCUMENT_SET_DISABLED")
        draft = lock_setup_draft(
            actor=actor, document_set=current, intent=intent, expected_revision=draft_revision
        )
        profile = RestPullProfile.objects.filter(public_id=profile_id, status="active").first()
        if (
            profile is None
            or not TenantRestPullProfileGrant.objects.filter(
                organization=organization, document_set=current, rest_profile=profile
            ).exists()
        ):
            raise RestAuthorizationError("REST_PROFILE_NOT_GRANTED")
        if definition["request"]["method"] != profile.method:
            raise RestServiceError("REST_PROFILE_METHOD_MISMATCH")
        policy = (
            setup_preparation_policy(current, expected=schedule["preparation"], lock=True)
            if schedule is not None and "preparation" in schedule
            else None
        )
        existing = (
            Source.objects.select_related("rest_contract")
            .filter(organization=organization, slug=slug)
            .first()
        )
        if existing:
            previous_schedule = getattr(existing, "sync_schedule", None)
            same_schedule = (
                previous_schedule is None
                if schedule is None
                else previous_schedule is not None
                and previous_schedule.enabled
                and previous_schedule.automation_mode == ("stage_only" if policy else "draft_only")
                and previous_schedule.interval_seconds == schedule["interval_seconds"]
                and previous_schedule.embedding_profile_id
                == (policy.embedding_profile_id if policy else None)
                and previous_schedule.ocr_profile_id == (policy.ocr_profile_id if policy else None)
                and not previous_schedule.promotion_targets.exists()
            )
            if (
                existing.connector_type != "generic_rest"
                or existing.document_set_id != current.pk
                or existing.rest_profile_id != profile.pk
                or existing.name != name
                or existing.connector_config != {"inputs": normalized}
                or existing.rest_contract is None
                or existing.rest_contract.checksum != checksum
                or not same_schedule
            ):
                raise RestServiceError("REST_SETUP_INTENT_CONFLICT")
            complete_setup_draft(draft, existing, actor)
            return existing
        contract = create_rest_contract(
            actor=actor,
            organization=organization,
            document_set=current,
            logical_id=slug,
            revision=1,
            definition=definition,
        )
        source = create_rest_source(
            actor=actor,
            organization=organization,
            document_set=current,
            rest_profile=profile,
            rest_contract=contract,
            slug=slug,
            name=name,
            inputs=normalized,
        )
        if schedule is not None:
            configure_sync_schedule(
                actor=actor,
                source=source,
                enabled=True,
                interval_seconds=schedule["interval_seconds"],
                next_run_at=timezone.now() + timedelta(seconds=schedule["interval_seconds"]),
                automation_mode="stage_only" if policy else "draft_only",
                embedding_profile=policy.embedding_profile if policy else None,
                ocr_profile=policy.ocr_profile if policy else None,
            )
        complete_setup_draft(draft, source, actor)
        return source
