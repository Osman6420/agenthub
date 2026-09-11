"""Closed consumer access packages for the human console; legacy vocabulary is preserved."""

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.identity.authorization import Capability as OperatorCapability
from apps.identity.authorization import authorize
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization


class ConsumerAccessError(ValueError):
    pass


@dataclass(frozen=True)
class ConsumerAccessOptions:
    run_scenario: bool = True
    read_tools: bool = False
    side_effect_tools: bool = False
    retrieve_debug: bool = False
    ingestion_status: bool = False


OPTION_CAPABILITIES = {
    "run_scenario": Capability.WORKFLOW_RUN,
    "read_tools": Capability.TOOL_CALL,
    "side_effect_tools": Capability.TOOL_CALL_SIDE_EFFECT,
    "retrieve_debug": Capability.RETRIEVE_DEBUG,
    "ingestion_status": Capability.INGESTION_READ,
}


def package_capabilities(options: ConsumerAccessOptions) -> list[str]:
    if not isinstance(options, ConsumerAccessOptions) or any(
        not isinstance(getattr(options, field), bool) for field in OPTION_CAPABILITIES
    ):
        raise ConsumerAccessError("INVALID_ACCESS_OPTIONS")
    if options.side_effect_tools and not options.read_tools:
        raise ConsumerAccessError("TOOL_ACCESS_REQUIRED")
    result: list[str] = [
        cap for field, cap in OPTION_CAPABILITIES.items() if getattr(options, field)
    ]
    if not result:
        raise ConsumerAccessError("ACCESS_OPTION_REQUIRED")
    return result


def create_console_binding(
    *,
    consumer: Consumer,
    scenario: Scenario,
    actor: Any,
    options: ConsumerAccessOptions,
    status: str = "active",
    request_id: str = "",
    trace_id: str = "",
) -> ConsumerBinding:
    try:
        with transaction.atomic():
            set_tenant_context(consumer.organization_id)
            organization = Organization.objects.select_for_update().get(pk=consumer.organization_id)
            if (
                organization.status != "active"
                or not authorize(
                    user=actor,
                    capability=OperatorCapability.ORGANIZATION_MANAGE,
                    organization=organization,
                ).allowed
            ):
                raise ConsumerAccessError("ORGANIZATION_ADMIN_REQUIRED")
            current_consumer = (
                Consumer.objects.select_for_update()
                .filter(pk=consumer.pk, organization=organization, status="active")
                .first()
            )
            current_scenario = Scenario.objects.filter(
                pk=scenario.pk, organization=organization, project__organization=organization
            ).first()
            if current_consumer is None or current_scenario is None:
                raise ConsumerAccessError("INVALID_BINDING_SCOPE")
            binding = ConsumerBinding.objects.create(
                consumer=current_consumer,
                scenario=current_scenario,
                status=status,
                capabilities=package_capabilities(options),
            )
            record_event(
                actor_type="user",
                actor_id=actor.get_username(),
                action="console.binding.create",
                outcome="success",
                organization_id=organization.pk,
                resource_type="binding",
                resource_id=str(binding.pk),
                reason="EXPLICIT_ACCESS_PACKAGES",
                request_id=request_id,
                trace_id=trace_id,
                after={"capabilities": binding.capabilities, "status": binding.status},
            )
            return binding
    except (ConsumerAccessError, ValidationError, IntegrityError) as exc:
        reason = (
            str(exc) if isinstance(exc, ConsumerAccessError) else "INVALID_OR_DUPLICATE_BINDING"
        )
        record_event(
            actor_type="user",
            actor_id=actor.get_username(),
            action="console.binding.create",
            outcome="deny",
            organization_id=consumer.organization_id,
            resource_type="consumer",
            resource_id=str(consumer.public_id),
            reason=reason,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise ConsumerAccessError(reason) from exc
