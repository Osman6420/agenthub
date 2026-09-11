"""Consumer/binding resolution.

Resolution is fail-closed: a binding is returned only when the consumer, the
binding, the scenario, and the targeted alias are all active and belong to the same
organization. The gateway (Sprint 3) uses this to authorize a call before issuing
an ExecutionContext.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.catalog.models import AliasStatus, LifecycleStatus, ScenarioAlias
from apps.identity.models import BindingStatus, Consumer, ConsumerBinding, ConsumerStatus


@dataclass(frozen=True)
class ResolvedBinding:
    consumer: Consumer
    binding: ConsumerBinding
    capabilities: frozenset[str]


def resolve_active_binding(
    *, organization_id: int, subject: str, alias: str
) -> ResolvedBinding | None:
    """Resolve an active binding for a consumer subject targeting a scenario alias.

    Returns ``None`` (deny) if anything in the chain is missing or disabled.
    """
    consumer = (
        Consumer.objects.filter(
            organization_id=organization_id,
            subject=subject,
            status=ConsumerStatus.ACTIVE,
        )
        .only("id", "organization_id", "status")
        .first()
    )
    if consumer is None:
        return None

    alias_row = (
        ScenarioAlias.objects.select_related("scenario")
        .filter(
            organization_id=organization_id,
            alias=alias,
            status=AliasStatus.ACTIVE,
        )
        .first()
    )
    if alias_row is None:
        return None

    scenario = alias_row.scenario
    if scenario.status != LifecycleStatus.ACTIVE:
        return None

    binding = ConsumerBinding.objects.filter(
        consumer=consumer,
        scenario=scenario,
        status=BindingStatus.ACTIVE,
    ).first()
    if binding is None:
        return None

    return ResolvedBinding(
        consumer=consumer,
        binding=binding,
        capabilities=frozenset(binding.capabilities),
    )
