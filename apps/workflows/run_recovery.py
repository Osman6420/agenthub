"""Explicit operator resolution for ambiguous canonical Run outcomes."""

from __future__ import annotations

import uuid

from django.db import transaction

from apps.audit.services import record_event
from apps.tenancy.context import set_tenant_context
from apps.workflows.models import Run, RunStatus
from apps.workflows.transitions import RunTransitionResult, transition_run

_TARGET_BY_DECISION = {
    "confirm_failed": RunStatus.FAILED,
    "confirm_cancelled": RunStatus.CANCELLED,
}


class RunRecoveryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@transaction.atomic
def resolve_run_recovery(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    actor_id: str,
    decision: str,
) -> RunTransitionResult:
    """Close recovery explicitly; ambiguous work is never re-run automatically."""

    target = _TARGET_BY_DECISION.get(decision)
    if target is None:
        raise RunRecoveryError("RUN_RECOVERY_DECISION_INVALID")
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    if run.status != RunStatus.RECOVERY_REQUIRED:
        raise RunRecoveryError("RUN_RECOVERY_NOT_REQUIRED")
    reason_code = (
        "OPERATOR_CONFIRMED_FAILED"
        if target == RunStatus.FAILED
        else "OPERATOR_CONFIRMED_CANCELLED"
    )
    record_event(
        actor_type="user",
        actor_id=actor_id[:200],
        action="workflow.run.recovery.resolve",
        outcome="success",
        organization_id=organization_id,
        resource_type="run",
        resource_id=str(run.id),
        reason=reason_code,
        before={"status": str(run.status), "checkpoint_version": run.checkpoint_version},
        after={"status": str(target)},
    )
    return transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=uuid.uuid5(run.id, f"recovery:{decision}:{run.checkpoint_version}"),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=RunStatus.RECOVERY_REQUIRED,
        target_status=target,
        reason_code=reason_code,
        error_code=run.error_code,
    )
