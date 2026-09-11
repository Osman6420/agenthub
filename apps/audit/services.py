"""Audit write API.

All audit writes go through :func:`record_event` so callers cannot accidentally
mutate history. Payloads must already be redacted by the caller — never pass
secrets or raw PII.
"""

from __future__ import annotations

from apps.audit.models import ActorType, AuditEvent, Outcome


def record_event(
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    outcome: str,
    organization_id: int | None = None,
    resource_type: str = "",
    resource_id: str = "",
    reason: str = "",
    request_id: str = "",
    trace_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
) -> AuditEvent:
    """Append an immutable audit event and return it."""
    if actor_type not in ActorType.values:
        raise ValueError(f"invalid actor_type: {actor_type}")
    if outcome not in Outcome.values:
        raise ValueError(f"invalid outcome: {outcome}")
    return AuditEvent.objects.create(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        outcome=outcome,
        organization_id=organization_id,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        request_id=request_id,
        trace_id=trace_id,
        before=before,
        after=after,
    )
