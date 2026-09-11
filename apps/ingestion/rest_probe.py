"""One authorized, audited REST first-page check outside database transactions."""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent, Outcome
from apps.documents.models import DocumentSet
from apps.ingestion.connections import ConnectionError, verify_connection
from apps.ingestion.models import Connection, RestPullProfile, TenantRestPullProfileGrant
from apps.ingestion.rest import GovernedRestClient, RestPullError, preview_rest_response
from apps.ingestion.rest_schema import RestContractError, validate_contract, validate_source_inputs
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError, _audit
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import UserLike, can_manage_documents
from apps.tools.deadline_dns import bounded_resolver


@dataclass(frozen=True)
class RestProbeResult:
    mapped_count: int
    fetched_bytes: int


def _authorized_profile(
    actor: UserLike,
    organization_id: int,
    document_set_id: int,
    profile_id: UUID,
) -> RestPullProfile:
    with transaction.atomic():
        set_tenant_context(organization_id)
        docset = (
            DocumentSet.objects.select_related("organization")
            .filter(pk=document_set_id, organization_id=organization_id, status="active")
            .first()
        )
        if (
            docset is None
            or not docset.organization.is_active
            or not can_manage_documents(actor, organization_id, document_set=docset)
        ):
            raise RestAuthorizationError("DOCUMENT_SET_MANAGER_REQUIRED")
        granted = TenantRestPullProfileGrant.objects.filter(
            organization_id=organization_id,
            document_set=docset,
            rest_profile__public_id=profile_id,
            rest_profile__status="active",
        ).exists()
        identity = Connection.objects.filter(rest_profile__public_id=profile_id).first()
        if not granted or identity is None:
            raise RestAuthorizationError("REST_PROFILE_NOT_GRANTED")
        profile = verify_connection(identity)
        if not isinstance(profile, RestPullProfile) or profile.status != "active":
            raise RestAuthorizationError("REST_PROFILE_NOT_GRANTED")
        return profile


def probe_rest_connection(
    *,
    actor: UserLike,
    organization_id: int,
    document_set_id: int,
    profile_id: UUID,
    definition: dict[str, Any],
    inputs: dict[str, Any],
    request_id: str = "",
) -> RestProbeResult:
    if connection.in_atomic_block:
        raise RestServiceError("REST_PROBE_REQUIRES_COMMITTED_BOUNDARY")
    definition = validate_contract(definition)
    inputs = validate_source_inputs(definition, inputs)
    actor_id = str(getattr(actor, "pk", "anonymous"))

    def audit(outcome, reason="", after=None, *, started=False):
        with transaction.atomic():
            set_tenant_context(organization_id)
            _audit(
                "rest_source.connection_test_started" if started else "rest_source.connection_test",
                actor_id,
                outcome,
                organization_id=organization_id,
                resource_id=str(profile_id),
                reason=reason,
                request_id=request_id,
                after=after,
            )

    def authorize() -> None:
        _authorized_profile(actor, organization_id, document_set_id, profile_id)

    try:
        profile = _authorized_profile(actor, organization_id, document_set_id, profile_id)
        if definition["request"]["method"] != profile.method:
            raise RestServiceError("REST_PROFILE_METHOD_MISMATCH")
        if profile.method != "GET" and definition["response"].get("detail") is not None:
            raise RestServiceError("REST_DETAIL_REQUIRES_GET_PROFILE")
        with transaction.atomic():
            set_tenant_context(organization_id)
            Organization.objects.select_for_update(no_key=True).get(pk=organization_id)
            now = timezone.now()
            recent = AuditEvent.objects.filter(
                organization_id=organization_id,
                action="rest_source.connection_test_started",
                occurred_at__gte=now - timedelta(minutes=1),
            )
            if (
                recent.filter(
                    actor_id=actor_id, occurred_at__gte=now - timedelta(seconds=10)
                ).exists()
                or len(list(recent.values_list("pk", flat=True)[:20])) >= 20
            ):
                raise RestServiceError("REST_PROBE_RATE_LIMITED")
            audit(Outcome.ALLOW, after={"document_set_id": document_set_id}, started=True)
        # Narrow a detached transport copy; the immutable catalog row is never updated.
        bounded = copy.copy(profile)
        bounded.timeout_seconds = min(profile.timeout_seconds, 10)
        bounded.max_response_bytes = min(profile.max_response_bytes, 100000)
        bounded.max_total_bytes = min(profile.max_total_bytes, 100000)
        bounded.max_requests = 1
        bounded.max_retries = 0
        deadline = time.monotonic() + bounded.timeout_seconds
        client = GovernedRestClient(
            deadline=deadline, before_request=authorize, resolver=bounded_resolver(deadline)
        )
        payload = client.read_first_page(bounded, definition, inputs=inputs)
        count = len(preview_rest_response(definition, payload, max_items=1000))
        authorize()
        result = RestProbeResult(mapped_count=count, fetched_bytes=client.fetched_bytes)
        audit(
            Outcome.SUCCESS,
            after={
                "document_set_id": document_set_id,
                "mapped_count": count,
                "fetched_bytes": client.fetched_bytes,
            },
        )
        return result
    except (
        RestAuthorizationError,
        RestServiceError,
        RestPullError,
        RestContractError,
        ConnectionError,
    ) as exc:
        audit(
            Outcome.DENY if isinstance(exc, RestAuthorizationError) else Outcome.FAILURE,
            getattr(exc, "code", "REST_PROBE_DENIED"),
        )
        raise
