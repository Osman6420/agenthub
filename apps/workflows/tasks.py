"""Celery workflow task; messages carry only the authoritative run id."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.tenancy.context import set_tenant_context
from apps.workflows.models import WorkflowRun, WorkflowRunEvent, WorkflowRunStatus
from apps.workflows.runtime import WorkflowPaused, WorkflowRuntimeError, execute_graph
from apps.workflows.services import _next_sequence

logger = logging.getLogger(__name__)


@shared_task(queue="runtime", acks_late=True)
def execute_workflow_run(run_id: int, organization_id: int | None = None) -> str:
    if organization_id is None:
        organization_id = (
            WorkflowRun.objects.filter(pk=run_id).values_list("organization_id", flat=True).first()
        )
        if organization_id is None:
            logger.warning(
                "workflow task ignored because run does not exist", extra={"run_id": run_id}
            )
            return "missing"
    try:
        with transaction.atomic():
            set_tenant_context(organization_id)
            run = (
                WorkflowRun.objects.select_for_update()
                .select_related("workflow_version", "release")
                .get(pk=run_id, organization_id=organization_id)
            )
            if run.status in {
                WorkflowRunStatus.COMPLETED,
                WorkflowRunStatus.FAILED,
                WorkflowRunStatus.TIMED_OUT,
                WorkflowRunStatus.CANCELLED,
            }:
                return str(run.status)
            if run.status not in {
                WorkflowRunStatus.QUEUED,
                WorkflowRunStatus.REQUESTED,
                WorkflowRunStatus.WAITING_APPROVAL,
                WorkflowRunStatus.WAITING_CHILD,
            }:
                return str(run.status)
            resuming = run.status in {
                WorkflowRunStatus.WAITING_APPROVAL,
                WorkflowRunStatus.WAITING_CHILD,
            }
            run.status = WorkflowRunStatus.RUNNING
            if run.started_at is None:
                run.started_at = timezone.now()
            run.save(update_fields=["status", "started_at", "updated_at"])
            WorkflowRunEvent.objects.create(
                run=run,
                sequence=_next_sequence(run),
                event_type="run_resumed" if resuming else "run_started",
                outcome="running",
            )
    except WorkflowRun.DoesNotExist:
        # Stale/redelivered broker messages can outlive a rolled-back or ephemeral
        # database. They carry no tenant data and must be an idempotent safe no-op.
        logger.warning("workflow task ignored because run does not exist", extra={"run_id": run_id})
        return "missing"

    try:
        with transaction.atomic():
            set_tenant_context(organization_id)
            try:
                result = execute_graph(run=run)
            except WorkflowPaused:
                # Commit the durable waiting checkpoint (approval or child) before acknowledging.
                return str(run.status)
    except WorkflowRuntimeError as exc:
        return _finish_error(run_id, organization_id, exc.code)

    with transaction.atomic():
        set_tenant_context(organization_id)
        run = WorkflowRun.objects.select_for_update().get(
            pk=run_id, organization_id=organization_id
        )
        if run.status == WorkflowRunStatus.CANCELLED:
            return str(run.status)
        run.redacted_state = result.state
        run.status = WorkflowRunStatus.COMPLETED
        run.finished_at = timezone.now()
        run.save(update_fields=["redacted_state", "status", "finished_at", "updated_at"])
        node_types = {
            node["id"]: node["type"] for node in run.workflow_version.compiled_graph["nodes"]
        }
        for node_id in result.executed_nodes:
            WorkflowRunEvent.objects.create(
                run=run,
                sequence=_next_sequence(run),
                event_type="node_completed",
                node_id=node_id,
                outcome=node_types.get(node_id, "unknown"),
                state_checksum=compute_checksum(result.state),
            )
        WorkflowRunEvent.objects.create(
            run=run,
            sequence=_next_sequence(run),
            event_type="run_completed",
            outcome="completed",
            state_checksum=compute_checksum(result.state),
        )
    return WorkflowRunStatus.COMPLETED


def _finish_error(run_id: int, organization_id: int, code: str) -> str:
    with transaction.atomic():
        set_tenant_context(organization_id)
        run = WorkflowRun.objects.select_for_update().get(
            pk=run_id, organization_id=organization_id
        )
        if run.status == WorkflowRunStatus.CANCELLED:
            return str(run.status)
        status = (
            WorkflowRunStatus.TIMED_OUT
            if code
            in {"WORKFLOW_TIMED_OUT", "WORKFLOW_NODE_TIMED_OUT", "COMPOSITION_CHILD_TIMED_OUT"}
            else WorkflowRunStatus.FAILED
        )
        run.status = status
        run.error_code = code
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
        WorkflowRunEvent.objects.create(
            run=run,
            sequence=_next_sequence(run),
            event_type="run_failed",
            outcome=str(status),
            reason_code=code,
        )
    return str(status)
