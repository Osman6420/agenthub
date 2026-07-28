"""Re-admit unified Runs after a governed tool-approval decision."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.tools.models import ApprovalRequest, ApprovalStatus
from apps.workflows.models import RUN_TERMINAL_STATUSES, Run

_DECIDED = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.REJECTED})


@receiver(post_save, sender=ApprovalRequest, dispatch_uid="workflows.unified_tool_approval_resume")
def resume_unified_run_on_tool_decision(
    sender: Any, instance: ApprovalRequest, **kwargs: Any
) -> None:
    if instance.status not in _DECIDED:
        return

    from apps.workflows.models import Run
    from apps.workflows.run_waits import (
        RunWaitError,
        resume_run_for_approval,
        run_id_from_tool_idempotency_key,
    )
    from apps.workflows.tasks import dispatch_unified_background_run
    from apps.workflows.unified_executor import UnifiedExecutorError

    run_id = run_id_from_tool_idempotency_key(instance.invocation.idempotency_key)
    if run_id is None:
        return
    organization_id = instance.organization_id

    def _resume() -> None:
        try:
            resume_run_for_approval(
                organization_id=organization_id,
                run_id=run_id,
                invocation_id=instance.invocation_id,
            )
        except (RunWaitError, Run.DoesNotExist):
            return
        try:
            dispatch_unified_background_run(run_id=run_id, organization_id=organization_id)
        except UnifiedExecutorError:
            return

    transaction.on_commit(_resume)


@receiver(post_save, sender=Run, dispatch_uid="workflows.unified_child_converge")
def converge_unified_child_on_terminal(sender: Any, instance: Run, **kwargs: Any) -> None:
    """Resume an exact parent only after its child terminal state commits."""

    if instance.status not in RUN_TERMINAL_STATUSES:
        return

    def _converge() -> None:
        from apps.workflows.run_children import RunChildError, converge_run_child

        try:
            converge_run_child(
                child_run_id=instance.id,
                organization_id=instance.organization_id,
            )
        except (Run.DoesNotExist, RunChildError):
            return

    transaction.on_commit(_converge)
