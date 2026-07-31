"""Shared fail-closed controls for the unified workflow runtime."""

from __future__ import annotations

import re
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.agents.models import (
    AgentRuntimeControl,
    RuntimeControlScope,
    RuntimeControlSource,
)
from apps.audit.services import record_event
from apps.identity.authorization import AuthoritySource, Capability, authorize
from apps.observability.metrics import RUNTIME_CONTROL_CHANGES, RUNTIME_SUSPENSION_BLOCKS
from apps.tenancy.context import set_tenant_scope

RUNTIME_CONTROL_REASON_CODES = frozenset(
    {
        "capacity_protection",
        "dependency_outage",
        "incident_response",
        "maintenance",
        "manual_safety_stop",
        "policy_violation",
    }
)
_SAFE_REASON = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]{1,200}$")


class RuntimeControlError(ValueError):
    """Stable failure at the runtime-control authorization boundary."""


def _bounded_reason(reason: str) -> str:
    value = reason.strip()
    if not _SAFE_REASON.fullmatch(value):
        raise RuntimeControlError("RUNTIME_CONTROL_REASON_INVALID")
    return value


def _scope_lookup(
    *,
    scope_type: str,
    organization_id: int | None,
    project_id: int | None,
    scenario_id: int | None,
) -> dict[str, Any]:
    try:
        scope = RuntimeControlScope(scope_type)
    except ValueError:
        raise RuntimeControlError("RUNTIME_CONTROL_SCOPE_INVALID") from None
    if scope == RuntimeControlScope.PLATFORM:
        if any(value is not None for value in (organization_id, project_id, scenario_id)):
            raise RuntimeControlError("RUNTIME_CONTROL_SCOPE_MISMATCH")
        return {
            "scope_type": scope,
            "organization_id": None,
            "project_id": None,
            "scenario_id": None,
        }
    if scope == RuntimeControlScope.ORGANIZATION:
        if organization_id is None or project_id is not None or scenario_id is not None:
            raise RuntimeControlError("RUNTIME_CONTROL_SCOPE_MISMATCH")
    elif scope == RuntimeControlScope.PROJECT:
        if organization_id is None or project_id is None or scenario_id is not None:
            raise RuntimeControlError("RUNTIME_CONTROL_SCOPE_MISMATCH")
    elif organization_id is None or project_id is not None or scenario_id is None:
        raise RuntimeControlError("RUNTIME_CONTROL_SCOPE_MISMATCH")
    return {
        "scope_type": scope,
        "organization_id": organization_id,
        "project_id": project_id,
        "scenario_id": scenario_id,
    }


def runtime_suspended(
    organization_id: int,
    *,
    project_id: int | None = None,
    scenario_id: int | None = None,
) -> bool:
    """Return the strongest active control applicable to trusted runtime lineage."""

    applicable = Q(scope_type=RuntimeControlScope.PLATFORM)
    applicable |= Q(
        scope_type=RuntimeControlScope.ORGANIZATION,
        organization_id=organization_id,
    )
    if project_id is not None:
        applicable |= Q(
            scope_type=RuntimeControlScope.PROJECT,
            organization_id=organization_id,
            project_id=project_id,
        )
    if scenario_id is not None:
        applicable |= Q(
            scope_type=RuntimeControlScope.SCENARIO,
            organization_id=organization_id,
            scenario_id=scenario_id,
        )
    return AgentRuntimeControl.objects.filter(applicable, suspended=True).exists()


def observe_runtime_suspension(boundary: str) -> None:
    """Count only the closed admission/claim/transition boundary label."""

    label = boundary if boundary in {"admission", "claim", "transition"} else "other"
    RUNTIME_SUSPENSION_BLOCKS.labels(boundary=label).inc()


