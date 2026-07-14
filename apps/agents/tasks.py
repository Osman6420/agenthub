"""Celery agent task; broker messages carry only the authoritative run id.

Mirrors the Sprint 8 workflow task: the message holds no tenant data, the run is
claimed under ``select_for_update`` with ``acks_late`` so a crash re-delivers it, a
terminal run is an idempotent no-op, a missing run is a safe no-op (a stale broker
message must never resurrect state), and a pause raises ``AgentPaused`` leaving the
durable ``waiting_approval`` checkpoint untouched for the approval-driven resume.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.agents.models import (
    TERMINAL_RUN_STATUSES,
    AgentRun,
    AgentRunEvent,
    AgentRunStatus,
)
from apps.agents.runtime import AgentPaused, AgentRuntimeError, execute_agent
from apps.agents.services import _next_sequence
from apps.artifacts.validation import compute_checksum
from apps.tenancy.context import set_tenant_context

logger = logging.getLogger(__name__)

_CLAIMABLE = frozenset(
    {
        AgentRunStatus.QUEUED,
        AgentRunStatus.REQUESTED,
        AgentRunStatus.WAITING_APPROVAL,
    }
)


@shared_task(queue="runtime", acks_late=True)
def execute_agent_run(run_id: int, organization_id: int | None = None) -> str:
    if organization_id is None:
        organization_id = (
            AgentRun.objects.filter(pk=run_id).values_list("organization_id", flat=True).first()
        )
        if organization_id is None:
            logger.warning(
                "agent task ignored because run does not exist", extra={"run_id": run_id}
            )
            return "missing"
    try:
        with transaction.atomic():
            set_tenant_context(organization_id)
            run = (
                AgentRun.objects.select_for_update()
                .select_related("agent_version", "release")
                .get(pk=run_id, organization_id=organization_id)
            )
            if run.status in TERMINAL_RUN_STATUSES:
                return str(run.status)
            if run.status not in _CLAIMABLE:
                return str(run.status)
            resuming = run.status == AgentRunStatus.WAITING_APPROVAL
            run.status = AgentRunStatus.RUNNING
            if run.started_at is None:
                run.started_at = timezone.now()
            run.save(update_fields=["status", "started_at", "updated_at"])
            AgentRunEvent.objects.create(
                run=run,
                sequence=_next_sequence(run),
                event_type="run_resumed" if resuming else "run_started",
                outcome="running",
            )
    except AgentRun.DoesNotExist:
        # Stale/redelivered broker messages can outlive a rolled-back or ephemeral
        # database. They carry no tenant data and must be an idempotent safe no-op.
        logger.warning("agent task ignored because run does not exist", extra={"run_id": run_id})
        return "missing"

    try:
        with transaction.atomic():
            set_tenant_context(organization_id)
            try:
                result = execute_agent(run=run)
            except AgentPaused:
                # Commit the durable waiting checkpoint before acknowledging the task.
                return str(AgentRunStatus.WAITING_APPROVAL)
    except AgentRuntimeError as exc:
        return _finish_error(run_id, organization_id, exc.code)

    with transaction.atomic():
        set_tenant_context(organization_id)
        run = AgentRun.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
        if run.status == AgentRunStatus.CANCELLED:
            return str(run.status)
        final_state = dict(result.state)
        run.checkpoint = final_state
        run.step_count = result.steps
        run.tool_call_count = result.tool_calls
        run.input_tokens = result.input_tokens
        run.output_tokens = result.output_tokens
        run.awaiting_step = None
        run.awaiting_role = ""
        run.status = AgentRunStatus.COMPLETED
        run.finished_at = timezone.now()
        run.save(
            update_fields=[
                "checkpoint",
                "step_count",
                "tool_call_count",
                "input_tokens",
                "output_tokens",
                "awaiting_step",
                "awaiting_role",
                "status",
                "finished_at",
                "updated_at",
            ]
        )
        AgentRunEvent.objects.create(
            run=run,
            sequence=_next_sequence(run),
            event_type="run_completed",
            outcome="completed",
            state_checksum=compute_checksum(final_state),
        )
    return str(AgentRunStatus.COMPLETED)


def _finish_error(run_id: int, organization_id: int, code: str) -> str:
    with transaction.atomic():
        set_tenant_context(organization_id)
        run = AgentRun.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
        if run.status == AgentRunStatus.CANCELLED:
            return str(run.status)
        status = AgentRunStatus.TIMED_OUT if code == "AGENT_TIMED_OUT" else AgentRunStatus.FAILED
        run.status = status
        run.error_code = code
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
        AgentRunEvent.objects.create(
            run=run,
            sequence=_next_sequence(run),
            event_type="run_failed",
            outcome=str(status),
            reason_code=code,
        )
    return str(status)
