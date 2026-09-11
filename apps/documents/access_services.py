"""Audited scenario-to-document-set request and live grant lifecycle."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.documents.models import (
    GrantPermission,
    ScenarioDocumentSetAccessRequest,
    ScenarioDocumentSetGrant,
    ScenarioDocumentSetGrantStatus,
    ScenarioDocumentSetRequestStatus,
)
from apps.identity.authorization import AuthoritySource, Capability, authorize
from apps.tenancy.models import Organization


class ScenarioDocumentSetAccessError(PermissionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _audit(
    *,
    actor: Any,
    action: str,
    outcome: str,
    organization_id: int,
    resource_type: str,
    resource_id: str,
    reason: str,
    request_id: str,
    trace_id: str,
) -> None:
    record_event(
        actor_type="user",
        actor_id=actor.get_username(),
        action=action,
        outcome=outcome,
        organization_id=organization_id,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        request_id=request_id,
        trace_id=trace_id,
    )


def request_scenario_document_set_access(
    *,
    scenario: Any,
    document_set: Any,
    purpose: str,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioDocumentSetAccessRequest:
    action = "scenario_document_set_access.request"
    safe_target = f"{scenario.public_id}:{document_set.public_id}"
    normalized_purpose = purpose.strip()
    try:
        if not normalized_purpose or len(normalized_purpose) > 500:
            raise ScenarioDocumentSetAccessError("INVALID_REQUEST_PURPOSE")
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=scenario.organization_id)
            decision = authorize(
                user=actor,
                capability=Capability.SCENARIO_EDIT,
                organization=organization,
                project=scenario.project,
                scenario=scenario,
                document_set=document_set,
            )
            if not decision.allowed or decision.source not in {
                AuthoritySource.PROJECT_RESPONSIBILITY,
                AuthoritySource.SCENARIO_RESPONSIBILITY,
            }:
                raise ScenarioDocumentSetAccessError("SCENARIO_ACCESS_REQUEST_DENIED")
            access_request = ScenarioDocumentSetAccessRequest.objects.create(
                organization=organization,
                scenario=scenario,
                document_set=document_set,
                requested_by=actor,
                purpose=normalized_purpose,
            )
            _audit(
                actor=actor,
                action=action,
                outcome="success",
                organization_id=organization.pk,
                resource_type="scenario_document_set_access_request",
                resource_id=str(access_request.pk),
                reason="ACCESS_REQUESTED",
                request_id=request_id,
                trace_id=trace_id,
            )
            return access_request
    except (ScenarioDocumentSetAccessError, IntegrityError) as exc:
        reason = (
            exc.code
            if isinstance(exc, ScenarioDocumentSetAccessError)
            else "PENDING_REQUEST_ALREADY_EXISTS"
        )
        _audit(
            actor=actor,
            action=action,
            outcome="deny",
            organization_id=scenario.organization_id,
            resource_type="scenario_document_set",
            resource_id=safe_target,
            reason=reason,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise ScenarioDocumentSetAccessError(reason) from exc


def approve_scenario_document_set_access(
    *,
    access_request: ScenarioDocumentSetAccessRequest,
    actor: Any,
    decision_reason: str = "",
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioDocumentSetGrant:
    action = "scenario_document_set_access.approve"
    try:
        with transaction.atomic():
            locked = (
                ScenarioDocumentSetAccessRequest.objects.select_for_update()
                .select_related("organization", "scenario", "document_set")
                .get(pk=access_request.pk)
            )
            decision = authorize(
                user=actor,
                capability=Capability.DOCUMENT_SET_RETRIEVE_GRANT,
                organization=locked.organization,
                scenario=locked.scenario,
                document_set=locked.document_set,
            )
            if (
                not decision.allowed
                or decision.source != AuthoritySource.DOCUMENT_SET_RESPONSIBILITY
            ):
                raise ScenarioDocumentSetAccessError("DOCUMENT_SET_MANAGER_REQUIRED")
            if locked.status != ScenarioDocumentSetRequestStatus.PENDING:
                raise ScenarioDocumentSetAccessError("REQUEST_NOT_PENDING")
            now = timezone.now()
            locked.status = ScenarioDocumentSetRequestStatus.APPROVED
            locked.decided_by = actor
            locked.decided_at = now
            locked.decision_reason = decision_reason[:500]
            locked.save()
            grant, _created = ScenarioDocumentSetGrant.objects.update_or_create(
                scenario=locked.scenario,
                document_set=locked.document_set,
                permission=GrantPermission.RETRIEVE,
                defaults={
                    "organization": locked.organization,
                    "status": ScenarioDocumentSetGrantStatus.GRANTED,
                    "granted_by": actor,
                    "granted_at": now,
                    "revoked_by": None,
                    "revoked_at": None,
                },
            )
            _audit(
                actor=actor,
                action=action,
                outcome="success",
                organization_id=locked.organization_id,
                resource_type="scenario_document_set_grant",
                resource_id=str(grant.pk),
                reason="ACCESS_GRANTED",
                request_id=request_id,
                trace_id=trace_id,
            )
            return grant
    except ScenarioDocumentSetAccessError as exc:
        _audit(
            actor=actor,
            action=action,
            outcome="deny",
            organization_id=access_request.organization_id,
            resource_type="scenario_document_set_access_request",
            resource_id=str(access_request.pk),
            reason=exc.code,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise


def reject_scenario_document_set_access(
    *,
    access_request: ScenarioDocumentSetAccessRequest,
    actor: Any,
    decision_reason: str,
    request_id: str = "",
    trace_id: str = "",
) -> None:
    action = "scenario_document_set_access.reject"
    try:
        with transaction.atomic():
            locked = (
                ScenarioDocumentSetAccessRequest.objects.select_for_update()
                .select_related("organization", "scenario", "document_set")
                .get(pk=access_request.pk)
            )
            decision = authorize(
                user=actor,
                capability=Capability.DOCUMENT_SET_RETRIEVE_GRANT,
                organization=locked.organization,
                scenario=locked.scenario,
                document_set=locked.document_set,
            )
            if (
                not decision.allowed
                or decision.source != AuthoritySource.DOCUMENT_SET_RESPONSIBILITY
            ):
                raise ScenarioDocumentSetAccessError("DOCUMENT_SET_MANAGER_REQUIRED")
            if locked.status != ScenarioDocumentSetRequestStatus.PENDING:
                raise ScenarioDocumentSetAccessError("REQUEST_NOT_PENDING")
            locked.status = ScenarioDocumentSetRequestStatus.REJECTED
            locked.decided_by = actor
            locked.decided_at = timezone.now()
            locked.decision_reason = decision_reason[:500]
            locked.save()
            _audit(
                actor=actor,
                action=action,
                outcome="success",
                organization_id=locked.organization_id,
                resource_type="scenario_document_set_access_request",
                resource_id=str(locked.pk),
                reason="ACCESS_REJECTED",
                request_id=request_id,
                trace_id=trace_id,
            )
    except ScenarioDocumentSetAccessError as exc:
        _audit(
            actor=actor,
            action=action,
            outcome="deny",
            organization_id=access_request.organization_id,
            resource_type="scenario_document_set_access_request",
            resource_id=str(access_request.pk),
            reason=exc.code,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise


def revoke_scenario_document_set_grant(
    *,
    grant: ScenarioDocumentSetGrant,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> None:
    initial_decision = authorize(
        user=actor,
        capability=Capability.DOCUMENT_SET_RETRIEVE_GRANT,
        organization=grant.organization,
        scenario=grant.scenario,
        document_set=grant.document_set,
    )
    allowed_sources = {
        AuthoritySource.DOCUMENT_SET_RESPONSIBILITY,
        AuthoritySource.SUPERADMIN_RECOVERY,
    }
    if not initial_decision.allowed or initial_decision.source not in allowed_sources:
        _audit(
            actor=actor,
            action="scenario_document_set_access.revoke",
            outcome="deny",
            organization_id=grant.organization_id,
            resource_type="scenario_document_set_grant",
            resource_id=str(grant.pk),
            reason="DOCUMENT_SET_MANAGER_REQUIRED",
            request_id=request_id,
            trace_id=trace_id,
        )
        raise ScenarioDocumentSetAccessError("DOCUMENT_SET_MANAGER_REQUIRED")
    with transaction.atomic():
        locked = (
            ScenarioDocumentSetGrant.objects.select_for_update()
            .select_related("organization", "scenario", "document_set")
            .get(pk=grant.pk)
        )
        decision = authorize(
            user=actor,
            capability=Capability.DOCUMENT_SET_RETRIEVE_GRANT,
            organization=locked.organization,
            scenario=locked.scenario,
            document_set=locked.document_set,
        )
        if not decision.allowed or decision.source not in allowed_sources:
            raise ScenarioDocumentSetAccessError("DOCUMENT_SET_MANAGER_REQUIRED")
        if locked.status == ScenarioDocumentSetGrantStatus.REVOKED:
            return
        locked.status = ScenarioDocumentSetGrantStatus.REVOKED
        locked.shared_consumers = False
        locked.shared_approved_by = None
        locked.shared_approved_at = None
        locked.revoked_by = actor
        locked.revoked_at = timezone.now()
        locked.save()
        _audit(
            actor=actor,
            action=(
                "superadmin.scenario_document_set_access_revoke"
                if decision.source == AuthoritySource.SUPERADMIN_RECOVERY
                else "scenario_document_set_access.revoke"
            ),
            outcome="success",
            organization_id=locked.organization_id,
            resource_type="scenario_document_set_grant",
            resource_id=str(locked.pk),
            reason="ACCESS_REVOKED",
            request_id=request_id,
            trace_id=trace_id,
        )


def has_live_scenario_document_set_grant(*, scenario_id: int, document_set_id: int) -> bool:
    return ScenarioDocumentSetGrant.objects.filter(
        scenario_id=scenario_id,
        document_set_id=document_set_id,
        permission=GrantPermission.RETRIEVE,
        status=ScenarioDocumentSetGrantStatus.GRANTED,
        revoked_at__isnull=True,
    ).exists()


def _ensure_evaluation_consumer_grant(
    *, document_set: Any, actor: Any, request_id: str = ""
) -> None:
    """Give the org's synthetic ``system:evaluation`` consumer retrieval on this set.

    Without this, "Sor" and "Yayımla ve test et" (which both run retrieval as this shared,
    platform-internal consumer -- never a real API client) silently retrieve zero chunks even
    after a live `ScenarioDocumentSetGrant` exists (BUG-015). The consumer grants no external
    API access, so this carries no additional authorization risk beyond the document-set-manager
    check already performed by the caller.
    """
    from apps.documents.models import GrantPrincipalType
    from apps.documents.services import DocumentError, grant_document_set
    from apps.evaluations.services import EvalError, evaluation_consumer_for_organization

    try:
        consumer = evaluation_consumer_for_organization(document_set.organization_id)
    except EvalError:
        return
    try:
        grant_document_set(
            document_set=document_set,
            principal_type=GrantPrincipalType.CONSUMER,
            principal_ref=str(consumer.pk),
            actor=actor.get_username(),
            request_id=request_id,
        )
    except DocumentError as exc:
        if exc.code != "DUPLICATE_GRANT":
            raise


def grant_scenario_document_set_access_if_authorized(
    *,
    scenario: Any,
    document_set: Any,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioDocumentSetGrant | None:
    """Grant live retrieval authority in the same step as binding (BUG-003 option a).

    Only takes effect when ``actor`` already holds document-set-manager authority
    (`Capability.DOCUMENT_SET_RETRIEVE_GRANT`, sourced from a real `DocumentSetResponsibility`
    or superadmin recovery) -- the same predicate `approve_scenario_document_set_access` already
    enforces, just without requiring a separate pending request first. Returns ``None`` (never
    raises for an authorization shortfall) when the actor lacks that authority: binding itself
    must still succeed, and a document-set manager can grant access separately afterward.
    """
    decision = authorize(
        user=actor,
        capability=Capability.DOCUMENT_SET_RETRIEVE_GRANT,
        organization=scenario.organization,
        scenario=scenario,
        document_set=document_set,
    )
    if not decision.allowed or decision.source not in {
        AuthoritySource.DOCUMENT_SET_RESPONSIBILITY,
        AuthoritySource.SUPERADMIN_RECOVERY,
    }:
        return None
    now = timezone.now()
    with transaction.atomic():
        grant, _created = ScenarioDocumentSetGrant.objects.update_or_create(
            scenario=scenario,
            document_set=document_set,
            permission=GrantPermission.RETRIEVE,
            defaults={
                "organization": scenario.organization,
                "status": ScenarioDocumentSetGrantStatus.GRANTED,
                "granted_by": actor,
                "granted_at": now,
                "revoked_by": None,
                "revoked_at": None,
            },
        )
        _audit(
            actor=actor,
            action="scenario_document_set_access.grant_on_bind",
            outcome="success",
            organization_id=scenario.organization_id,
            resource_type="scenario_document_set_grant",
            resource_id=str(grant.pk),
            reason="ACCESS_GRANTED_ON_BIND",
            request_id=request_id,
            trace_id=trace_id,
        )
    _ensure_evaluation_consumer_grant(document_set=document_set, actor=actor, request_id=request_id)
    return grant


def bind_authorized_scenario_document_set(
    *,
    scenario: Any,
    document_set: Any,
    actor: Any,
    request_id: str = "",
) -> Any:
    """Bind configuration only after exact author authority and a live grant."""

    decision = authorize(
        user=actor,
        capability=Capability.SCENARIO_EDIT,
        organization=scenario.organization,
        project=scenario.project,
        scenario=scenario,
        document_set=document_set,
    )
    if not decision.allowed or decision.source not in {
        AuthoritySource.PROJECT_RESPONSIBILITY,
        AuthoritySource.SCENARIO_RESPONSIBILITY,
    }:
        raise ScenarioDocumentSetAccessError("SCENARIO_BIND_DENIED")
    if not has_live_scenario_document_set_grant(
        scenario_id=scenario.pk,
        document_set_id=document_set.pk,
    ):
        raise ScenarioDocumentSetAccessError("LIVE_RETRIEVE_GRANT_REQUIRED")
    from apps.documents.services import bind_scenario_document_set

    return bind_scenario_document_set(
        scenario=scenario,
        document_set=document_set,
        actor=actor.get_username(),
        request_id=request_id,
    )
