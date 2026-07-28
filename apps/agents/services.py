"""Shared fail-closed suspension controls for workflow agent-loop nodes."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Q

from apps.agents.models import AgentRuntimeControl
from apps.audit.services import record_event
from apps.tenancy.context import set_tenant_scope


def runtime_suspended(organization_id: int) -> bool:
    """Return whether the global or tenant-specific agent-loop switch is suspended."""

    return AgentRuntimeControl.objects.filter(
        Q(organization__isnull=True) | Q(organization_id=organization_id),
        suspended=True,
    ).exists()


@transaction.atomic
def set_runtime_suspension(
    *,
    organization_id: int | None,
    suspended: bool,
    actor: str,
    reason: str = "",
) -> AgentRuntimeControl:
    """Idempotently update one audited global or tenant suspension control."""

    if organization_id is not None:
        set_tenant_scope((organization_id,))
    lookup: dict[str, Any] = {"organization_id": organization_id}
    control, _created = AgentRuntimeControl.objects.select_for_update().get_or_create(
        defaults={"suspended": suspended, "updated_by": actor, "reason": reason[:200]},
        **lookup,
    )
    control.suspended = suspended
    control.updated_by = actor
    control.reason = reason[:200]
    control.save(update_fields=["suspended", "updated_by", "reason", "updated_at"])
    record_event(
        actor_type="user",
        actor_id=actor,
        action="agent.runtime_suspend" if suspended else "agent.runtime_resume",
        outcome="success",
        organization_id=organization_id,
        resource_type="agent_runtime_control",
        resource_id="global" if organization_id is None else str(organization_id),
        reason=reason[:64] or ("suspended" if suspended else "resumed"),
    )
    return control
