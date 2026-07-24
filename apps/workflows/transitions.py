"""Locked state transitions for the unified workflow Run aggregate."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.tenancy.context import set_tenant_context
from apps.workflows.models import (
    WORKFLOW_TERMINAL_STATUSES,
    Run,
    RunAwaitingKind,
    RunCancellationState,
    RunEventType,
    WorkflowRunStatus,
)
from apps.workflows.run_events import append_locked_run_event

MAX_CHECKPOINT_BYTES = 1_048_576
MAX_COUNTER_VALUE = 2_147_483_647
_WAITING_KIND_BY_STATUS = {
    WorkflowRunStatus.WAITING_APPROVAL: RunAwaitingKind.APPROVAL,
    WorkflowRunStatus.WAITING_EVENT: RunAwaitingKind.EVENT,
    WorkflowRunStatus.WAITING_HUMAN: RunAwaitingKind.HUMAN,
    WorkflowRunStatus.WAITING_TIMER: RunAwaitingKind.TIMER,
    WorkflowRunStatus.WAITING_CHILD: RunAwaitingKind.CHILD,
    WorkflowRunStatus.RECOVERY_REQUIRED: RunAwaitingKind.RECOVERY,
}
_ALLOWED_TRANSITIONS = {
    WorkflowRunStatus.REQUESTED: {
        WorkflowRunStatus.QUEUED,
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.CANCELLED,
    },
    WorkflowRunStatus.QUEUED: {
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.CANCELLED,
    },
    WorkflowRunStatus.RUNNING: {
        *_WAITING_KIND_BY_STATUS,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.CANCELLED,
    },
    **{
        waiting_status: {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.TIMED_OUT,
            WorkflowRunStatus.CANCELLED,
        }
        for waiting_status in _WAITING_KIND_BY_STATUS
    },
}
_EVENT_BY_TARGET = {
    WorkflowRunStatus.QUEUED: RunEventType.QUEUED,
    WorkflowRunStatus.COMPLETED: RunEventType.COMPLETED,
    WorkflowRunStatus.FAILED: RunEventType.FAILED,
    WorkflowRunStatus.TIMED_OUT: RunEventType.TIMED_OUT,
    WorkflowRunStatus.CANCELLED: RunEventType.CANCELLED,
    WorkflowRunStatus.RECOVERY_REQUIRED: RunEventType.RECOVERY_REQUIRED,
}


class RunTransitionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RunTransitionResult:
    outcome: str
    status: str
    checkpoint_version: int
    event_sequence: int | None


def _validate_checkpoint(checkpoint: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(checkpoint, dict):
        raise RunTransitionError("RUN_CHECKPOINT_INVALID")
    try:
        encoded = json.dumps(
            checkpoint,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise RunTransitionError("RUN_CHECKPOINT_INVALID") from None
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise RunTransitionError("RUN_CHECKPOINT_TOO_LARGE")
    return dict(checkpoint)


def _event_for_transition(
    previous_status: WorkflowRunStatus, target_status: WorkflowRunStatus
) -> str:
    if target_status == WorkflowRunStatus.RUNNING:
        return (
            RunEventType.RESUMED
            if previous_status in _WAITING_KIND_BY_STATUS
            else RunEventType.STARTED
        )
    if target_status in _WAITING_KIND_BY_STATUS:
        return RunEventType.WAITING
    return _EVENT_BY_TARGET[target_status]


@transaction.atomic
def transition_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    expected_checkpoint_version: int,
    target_status: str,
    expected_status: str | None = None,
    checkpoint: dict[str, Any] | None = None,
    awaiting_reference: str = "",
    reason_code: str = "",
    error_code: str = "",
    step_delta: int = 0,
    tool_call_delta: int = 0,
    input_token_delta: int = 0,
    output_token_delta: int = 0,
) -> RunTransitionResult:
    """Commit one legal transition or safely record a stale/terminal late result."""

    deltas = (step_delta, tool_call_delta, input_token_delta, output_token_delta)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in deltas):
        raise RunTransitionError("RUN_COUNTER_DELTA_INVALID")
    if len(awaiting_reference) > 200:
        raise RunTransitionError("RUN_AWAITING_REFERENCE_INVALID")
    if len(reason_code) > 64 or len(error_code) > 64:
        raise RunTransitionError("RUN_REASON_CODE_INVALID")
    try:
        target = WorkflowRunStatus(target_status)
    except ValueError:
        raise RunTransitionError("RUN_TRANSITION_INVALID") from None
    clean_checkpoint = _validate_checkpoint(checkpoint) if checkpoint is not None else None
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(
        pk=run_id,
        organization_id=organization_id,
    )
    if run.status in WORKFLOW_TERMINAL_STATUSES:
        event = append_locked_run_event(
            run=run,
            event_type=RunEventType.LATE_RESULT_DISCARDED,
            outcome="discarded",
            reason_code="RUN_TERMINAL",
            payload={"current_status": str(run.status)},
        )
        run.save(update_fields=["next_event_sequence", "updated_at"])
        return RunTransitionResult(
            "terminal",
            str(run.status),
            run.checkpoint_version,
            event.sequence,
        )
    if (
        run.checkpoint_version != expected_checkpoint_version
        or (expected_status is not None and run.status != expected_status)
    ):
        event = append_locked_run_event(
            run=run,
            event_type=RunEventType.LATE_RESULT_DISCARDED,
            outcome="discarded",
            reason_code="RUN_TRANSITION_STALE",
            payload={"current_status": str(run.status)},
        )
        run.save(update_fields=["next_event_sequence", "updated_at"])
        return RunTransitionResult(
            "stale",
            str(run.status),
            run.checkpoint_version,
            event.sequence,
        )
    current = WorkflowRunStatus(run.status)
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise RunTransitionError("RUN_TRANSITION_INVALID")

    awaiting_kind = _WAITING_KIND_BY_STATUS.get(target, "")
    if bool(awaiting_kind) != bool(awaiting_reference):
        raise RunTransitionError("RUN_AWAITING_REFERENCE_INVALID")

    previous_status = current
    run.status = target
    run.awaiting_kind = awaiting_kind
    run.awaiting_reference = awaiting_reference
    run.reason_code = reason_code
    run.error_code = error_code
    run.checkpoint_version += 1
    if clean_checkpoint is not None:
        run.checkpoint = clean_checkpoint
        run.redacted_state = clean_checkpoint
    run.step_count += step_delta
    run.tool_call_count += tool_call_delta
    run.input_token_count += input_token_delta
    run.output_token_count += output_token_delta
    if any(
        value > MAX_COUNTER_VALUE
        for value in (
            run.step_count,
            run.tool_call_count,
            run.input_token_count,
            run.output_token_count,
        )
    ):
        raise RunTransitionError("RUN_COUNTER_LIMIT_EXCEEDED")

    now = timezone.now()
    if target == WorkflowRunStatus.RUNNING and run.started_at is None:
        run.started_at = now
    if target in WORKFLOW_TERMINAL_STATUSES:
        run.finished_at = now
        run.sync_lease_token = None
        run.sync_lease_expires_at = None
        if target == WorkflowRunStatus.CANCELLED:
            run.cancellation_state = RunCancellationState.ACKNOWLEDGED

    event = append_locked_run_event(
        run=run,
        event_type=_event_for_transition(previous_status, target),
        outcome=str(target),
        reason_code=reason_code or error_code,
        state_checksum=compute_checksum(run.redacted_state),
        payload={
            "checkpoint_version": run.checkpoint_version,
            "previous_status": str(previous_status),
        },
    )
    run.save()
    return RunTransitionResult(
        "committed",
        str(run.status),
        run.checkpoint_version,
        event.sequence,
    )
