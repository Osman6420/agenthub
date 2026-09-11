"""Explicit data-owner consent for current and future authorized scenario consumers."""

from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.catalog.models import Scenario, ScenarioDataAccessMode
from apps.documents.access_services import ScenarioDocumentSetAccessError
from apps.documents.models import ScenarioDocumentSetGrant
from apps.identity.authorization import AuthoritySource, Capability, authorize
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization


def set_shared_consumer_consent(
    *,
    grant: ScenarioDocumentSetGrant,
    actor: Any,
    enabled: bool,
    acknowledge_future_consumers: bool = False,
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioDocumentSetGrant:
    action = "scenario_document_set_access.shared_consent"
    try:
        with transaction.atomic():
            set_tenant_context(grant.organization_id)
            Organization.objects.select_for_update().get(pk=grant.organization_id)
            current = (
                ScenarioDocumentSetGrant.objects.select_for_update()
                .select_related(
                    "scenario__project", "scenario__organization", "document_set", "organization"
                )
                .get(pk=grant.pk, organization_id=grant.organization_id)
            )
            decision = authorize(
                user=actor,
                capability=Capability.DOCUMENT_SET_RETRIEVE_GRANT,
                organization=current.organization,
                scenario=current.scenario,
                document_set=current.document_set,
            )
            if (
                not decision.allowed
                or decision.source != AuthoritySource.DOCUMENT_SET_RESPONSIBILITY
            ):
                raise ScenarioDocumentSetAccessError("DOCUMENT_SET_MANAGER_REQUIRED")
            if not isinstance(enabled, bool) or (
                enabled and acknowledge_future_consumers is not True
            ):
                raise ScenarioDocumentSetAccessError("SHARED_FUTURE_CONSUMERS_ACK_REQUIRED")
            if enabled and not current.is_active:
                raise ScenarioDocumentSetAccessError("LIVE_SCENARIO_GRANT_REQUIRED")
            if current.shared_consumers == enabled:
                return current
            current.shared_consumers = enabled
            current.shared_approved_by = actor if enabled else None
            current.shared_approved_at = timezone.now() if enabled else None
            current.save(
                update_fields=[
                    "shared_consumers",
                    "shared_approved_by",
                    "shared_approved_at",
                    "updated_at",
                ]
            )
            record_event(
                actor_type="user",
                actor_id=actor.get_username(),
                action=action,
                outcome="success",
                organization_id=current.organization_id,
                resource_type="scenario_document_set_grant",
                resource_id=str(current.pk),
                reason="EXPLICIT_SHARED_CONSENT" if enabled else "SHARED_CONSENT_REVOKED",
                request_id=request_id,
                trace_id=trace_id,
                after={
                    "shared_consumers": enabled,
                    "includes_future_authorized_consumers": enabled,
                },
            )
            return current
    except ScenarioDocumentSetAccessError as exc:
        record_event(
            actor_type="user",
            actor_id=actor.get_username(),
            action=action,
            outcome="deny",
            organization_id=grant.organization_id,
            resource_type="scenario_document_set_grant",
            resource_id=str(grant.pk),
            reason=exc.code,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise


def set_scenario_data_access_mode(
    *,
    scenario: Scenario,
    actor: Any,
    mode: str,
    expected_mode: str | None = None,
    request_id: str = "",
    trace_id: str = "",
) -> Scenario:
    action = "scenario.data_access_mode_changed"
    try:
        with transaction.atomic():
            set_tenant_context(scenario.organization_id)
            Organization.objects.select_for_update().get(pk=scenario.organization_id)
            current = (
                Scenario.objects.select_for_update()
                .select_related("organization", "project")
                .get(pk=scenario.pk, organization_id=scenario.organization_id)
            )
            if not authorize(
                user=actor, capability=Capability.SCENARIO_EDIT, scenario=current
            ).allowed:
                raise ScenarioDocumentSetAccessError("SCENARIO_EDIT_REQUIRED")
            if mode not in ScenarioDataAccessMode.values:
                raise ScenarioDocumentSetAccessError("INVALID_DATA_ACCESS_MODE")
            if mode == current.data_access_mode:
                return current
            if expected_mode is not None and expected_mode != current.data_access_mode:
                raise ScenarioDocumentSetAccessError("DATA_ACCESS_MODE_STALE")
            previous = current.data_access_mode
            current.data_access_mode = mode
            current.save(update_fields=["data_access_mode", "updated_at"])
            record_event(
                actor_type="user",
                actor_id=actor.get_username(),
                action=action,
                outcome="success",
                organization_id=current.organization_id,
                resource_type="scenario",
                resource_id=str(current.public_id),
                reason="EXPLICIT_DATA_ACCESS_MODE",
                request_id=request_id,
                trace_id=trace_id,
                before={"mode": previous},
                after={"mode": mode},
            )
            return current
    except ScenarioDocumentSetAccessError as exc:
        record_event(
            actor_type="user",
            actor_id=actor.get_username(),
            action=action,
            outcome="deny",
            organization_id=scenario.organization_id,
            resource_type="scenario",
            resource_id=str(scenario.public_id),
            reason=exc.code,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise
