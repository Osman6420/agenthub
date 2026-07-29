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
    RUN_TERMINAL_STATUSES,
    Run,
    RunAwaitingKind,
    RunCancellationState,
    RunEvent,
    RunEventType,
    RunExecutionMode,
    RunStatus,
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
    RunStatus.WAITING_APPROVAL: RunAwaitingKind.APPROVAL,
    RunStatus.WAITING_EVENT: RunAwaitingKind.EVENT,
    RunStatus.WAITING_HUMAN: RunAwaitingKind.HUMAN,
    RunStatus.WAITING_TIMER: RunAwaitingKind.TIMER,
    RunStatus.WAITING_CHILD: RunAwaitingKind.CHILD,
    RunStatus.RECOVERY_REQUIRED: RunAwaitingKind.RECOVERY,
}
# A durable wait has no background owner, so an external resume signal may re-admit it.
# `recovery_required` is deliberately excluded: it is never automatically re-queued.
DURABLE_WAIT_STATUSES = frozenset(
    {
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_EVENT,
        RunStatus.WAITING_HUMAN,
        RunStatus.WAITING_TIMER,
        RunStatus.WAITING_CHILD,
    }
)
# An unowned durable wait may be re-queued or closed, but never executed directly: reaching
# `running` always requires a fresh background claim.
_UNOWNED_WAIT_TARGETS = frozenset(
    {
        RunStatus.QUEUED,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
    }
)
_ALLOWED_TRANSITIONS = {
    RunStatus.REQUESTED: {
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.RECOVERY_REQUIRED,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
    },
    RunStatus.QUEUED: {
        RunStatus.RUNNING,
        RunStatus.RECOVERY_REQUIRED,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
    },
    RunStatus.RUNNING: {
        *_WAITING_KIND_BY_STATUS,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
    },
    **{
        waiting_status: {
            RunStatus.RUNNING,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
            *({RunStatus.QUEUED} if waiting_status in DURABLE_WAIT_STATUSES else set()),
        }
        for waiting_status in _WAITING_KIND_BY_STATUS
    },
}
_EVENT_BY_TARGET = {
    RunStatus.QUEUED: RunEventType.QUEUED,
    RunStatus.COMPLETED: RunEventType.COMPLETED,
    RunStatus.FAILED: RunEventType.FAILED,
    RunStatus.TIMED_OUT: RunEventType.TIMED_OUT,
    RunStatus.CANCELLED: RunEventType.CANCELLED,
    RunStatus.RECOVERY_REQUIRED: RunEventType.RECOVERY_REQUIRED,
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


def _event_for_transition(previous_status: RunStatus, target_status: RunStatus) -> str:
    if target_status == RunStatus.RUNNING:
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
    background_claim_token: uuid.UUID | None,
    sync_lease_token: uuid.UUID | None,
) -> str:
    content: dict[str, Any] = {
        "awaiting_reference": awaiting_reference,
        "checkpoint": checkpoint,
        "deltas": list(deltas),
        "error_code": error_code,
        "expected_checkpoint_version": expected_checkpoint_version,
        "expected_status": expected_status,
        "reason_code": reason_code,
        "target_status": target_status,
    }
    if background_claim_token is not None:
        content["background_claim_token"] = str(background_claim_token)
    if sync_lease_token is not None:
        content["sync_lease_token"] = str(sync_lease_token)
    return compute_checksum(content)


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
    background_claim_token: uuid.UUID | None = None,
    sync_lease_token: uuid.UUID | None = None,
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
        target = RunStatus(target_status)
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
        background_claim_token=background_claim_token,
        sync_lease_token=sync_lease_token,
    )
    set_tenant_context(organization_id)
    run = (
        Run.objects.select_for_update()
        .select_related("scenario")
        .get(
            pk=run_id,
            organization_id=organization_id,
        )
    )
    replay = run.events.filter(transition_token=transition_token).first()
    if replay is not None:
        return _replayed_transition(replay, transition_checksum)
    if run.status in RUN_TERMINAL_STATUSES:
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
    transition_now = timezone.now()
    admission_queue = (
        run.status == RunStatus.REQUESTED
        and target == RunStatus.QUEUED
        and background_claim_token is None
    )
    guard_convergence = background_claim_token is None and (
        (run.cancellation_state == RunCancellationState.REQUESTED and target == RunStatus.CANCELLED)
        or (transition_now >= run.deadline_at and target == RunStatus.TIMED_OUT)
    )
    # A durable wait released its claim at suspension, so there is no owner to displace and a
    # resume/expiry signal cannot prove one. Ownership proof stays mandatory everywhere else.
    unowned_wait = (
        background_claim_token is None
        and run.background_claim_token is None
        and run.status in DURABLE_WAIT_STATUSES
        and target in _UNOWNED_WAIT_TARGETS
    )
    expired_sync_recovery = (
        run.execution_mode == RunExecutionMode.SYNC
        and target
        in {
            RunStatus.CANCELLED,
            RunStatus.RECOVERY_REQUIRED,
            RunStatus.TIMED_OUT,
        }
        and run.sync_lease_expires_at is not None
        and run.sync_lease_expires_at <= transition_now
    )
    if (
        run.execution_mode == RunExecutionMode.SYNC
        and run.status != RunStatus.REQUESTED
        and (run.status == RunStatus.QUEUED or run.sync_lease_token is not None)
        and not guard_convergence
        and not expired_sync_recovery
    ):
        if not isinstance(sync_lease_token, uuid.UUID):
            raise RunTransitionError("RUN_SYNC_LEASE_REQUIRED")
        if run.sync_lease_token != sync_lease_token:
            raise RunTransitionError("RUN_SYNC_LEASE_STALE")
        if run.sync_lease_expires_at is None or run.sync_lease_expires_at <= transition_now:
            raise RunTransitionError("RUN_SYNC_LEASE_EXPIRED")
    if (
        run.execution_mode == RunExecutionMode.BACKGROUND
        and not admission_queue
        and not guard_convergence
        and not unowned_wait
    ):
        if not isinstance(background_claim_token, uuid.UUID):
            raise RunTransitionError("RUN_BACKGROUND_CLAIM_REQUIRED")
        if (
            run.background_claim_token != background_claim_token
            or run.background_claim_checkpoint_version != expected_checkpoint_version
        ):
            raise RunTransitionError("RUN_BACKGROUND_CLAIM_STALE")
        claim_may_be_expired = target in {
            RunStatus.CANCELLED,
            RunStatus.RECOVERY_REQUIRED,
            RunStatus.TIMED_OUT,
        }
        if run.background_claim_expires_at is None or (
            run.background_claim_expires_at <= transition_now and not claim_may_be_expired
        ):
            raise RunTransitionError("RUN_BACKGROUND_CLAIM_EXPIRED")
    if target not in {
        RunStatus.CANCELLED,
        RunStatus.RECOVERY_REQUIRED,
        RunStatus.TIMED_OUT,
    }:
        from apps.agents.services import observe_runtime_suspension, runtime_suspended

        if runtime_suspended(
            organization_id,
            project_id=run.scenario.project_id,
            scenario_id=run.scenario_id,
        ):
            observe_runtime_suspension("transition")
            raise RunTransitionError("RUN_RUNTIME_SUSPENDED")
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
        RunStatus.CANCELLED,
        RunStatus.RECOVERY_REQUIRED,
    }:
        target = RunStatus.CANCELLED
        awaiting_reference = ""
        reason_code = "RUN_CANCELLATION_REQUESTED"
    elif transition_now >= run.deadline_at and target not in {
        RunStatus.CANCELLED,
        RunStatus.RECOVERY_REQUIRED,
        RunStatus.TIMED_OUT,
    }:
        target = RunStatus.TIMED_OUT
        awaiting_reference = ""
        reason_code = "RUN_DEADLINE_EXCEEDED"
    current = RunStatus(run.status)
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
        from apps.workflows.services import redact_run_state

        run.checkpoint = clean_checkpoint
        run.redacted_state = redact_run_state(clean_checkpoint)
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

    now = transition_now
    if target == RunStatus.RUNNING and run.started_at is None:
        run.started_at = now
    if target in RUN_TERMINAL_STATUSES:
        run.finished_at = now
        run.sync_lease_token = None
        run.sync_lease_expires_at = None
        run.background_claim_token = None
        run.background_claim_expires_at = None
        run.background_claim_checkpoint_version = None
        if target == RunStatus.CANCELLED:
            run.cancellation_state = RunCancellationState.ACKNOWLEDGED
    elif target == RunStatus.RECOVERY_REQUIRED:
        run.sync_lease_token = None
        run.sync_lease_expires_at = None
        run.background_claim_token = None
        run.background_claim_expires_at = None
        run.background_claim_checkpoint_version = None
    elif run.execution_mode == RunExecutionMode.BACKGROUND:
        if target == RunStatus.RUNNING:
            run.background_claim_checkpoint_version = run.checkpoint_version
        else:
            run.background_claim_token = None
            run.background_claim_expires_at = None
            run.background_claim_checkpoint_version = None

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
    if run.execution_mode != RunExecutionMode.SYNC or run.status in RUN_TERMINAL_STATUSES:
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
    if run.status in RUN_TERMINAL_STATUSES:
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
    if run.status == RunStatus.WAITING_CHILD:
        from apps.workflows.models import RunChildLink, RunChildStatus

        child_link = (
            RunChildLink.objects.select_for_update()
            .filter(parent_run=run, status=RunChildStatus.ADMITTED)
            .first()
        )
        if child_link is not None:
            request_run_cancellation(
                organization_id=organization_id,
                run_id=child_link.child_run_id,
                reason_code=reason_code,
            )
            child_link.status = RunChildStatus.CANCELLED
            child_link.reason_code = "PARENT_CANCELLED"
            child_link.save(update_fields=["status", "reason_code", "updated_at"])
            purpose = "child-cancellation-converged"
        else:
            # A parallel region has no background owner while its parent is parked. Revoke the
            # branch delivery capabilities and converge the unowned wait now.
            from apps.workflows.run_parallel import _cancel_locked_run_parallel_work

            _cancel_locked_run_parallel_work(run=run, now=timezone.now())
            purpose = "parallel-cancellation-converged"
        return transition_run(
            organization_id=organization_id,
            run_id=run.id,
            transition_token=uuid.uuid5(run.id, purpose),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=RunStatus.WAITING_CHILD,
            target_status=RunStatus.CANCELLED,
            reason_code="RUN_CANCELLATION_REQUESTED",
        )
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
    if run.status in RUN_TERMINAL_STATUSES:
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
            RunStatus.CANCELLED if cancellation_requested else RunStatus.RECOVERY_REQUIRED
        ),
        awaiting_reference="" if cancellation_requested else "sync-lease-expired",
        reason_code=(
            "RUN_CANCELLATION_REQUESTED" if cancellation_requested else "RUN_SYNC_LEASE_EXPIRED"
        ),
    )
