"""Auto-resume a paused agent run once its tool approval is decided.

A tool step parks the run in ``waiting_approval`` with a durable checkpoint. When an
operator approves or rejects the linked invocation, this re-dispatches the run's Celery
task after the deciding transaction commits; the runtime then executes the approved tool
(or fails closed on rejection). Enqueue happens only on commit, so a rolled-back decision
never triggers a resume. The workflow and agent resume handlers are disjoint: each keys
off its own idempotency-key prefix (``wf:`` vs ``agent:``), so a decision resumes exactly
one runtime.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.tools.models import ApprovalRequest, ApprovalStatus

_DECIDED = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.REJECTED})


@receiver(post_save, sender=ApprovalRequest, dispatch_uid="agents.tool_approval_resume")
def resume_agent_on_tool_decision(sender: Any, instance: ApprovalRequest, **kwargs: Any) -> None:
    if instance.status not in _DECIDED:
        return
    run_id = _run_id_from_invocation_key(instance)
    if run_id is None:
        return

    from apps.agents.tasks import execute_agent_run

    organization_id = instance.organization_id
    transaction.on_commit(lambda: execute_agent_run.delay(run_id, organization_id))


def _run_id_from_invocation_key(approval: ApprovalRequest) -> int | None:
    # Agent tool invocations use an "agent:<run_id>:<step_index>" idempotency key.
    key = approval.invocation.idempotency_key
    if not key.startswith("agent:"):
        return None
    parts = key.split(":")
    if len(parts) < 3:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None
