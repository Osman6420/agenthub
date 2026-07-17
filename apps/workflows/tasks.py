"""Celery workflow task; messages carry only the authoritative run id."""

from __future__ import annotations

import logging
from functools import partial

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.tenancy.context import set_tenant_context
from apps.workflows.models import WorkflowBranch, WorkflowRun, WorkflowRunEvent, WorkflowRunStatus
from apps.workflows.runtime import (
    WorkflowParallelPending,
    WorkflowPaused,
    WorkflowRetryPending,
    WorkflowRuntimeError,
    execute_branch_path,
    execute_graph,
)
from apps.workflows.services import _next_sequence
from apps.workflows.waits import reconcile_due_waits

logger = logging.getLogger(__name__)


def _dispatch_branches(branch_ids: tuple[int, ...], organization_id: int) -> None:
    for branch_id in branch_ids:
        execute_workflow_branch.delay(branch_id, organization_id)


def _dispatch_retry(run_id: int, organization_id: int, countdown_seconds: int) -> None:
    execute_workflow_run.apply_async(args=(run_id, organization_id), countdown=countdown_seconds)


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
                WorkflowRunStatus.WAITING_EVENT,
                WorkflowRunStatus.WAITING_HUMAN,
                WorkflowRunStatus.WAITING_TIMER,
                WorkflowRunStatus.WAITING_CHILD,
            } and not (run.status == WorkflowRunStatus.RUNNING and run.awaiting_node):
                return str(run.status)
            resuming = run.status in {
                WorkflowRunStatus.WAITING_APPROVAL,
                WorkflowRunStatus.WAITING_EVENT,
                WorkflowRunStatus.WAITING_HUMAN,
                WorkflowRunStatus.WAITING_TIMER,
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
                # Commit the durable waiting checkpoint before acknowledging the task.
                return str(run.status)
            except WorkflowParallelPending as pending:
                if pending.branch_ids:
                    branch_ids = tuple(pending.branch_ids)
                    transaction.on_commit(partial(_dispatch_branches, branch_ids, organization_id))
                return "parallel_pending"
            except WorkflowRetryPending as pending:
                transaction.on_commit(
                    partial(_dispatch_retry, run_id, organization_id, pending.countdown_seconds)
                )
                return "retry_pending"
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


@shared_task(queue="runtime", acks_late=True)
def execute_workflow_branch(branch_id: int, organization_id: int) -> str:
    """Execute a server-owned branch locator under freshly installed tenant context."""
    from apps.workflows.parallel import claim_branch, complete_branch

    try:
        claim = claim_branch(organization_id=organization_id, branch_id=branch_id)
        if claim != "claimed":
            return claim
        with transaction.atomic():
            set_tenant_context(organization_id)
            branch = WorkflowBranch.objects.select_related(
                "run__workflow_version", "run__release", "run__consumer"
            ).get(pk=branch_id, organization_id=organization_id)
            result = execute_branch_path(branch=branch)
        transition = complete_branch(
            organization_id=organization_id,
            branch_id=branch_id,
            idempotency_key=f"branch:{branch_id}:attempt:{branch.attempt_count}",
            result_state=result,
        )
    except (WorkflowBranch.DoesNotExist, WorkflowRun.DoesNotExist):
        return "missing"
    except WorkflowRuntimeError as exc:
        transition = complete_branch(
            organization_id=organization_id,
            branch_id=branch_id,
            idempotency_key=f"branch:{branch_id}:failed",
            reason_code=exc.code,
        )
    if transition.join_status in {"succeeded", "failed"}:
        execute_workflow_run.delay(branch.run_id, organization_id)
    return transition.outcome


@shared_task(queue="runtime", acks_late=True)
def reconcile_workflow_waits(limit: int = 100) -> int:
    """Wake due durable waits without holding a worker for their delay."""
    run_ids = reconcile_due_waits(limit=limit)
    for run_id in run_ids:
        organization_id = (
            WorkflowRun.objects.filter(pk=run_id).values_list("organization_id", flat=True).first()
        )
        if organization_id is not None:
            execute_workflow_run.delay(run_id, organization_id)
    return len(run_ids)
