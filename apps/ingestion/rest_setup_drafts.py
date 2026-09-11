"""Bounded private REST checkpoints, independent of browser-session lifetime."""

from __future__ import annotations

import copy
import json
import re
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import Outcome
from apps.documents.models import DocumentSet, DocumentSetStatus
from apps.ingestion.models import RestSetupDraft, Source
from apps.ingestion.rest_schema import RestContractError, validate_contract, validate_source_inputs
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError, _audit
from apps.ingestion.rest_setup_schedule import validate_setup_schedule
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import UserLike, can_manage_documents

MAX_SAVED_DRAFTS = 5
MAX_PAYLOAD_BYTES = 160000
PAYLOAD_KEYS = {
    "name",
    "step",
    "mode",
    "profile",
    "definition",
    "inputs",
    "schedule",
    "base_source",
    "base_token",
}


def validate_draft_payload(payload: Any) -> dict[str, Any]:
    """Keep only setup data; no actor/scope/session authority can be embedded."""
    if not isinstance(payload, dict) or set(payload) - PAYLOAD_KEYS:
        raise RestServiceError("REST_SETUP_DRAFT_INVALID")
    try:
        if len(json.dumps(payload, allow_nan=False).encode()) > MAX_PAYLOAD_BYTES:
            raise RestServiceError("REST_SETUP_STATE_LIMIT")
        pending = [(payload, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 16:
                raise RestServiceError("REST_SETUP_STATE_LIMIT")
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
    except RestServiceError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise RestServiceError("REST_SETUP_DRAFT_INVALID") from exc
    if (
        not isinstance(payload.get("name"), str)
        or not 1 <= len(payload["name"].strip()) <= 200
        or type(payload.get("step")) is not int
        or payload["step"] not in {1, 2, 3, 4}
        or payload.get("mode") not in {"visual", "advanced"}
    ):
        raise RestServiceError("REST_SETUP_DRAFT_INVALID")
    if "profile" in payload:
        try:
            UUID(payload["profile"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise RestServiceError("REST_SETUP_DRAFT_INVALID") from exc
    elif payload["step"] > 1:
        raise RestServiceError("REST_SETUP_DRAFT_INVALID")
    if "definition" in payload:
        validate_contract(payload["definition"])
    elif payload["step"] > 2 or "inputs" in payload:
        raise RestServiceError("REST_SETUP_DRAFT_INVALID")
    if "inputs" in payload:
        validate_source_inputs(payload["definition"], payload["inputs"])
    elif payload["step"] == 4:
        raise RestServiceError("REST_SETUP_DRAFT_INVALID")
    if payload.get("base_source"):
        from apps.ingestion.revision_schedule import validate_revision_schedule

        validate_revision_schedule(payload.get("schedule"))
    else:
        validate_setup_schedule(payload.get("schedule"))
    if "base_source" in payload or "base_token" in payload:
        if (
            type(payload.get("base_source")) is not int
            or payload["base_source"] < 1
            or not isinstance(payload.get("base_token"), str)
            or re.fullmatch(r"[0-9a-f]{64}", payload["base_token"]) is None
        ):
            raise RestServiceError("REST_SETUP_DRAFT_INVALID")
    return copy.deepcopy(payload)


def _authorize(actor: UserLike, document_set: DocumentSet) -> DocumentSet:
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
    return current


def lock_setup_draft(
    *, actor: UserLike, document_set: DocumentSet, intent: UUID, expected_revision: int | None
) -> RestSetupDraft | None:
    """Caller holds the organization lock. A checkpoint cannot be overwritten by a stale tab."""
    draft = RestSetupDraft.objects.select_for_update().filter(public_id=intent).first()
    if draft is None:
        if expected_revision not in {None, 0}:
            raise RestServiceError("REST_SETUP_DRAFT_CONFLICT")
        return None
    if (
        draft.organization_id != document_set.organization_id
        or draft.document_set_id != document_set.pk
        or draft.owner_id != getattr(actor, "pk", None)
    ):
        raise RestAuthorizationError("REST_SETUP_DRAFT_OWNER_REQUIRED")
    if draft.expires_at <= timezone.now():
        raise RestServiceError("REST_SETUP_DRAFT_EXPIRED")
    if draft.completed_source_id is not None or draft.revision != expected_revision:
        raise RestServiceError("REST_SETUP_DRAFT_CONFLICT")
    return draft


def save_setup_draft(
    *,
    actor: UserLike,
    document_set: DocumentSet,
    intent: UUID,
    payload: dict[str, Any],
    expected_revision: int = 0,
) -> RestSetupDraft:
    try:
        return _save_setup_draft(
            actor=actor,
            document_set=document_set,
            intent=intent,
            payload=payload,
            expected_revision=expected_revision,
        )
    except (RestAuthorizationError, RestServiceError, RestContractError) as exc:
        _audit_denial("rest_setup_draft.save", actor, document_set, exc)
        raise


def _audit_denial(action, actor, document_set, exc):
    with transaction.atomic():
        set_tenant_context(document_set.organization_id)
        _audit(
            action,
            str(getattr(actor, "pk", "anonymous")),
            Outcome.DENY,
            organization_id=document_set.organization_id,
            resource_id=str(document_set.public_id),
            reason=getattr(exc, "code", "REST_SETUP_DRAFT_DENIED"),
        )


@transaction.atomic
def _save_setup_draft(
    *,
    actor: UserLike,
    document_set: DocumentSet,
    intent: UUID,
    payload: dict[str, Any],
    expected_revision: int,
) -> RestSetupDraft:
    current = _authorize(actor, document_set)
    owner_id = getattr(actor, "pk", None)
    if owner_id is None:
        raise RestAuthorizationError("REST_SETUP_DRAFT_OWNER_REQUIRED")
    normalized = validate_draft_payload(payload)
    if (
        "base_source" in normalized
        and not Source.objects.filter(
            pk=normalized["base_source"], document_set=current, connector_type="generic_rest"
        ).exists()
    ):
        raise RestServiceError("SOURCE_REVISION_NOT_FOUND")
    if not isinstance(intent, UUID) or type(expected_revision) is not int or expected_revision < 0:
        raise RestServiceError("REST_SETUP_DRAFT_INVALID")
    draft = lock_setup_draft(
        actor=actor, document_set=current, intent=intent, expected_revision=expected_revision
    )
    if draft is None:
        if (
            RestSetupDraft.objects.filter(
                organization_id=current.organization_id,
                owner_id=getattr(actor, "pk", None),
                completed_source__isnull=True,
                expires_at__gt=timezone.now(),
            ).count()
            >= MAX_SAVED_DRAFTS
        ):
            raise RestServiceError("REST_SETUP_DRAFT_LIMIT")
        draft = RestSetupDraft(
            public_id=intent,
            organization_id=current.organization_id,
            document_set=current,
            owner_id=owner_id,
            expires_at=timezone.now() + timedelta(days=30),
        )
    else:
        draft.revision += 1
    draft.name = normalized["name"]
    draft.payload = normalized
    draft.save()
    _audit(
        "rest_setup_draft.save",
        str(getattr(actor, "pk", "anonymous")),
        Outcome.ALLOW,
        organization_id=current.organization_id,
        resource_id=str(intent),
    )
    return draft


def load_setup_draft(*, actor: UserLike, document_set: DocumentSet, intent: UUID) -> RestSetupDraft:
    try:
        return _load_setup_draft(actor=actor, document_set=document_set, intent=intent)
    except (RestAuthorizationError, RestServiceError) as exc:
        _audit_denial("rest_setup_draft.resume", actor, document_set, exc)
        raise


@transaction.atomic
def _load_setup_draft(
    *, actor: UserLike, document_set: DocumentSet, intent: UUID
) -> RestSetupDraft:
    current = _authorize(actor, document_set)
    draft = RestSetupDraft.objects.filter(
        public_id=intent,
        organization_id=current.organization_id,
        document_set=current,
        owner_id=getattr(actor, "pk", None),
        expires_at__gt=timezone.now(),
    ).first()
    if draft is None:
        raise RestServiceError("REST_SETUP_DRAFT_UNAVAILABLE")
    _audit(
        "rest_setup_draft.resume",
        str(getattr(actor, "pk", "anonymous")),
        Outcome.ALLOW,
        organization_id=current.organization_id,
        resource_id=str(intent),
    )
    return draft


def complete_setup_draft(draft: RestSetupDraft | None, source: Source, actor: UserLike) -> None:
    """Complete inside the source transaction, dropping the duplicate configuration."""
    if draft is None:
        return
    draft.payload = {}
    draft.completed_source = source
    draft.revision += 1
    draft.save(update_fields=["payload", "completed_source", "revision", "updated_at"])
    _audit(
        "rest_setup_draft.complete",
        str(getattr(actor, "pk", "anonymous")),
        Outcome.ALLOW,
        organization_id=draft.organization_id,
        resource_id=str(draft.public_id),
    )
