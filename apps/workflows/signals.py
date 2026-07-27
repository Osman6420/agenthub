"""Auto-resume a paused workflow run once its tool approval is decided.

A tool-node run parks in ``waiting_approval`` with a durable checkpoint. When an
operator approves or rejects the linked invocation, this re-dispatches the run's
Celery task after the deciding transaction commits; the runtime then executes the
approved tool (or fails closed on rejection). Enqueue happens only on commit, so a
rolled-back decision never triggers a resume.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.tools.models import ApprovalRequest, ApprovalStatus

_DECIDED = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.REJECTED})


@receiver(post_save, sender=ApprovalRequest, dispatch_uid="workflows.tool_approval_resume")
def resume_workflow_on_tool_decision(sender: Any, instance: ApprovalRequest, **kwargs: Any) -> None:
    if instance.status not in _DECIDED:
        return
    run_id = _run_id_from_invocation_key(instance)
    if run_id is None:
        return

    from apps.workflows.tasks import execute_workflow_run

    organization_id = instance.organization_id
    transaction.on_commit(lambda: execute_workflow_run.delay(run_id, organization_id))


@receiver(post_save, sender=ApprovalRequest, dispatch_uid="workflows.unified_tool_approval_resume")
def resume_unified_run_on_tool_decision(
    sender: Any, instance: ApprovalRequest, **kwargs: Any
) -> None:
    """Re-admit a unified Run parked on this approval, then redeliver it after commit."""
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
        # Deferred to commit for two reasons: the deciding transaction only moves the invocation
        # out of ``pending_approval`` after this signal fires, and a rolled-back decision must
        # never re-admit the Run.
        try:
            resume_run_for_approval(
                organization_id=organization_id,
                run_id=run_id,
                invocation_id=instance.invocation_id,
            )
        except (RunWaitError, Run.DoesNotExist):
            # A Run that is not parked on exactly this invocation has already converged, so the
            # decision must not move it.
            return
        try:
            dispatch_unified_background_run(run_id=run_id, organization_id=organization_id)
        except UnifiedExecutorError:
            # The Run is queued and durable; a disabled executor only delays its next delivery.
            return

    transaction.on_commit(_resume)


def _run_id_from_invocation_key(approval: ApprovalRequest) -> int | None:
    # Workflow tool invocations use a "wf:<run_id>:<node_id>" idempotency key.
    key = approval.invocation.idempotency_key
    if not key.startswith("wf:"):
        return None
    parts = key.split(":")
    if len(parts) < 3:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


# --- Child composition resume (P2.6.5) ------------------------------------------------------------
# A parent workflow node parks in ``waiting_child`` while a pinned child sub-workflow/agent runs
# as a separate durable run. When that child reaches a terminal state, re-dispatch the parent so it
# can validate the untrusted child output and resume. Enqueue only after commit, so a rolled-back
# child transition never resumes the parent. The parent task's terminal guards make a late/duplicate
# child result a safe no-op against an already-terminal parent.
def _resume_parent_for_child_link(link: Any) -> None:
    from apps.workflows.tasks import execute_workflow_run

    parent_run_id = link.parent_run_id
    organization_id = link.organization_id
    transaction.on_commit(lambda: execute_workflow_run.delay(parent_run_id, organization_id))


def _connect_child_resume_receivers() -> None:
    """Connect terminal-child → parent-resume receivers (called from ``ready()``)."""
    from apps.agents.models import TERMINAL_RUN_STATUSES, AgentRun
    from apps.workflows.models import (
        WORKFLOW_TERMINAL_STATUSES,
        WorkflowChildLink,
        WorkflowRun,
    )

    def _on_child_workflow(sender: Any, instance: Any, **kwargs: Any) -> None:
        if instance.status not in WORKFLOW_TERMINAL_STATUSES:
            return
        link = WorkflowChildLink.objects.filter(child_workflow_run=instance).first()
        if link is not None:
            _resume_parent_for_child_link(link)

    def _on_child_agent(sender: Any, instance: Any, **kwargs: Any) -> None:
        if instance.status not in TERMINAL_RUN_STATUSES:
            return
        link = WorkflowChildLink.objects.filter(child_agent_run=instance).first()
        if link is not None:
            _resume_parent_for_child_link(link)

    # weak=False: the receivers are module-scoped closures, so keep a strong reference.
    post_save.connect(
        _on_child_workflow,
        sender=WorkflowRun,
        dispatch_uid="workflows.child_workflow_resume",
        weak=False,
    )
    post_save.connect(
        _on_child_agent,
        sender=AgentRun,
        dispatch_uid="workflows.child_agent_resume",
        weak=False,
    )