def applicable_runtime_controls(
    organization_id: int,
    *,
    project_id: int | None = None,
    scenario_id: int | None = None,
) -> list[AgentRuntimeControl]:
    """Return active applicable controls in dominance order without payload-bearing data."""

    applicable = Q(scope_type=RuntimeControlScope.PLATFORM)
    applicable |= Q(
        scope_type=RuntimeControlScope.ORGANIZATION,
        organization_id=organization_id,
    )
    if project_id is not None:
        applicable |= Q(
            scope_type=RuntimeControlScope.PROJECT,
            organization_id=organization_id,
            project_id=project_id,
        )
    if scenario_id is not None:
        applicable |= Q(
            scope_type=RuntimeControlScope.SCENARIO,
            organization_id=organization_id,
            scenario_id=scenario_id,
        )
    order = {
        RuntimeControlScope.PLATFORM: 0,
        RuntimeControlScope.ORGANIZATION: 1,
        RuntimeControlScope.PROJECT: 2,
        RuntimeControlScope.SCENARIO: 3,
    }
    return sorted(
        AgentRuntimeControl.objects.filter(applicable, suspended=True).select_related(
            "organization", "project", "scenario"
        ),
        key=lambda control: order[RuntimeControlScope(control.scope_type)],
    )


def _resource_id(lookup: dict[str, Any]) -> str:
    scope = RuntimeControlScope(lookup["scope_type"])
    if scope == RuntimeControlScope.PLATFORM:
        return "platform"
    target_id = lookup[f"{scope.value}_id"]
    return f"{scope.value}:{target_id}"


def _record_control_event(
    *,
    actor_id: str,
    organization_id: int | None,
    suspended: bool,
    outcome: str,
    reason_code: str,
    authority_source: str,
    resource_id: str,
    superadmin: bool,
) -> None:
    action = (
        "superadmin.runtime_control"
        if superadmin
        else ("runtime.control.pause" if suspended else "runtime.control.resume")
    )
    record_event(
        actor_type="user",
        actor_id=actor_id,
        action=action,
        outcome=outcome,
        organization_id=organization_id,
        resource_type="runtime_control",
        resource_id=resource_id,
        reason=f"{reason_code}:{authority_source}"[:128],
    )
    scope = resource_id.split(":", 1)[0]
    RUNTIME_CONTROL_CHANGES.labels(
        scope=scope if scope in RuntimeControlScope.values else "other",
        action="pause" if suspended else "resume",
        outcome=outcome if outcome in {"allow", "deny"} else "other",
    ).inc()


