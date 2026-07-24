"""Locked state transitions for the unified workflow Run aggregate."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    RunEvent,
    RunEventType,
    RunExecutionMode,
    WorkflowRunStatus,
)
from apps.workflows.run_events import append_locked_run_event

MAX_CHECKPOINT_BYTES = 1_048_576
MAX_COUNTER_VALUE = 2_147_483_647
MAX_SYNC_LEASE_SECONDS = 60
_CANCELLATION_REASON_CODES = frozenset(
    {
        "CLIENT_DISCONNECTED",
        "CLIENT_REQUESTED",
        "DEADLINE_EXPIRED",
        "OPERATOR_REQUESTED",
    }
)
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
        WorkflowRunStatus.RECOVERY_REQUIRED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.CANCELLED,
    },
    WorkflowRunStatus.QUEUED: {
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.RECOVERY_REQUIRED,
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


def _transition_checksum(
    *,
    expected_checkpoint_version: int,
    expected_status: str | None,
    target_status: str,
    checkpoint: dict[str, Any] | None,
    awaiting_reference: str,
    reason_code: str,
    error_code: str,
    deltas: tuple[int, int, int, int],
) -> str:
    return compute_checksum(
        {
            "awaiting_reference": awaiting_reference,
            "checkpoint": checkpoint,
            "deltas": list(deltas),
            "error_code": error_code,
            "expected_checkpoint_version": expected_checkpoint_version,
            "expected_status": expected_status,
            "reason_code": reason_code,
            "target_status": target_status,
        }
    )


def _replayed_transition(event: RunEvent, checksum: str) -> RunTransitionResult:
    if event.transition_checksum != checksum:
        raise RunTransitionError("RUN_TRANSITION_TOKEN_CONFLICT")
    return RunTransitionResult(
        str(event.payload["result_outcome"]),
        str(event.payload["current_status"]),
        int(event.payload["checkpoint_version"]),
        event.sequence,
    )


@transaction.atomic
def transition_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    transition_token: uuid.UUID,
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
    if not isinstance(transition_token, uuid.UUID):
        raise RunTransitionError("RUN_TRANSITION_TOKEN_INVALID")
    transition_checksum = _transition_checksum(
        expected_checkpoint_version=expected_checkpoint_version,
        expected_status=expected_status,
        target_status=str(target),
        checkpoint=clean_checkpoint,
        awaiting_reference=awaiting_reference,
        reason_code=reason_code,
        error_code=error_code,
        deltas=deltas,
    )
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(
        pk=run_id,
        organization_id=organization_id,
    )
    replay = run.events.filter(transition_token=transition_token).first()
    if replay is not None:
        return _replayed_transition(replay, transition_checksum)
    if run.status in WORKFLOW_TERMINAL_STATUSES:
        event = append_locked_run_event(
            run=run,
            event_type=RunEventType.LATE_RESULT_DISCARDED,
            outcome="discarded",
            reason_code="RUN_TERMINAL",
            payload={
                "checkpoint_version": run.checkpoint_version,
                "current_status": str(run.status),
                "result_outcome": "terminal",
            },
            transition_token=transition_token,
            transition_checksum=transition_checksum,
        )
        run.save(update_fields=["next_event_sequence", "updated_at"])
        return RunTransitionResult(
            "terminal",
            str(run.status),
            run.checkpoint_version,
            event.sequence,
        )
    if run.checkpoint_version != expected_checkpoint_version or (
        expected_status is not None and run.status != expected_status
    ):
        event = append_locked_run_event(
            run=run,
            event_type=RunEventType.LATE_RESULT_DISCARDED,
            outcome="discarded",
            reason_code="RUN_TRANSITION_STALE",
            payload={
                "checkpoint_version": run.checkpoint_version,
                "current_status": str(run.status),
                "result_outcome": "stale",
            },
            transition_token=transition_token,
            transition_checksum=transition_checksum,
        )
        run.save(update_fields=["next_event_sequence", "updated_at"])
        return RunTransitionResult(
            "stale",
            str(run.status),
            run.checkpoint_version,
            event.sequence,
        )
    if run.cancellation_state == RunCancellationState.REQUESTED and target not in {
        WorkflowRunStatus.CANCELLED,
        WorkflowRunStatus.RECOVERY_REQUIRED,
    }:
        target = WorkflowRunStatus.CANCELLED
        awaiting_reference = ""
        reason_code = "RUN_CANCELLATION_REQUESTED"
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
    elif target == WorkflowRunStatus.RECOVERY_REQUIRED:
        run.sync_lease_token = None
        run.sync_lease_expires_at = None

    event = append_locked_run_event(
        run=run,
        event_type=_event_for_transition(previous_status, target),
        outcome=str(target),
        reason_code=reason_code or error_code,
        state_checksum=compute_checksum(run.redacted_state),
        payload={
            "checkpoint_version": run.checkpoint_version,
            "current_status": str(run.status),
            "previous_status": str(previous_status),
            "result_outcome": "committed",
        },
        transition_token=transition_token,
        transition_checksum=transition_checksum,
    )
    run.save()
    return RunTransitionResult(
        "committed",
        str(run.status),
        run.checkpoint_version,
        event.sequence,
    )


@transaction.atomic
def renew_sync_lease(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    lease_token: uuid.UUID,
    expires_at: datetime,
) -> None:
    """Acquire or renew the exact bounded lease for a non-terminal synchronous run."""

    now = timezone.now()
    if (
        not isinstance(lease_token, uuid.UUID)
        or not isinstance(expires_at, datetime)
        or not timezone.is_aware(expires_at)
        or expires_at <= now
        or expires_at > now + timedelta(seconds=MAX_SYNC_LEASE_SECONDS)
    ):
        raise RunTransitionError("RUN_SYNC_LEASE_INVALID")
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    if run.execution_mode != RunExecutionMode.SYNC or run.status in WORKFLOW_TERMINAL_STATUSES:
        raise RunTransitionError("RUN_SYNC_LEASE_INVALID")
    if run.deadline_at <= now:
        raise RunTransitionError("RUN_SYNC_LEASE_INVALID")
    if run.cancellation_state != RunCancellationState.NONE:
        raise RunTransitionError("RUN_CANCELLATION_REQUESTED")
    if run.sync_lease_token is not None and run.sync_lease_token != lease_token:
        raise RunTransitionError("RUN_SYNC_LEASE_CONFLICT")
    run.sync_lease_token = lease_token
    run.sync_lease_expires_at = min(expires_at, run.deadline_at)
    run.save(update_fields=["sync_lease_token", "sync_lease_expires_at", "updated_at"])


@transaction.atomic
def request_run_cancellation(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    reason_code: str,
) -> RunTransitionResult:
    """Record one cooperative cancellation request without reopening terminal runs."""

    if reason_code not in _CANCELLATION_REASON_CODES:
        raise RunTransitionError("RUN_REASON_CODE_INVALID")
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    if run.status in WORKFLOW_TERMINAL_STATUSES:
        return RunTransitionResult("terminal", str(run.status), run.checkpoint_version, None)
    existing = run.events.filter(event_type=RunEventType.CANCELLATION_REQUESTED).first()
    if run.cancellation_state == RunCancellationState.REQUESTED:
        if existing is None:
            raise RunTransitionError("RUN_CANCELLATION_STATE_INVALID")
        return RunTransitionResult(
            "replayed",
            str(run.status),
            run.checkpoint_version,
            existing.sequence,
        )
    run.cancellation_state = RunCancellationState.REQUESTED
    run.cancellation_requested_at = timezone.now()
    run.cancellation_reason_code = reason_code
    event = append_locked_run_event(
        run=run,
        event_type=RunEventType.CANCELLATION_REQUESTED,
        outcome="requested",
        reason_code=reason_code,
        payload={"current_status": str(run.status)},
    )
    run.save()
    return RunTransitionResult("committed", str(run.status), run.checkpoint_version, event.sequence)


@transaction.atomic
def resolve_expired_sync_lease(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    lease_token: uuid.UUID,
    transition_token: uuid.UUID,
    observed_at: datetime | None = None,
) -> RunTransitionResult:
    """Resolve an expired sync owner without transferring execution to a worker."""

    now = observed_at or timezone.now()
    if not isinstance(now, datetime) or not timezone.is_aware(now):
        raise RunTransitionError("RUN_SYNC_LEASE_INVALID")
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    if run.status in WORKFLOW_TERMINAL_STATUSES:
        return RunTransitionResult("terminal", str(run.status), run.checkpoint_version, None)
    if run.sync_lease_token != lease_token:
        raise RunTransitionError("RUN_SYNC_LEASE_CONFLICT")
    if run.sync_lease_expires_at is None or run.sync_lease_expires_at > now:
        raise RunTransitionError("RUN_SYNC_LEASE_ACTIVE")
    cancellation_requested = run.cancellation_state == RunCancellationState.REQUESTED
    return transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=transition_token,
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=str(run.status),
        target_status=(
            WorkflowRunStatus.CANCELLED
            if cancellation_requested
            else WorkflowRunStatus.RECOVERY_REQUIRED
        ),
        awaiting_reference="" if cancellation_requested else "sync-lease-expired",
        reason_code=(
            "RUN_CANCELLATION_REQUESTED" if cancellation_requested else "RUN_SYNC_LEASE_EXPIRED"
        ),
    )