def change_runtime_control(
    *,
    user: Any,
    scope_type: str,
    suspended: bool,
    reason_code: str,
    reason: str,
    organization: Any | None = None,
    project: Any | None = None,
    scenario: Any | None = None,
    source: str = RuntimeControlSource.HUMAN,
    requires_privileged_resume: bool = False,
) -> AgentRuntimeControl:
    """Authorize and transactionally mutate one exact persisted control."""

    if reason_code not in RUNTIME_CONTROL_REASON_CODES:
        raise RuntimeControlError("RUNTIME_CONTROL_REASON_CODE_INVALID")
    bounded_reason = _bounded_reason(reason)
    try:
        control_source = RuntimeControlSource(source)
    except ValueError:
        raise RuntimeControlError("RUNTIME_CONTROL_SOURCE_INVALID") from None
    lookup = _scope_lookup(
        scope_type=scope_type,
        organization_id=getattr(organization, "pk", None),
        project_id=getattr(project, "pk", None),
        scenario_id=getattr(scenario, "pk", None),
    )
    if project is not None and project.organization_id != getattr(organization, "pk", None):
        raise RuntimeControlError("RUNTIME_CONTROL_SCOPE_MISMATCH")
    if scenario is not None and scenario.organization_id != getattr(organization, "pk", None):
        raise RuntimeControlError("RUNTIME_CONTROL_SCOPE_MISMATCH")

    decision = authorize(
        user=user,
        capability=Capability.RUNTIME_PAUSE if suspended else Capability.RUNTIME_RESUME,
        organization=organization,
        project=project,
        scenario=scenario,
    )
    actor_id = str(getattr(user, "pk", ""))
    resource_id = _resource_id(lookup)
    is_superadmin = decision.source == AuthoritySource.SUPERADMIN_RECOVERY
    if not decision.allowed:
        _record_control_event(
            actor_id=actor_id,
            organization_id=lookup["organization_id"],
            suspended=suspended,
            outcome="deny",
            reason_code=decision.reason,
            authority_source=str(decision.source),
            resource_id=resource_id,
            superadmin=is_superadmin,
        )
        raise RuntimeControlError("RUNTIME_CONTROL_FORBIDDEN")

    if lookup["organization_id"] is not None:
        set_tenant_scope((lookup["organization_id"],))
    privileged_resume_denied = False
    with transaction.atomic():
        control = AgentRuntimeControl.objects.select_for_update().filter(**lookup).first()
        if (
            not suspended
            and control is not None
            and control.requires_privileged_resume
            and decision.source != AuthoritySource.SUPERADMIN_RECOVERY
        ):
            privileged_resume_denied = True
        else:
            if control is None:
                control = AgentRuntimeControl(**lookup)
            control.suspended = suspended
            control.reason_code = reason_code
            control.reason = bounded_reason
            control.source = control_source if suspended else control.source
            control.requires_privileged_resume = bool(
                suspended
                and (
                    requires_privileged_resume
                    or control_source
                    in {RuntimeControlSource.AUTOMATIC, RuntimeControlSource.POLICY}
                )
            )
            control.updated_by = actor_id
            control.activated_at = timezone.now() if suspended else None
            control.full_clean(validate_unique=False)
            control.save()
            _record_control_event(
                actor_id=actor_id,
                organization_id=lookup["organization_id"],
                suspended=suspended,
                outcome="allow",
                reason_code=reason_code,
                authority_source=str(decision.source),
                resource_id=resource_id,
                superadmin=is_superadmin,
            )
    if privileged_resume_denied:
        _record_control_event(
            actor_id=actor_id,
            organization_id=lookup["organization_id"],
            suspended=False,
            outcome="deny",
            reason_code="PRIVILEGED_RESUME_REQUIRED",
            authority_source=str(decision.source),
            resource_id=resource_id,
            superadmin=is_superadmin,
        )
        raise RuntimeControlError("RUNTIME_CONTROL_PRIVILEGED_RESUME_REQUIRED")
    if control is None:  # Defensive: every non-denied path creates or locks the exact row.
        raise RuntimeControlError("RUNTIME_CONTROL_STATE_INVALID")
    return control


@transaction.atomic
def set_runtime_suspension(
    *,
    organization_id: int | None,
    suspended: bool,
    actor: str,
    reason: str = "",
) -> AgentRuntimeControl:
    """Compatibility command boundary for platform/organization controls."""

    if organization_id is not None:
        set_tenant_scope((organization_id,))
    scope_type = (
        RuntimeControlScope.PLATFORM
        if organization_id is None
        else RuntimeControlScope.ORGANIZATION
    )
    lookup = _scope_lookup(
        scope_type=scope_type,
        organization_id=organization_id,
        project_id=None,
        scenario_id=None,
    )
    control, _created = AgentRuntimeControl.objects.select_for_update().get_or_create(**lookup)
    control.suspended = suspended
    control.reason_code = "manual_safety_stop"
    control.reason = (reason.strip() or "Operator command")[:200]
    control.source = RuntimeControlSource.HUMAN
    control.requires_privileged_resume = False
    control.updated_by = actor[:200]
    control.activated_at = timezone.now() if suspended else None
    control.full_clean(validate_unique=False)
    control.save()
    record_event(
        actor_type="user",
        actor_id=actor[:200],
        action="agent.runtime_suspend" if suspended else "agent.runtime_resume",
        outcome="success",
        organization_id=organization_id,
        resource_type="runtime_control",
        resource_id=_resource_id(lookup),
        reason="manual_safety_stop",
    )
    return control
