"""Durable, audited P2.6.4 recovery transitions.

Only the runtime may open a case. Admins can resolve an existing exact revision through a fixed
action enum; they cannot create work, select nodes, edit state or request an arbitrary retry.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.tenancy.services import can_admin_org
from apps.workflows.models import (
    WORKFLOW_TERMINAL_STATUSES,
    WorkflowCompensationEntry,
    WorkflowCompensationStatus,
    WorkflowNodeAttempt,
    WorkflowNodeAttemptStatus,
    WorkflowRecoveryApproval,
    WorkflowRecoveryCase,
    WorkflowRecoveryStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from apps.workflows.recovery import FailureClass, classify_failure, retry_decision

RECOVERY_ACTIONS = frozenset(
    {
        "reconcile_confirmed_success",
        "reconcile_confirmed_failure",
        "resume_compensation",
        "terminate_failed",
    }
)


class WorkflowRecoveryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@transaction.atomic
def start_node_attempt(*, run: WorkflowRun, node_id: str) -> WorkflowNodeAttempt:
    locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
    if locked.status in WORKFLOW_TERMINAL_STATUSES:
        raise WorkflowRecoveryError("RECOVERY_RUN_TERMINAL")
    last = (
        WorkflowNodeAttempt.objects.filter(run=locked, node_id=node_id).order_by("-ordinal").first()
    )
    if last is not None and last.status == WorkflowNodeAttemptStatus.RUNNING:
        return last
    ordinal = 1 if last is None else last.ordinal + 1
    return WorkflowNodeAttempt.objects.create(
        organization_id=locked.organization_id,
        run=locked,
        node_id=node_id,
        ordinal=ordinal,
        state_checksum=compute_checksum(locked.redacted_state),
    )


@transaction.atomic
def complete_node_attempt(*, attempt: WorkflowNodeAttempt) -> None:
    locked = WorkflowNodeAttempt.objects.select_for_update().get(pk=attempt.pk)
    if locked.status == WorkflowNodeAttemptStatus.SUCCEEDED:
        return
    if locked.status not in {
        WorkflowNodeAttemptStatus.RUNNING,
        WorkflowNodeAttemptStatus.RETRY_WAIT,
    }:
        raise WorkflowRecoveryError("RECOVERY_ATTEMPT_TERMINAL")
    locked.status = WorkflowNodeAttemptStatus.SUCCEEDED
    locked.finished_at = timezone.now()
    locked.save(update_fields=["status", "finished_at", "updated_at"])


@transaction.atomic
def fail_node_attempt(
    *, attempt: WorkflowNodeAttempt, code: str, retry_policy: dict[str, Any] | None
) -> tuple[FailureClass, bool, int]:
    locked = WorkflowNodeAttempt.objects.select_for_update().get(pk=attempt.pk)
    failure_class = classify_failure(code)
    decision = retry_decision(
        policy=retry_policy, failure_class=failure_class, completed_attempts=locked.ordinal
    )
    locked.failure_class = failure_class
    locked.reason_code = code[:64]
    locked.finished_at = timezone.now()
    if decision.allowed:
        locked.status = WorkflowNodeAttemptStatus.RETRY_WAIT
        locked.retry_not_before = timezone.now() + timedelta(seconds=decision.countdown_seconds)
    else:
        locked.status = WorkflowNodeAttemptStatus.FAILED
    locked.save(
        update_fields=[
            "failure_class",
            "reason_code",
            "finished_at",
            "status",
            "retry_not_before",
            "updated_at",
        ]
    )
    return failure_class, decision.allowed, decision.countdown_seconds


@transaction.atomic
def push_compensation(*, run: WorkflowRun, source_node_id: str, compensation_node_id: str) -> None:
    if WorkflowCompensationEntry.objects.filter(run=run, source_node_id=source_node_id).exists():
        return
    last = WorkflowCompensationEntry.objects.filter(run=run).order_by("-sequence").first()
    WorkflowCompensationEntry.objects.create(
        organization_id=run.organization_id,
        run=run,
        sequence=1 if last is None else last.sequence + 1,
        source_node_id=source_node_id,
        compensation_node_id=compensation_node_id,
        input_checksum=compute_checksum(run.redacted_state),
    )


@transaction.atomic
def mark_compensation(
    *, entry: WorkflowCompensationEntry, status: str, reason_code: str = ""
) -> None:
    locked = WorkflowCompensationEntry.objects.select_for_update().get(pk=entry.pk)
    if locked.status in {
        WorkflowCompensationStatus.SUCCEEDED,
        WorkflowCompensationStatus.CANCELLED,
    }:
        return
    locked.status = status
    locked.reason_code = reason_code[:64]
    locked.attempt_count += 1
    if status in {WorkflowCompensationStatus.SUCCEEDED, WorkflowCompensationStatus.BLOCKED}:
        locked.finished_at = timezone.now()
    locked.save(
        update_fields=[
            "status",
            "reason_code",
            "attempt_count",
            "finished_at",
            "updated_at",
        ]
    )


@transaction.atomic
def open_recovery_case(
    *, run: WorkflowRun, node_id: str, failure_class: str, reason_code: str, high_risk: bool
) -> WorkflowRecoveryCase:
    """System-only idempotent case creation over safe metadata."""
    locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
    if locked.status in WORKFLOW_TERMINAL_STATUSES:
        raise WorkflowRecoveryError("RECOVERY_RUN_TERMINAL")
    existing = (
        WorkflowRecoveryCase.objects.select_for_update()
        .filter(run=locked, node_id=node_id, status__in=["open", "awaiting_second_approval"])
        .first()
    )
    if existing is not None:
        return existing
    previous = (
        WorkflowRecoveryCase.objects.filter(run=locked, node_id=node_id)
        .order_by("-revision")
        .first()
    )
    state_checksum = compute_checksum(locked.redacted_state)
    case = WorkflowRecoveryCase.objects.create(
        organization_id=locked.organization_id,
        run=locked,
        node_id=node_id,
        failure_class=failure_class,
        reason_code=reason_code[:64],
        state_checksum=state_checksum,
        high_risk=high_risk,
        required_approvals=1,
        revision=1 if previous is None else previous.revision + 1,
    )
    locked.status = WorkflowRunStatus.RECOVERY_REQUIRED
    locked.awaiting_node = node_id
    locked.save(update_fields=["status", "awaiting_node", "updated_at"])
    record_event(
        actor_type=ActorType.SYSTEM,
        actor_id="workflow-runtime",
        action="workflow.recovery_opened",
        outcome=Outcome.SUCCESS,
        organization_id=locked.organization_id,
        resource_type="workflow_recovery_case",
        resource_id=str(case.public_id),
        reason=reason_code[:64],
        after={"failure_class": failure_class, "revision": case.revision},
    )
    return case


def decide_recovery_case(
    *,
    recovery_public_id: Any,
    actor: Any,
    action: str,
    reason: str,
    expected_revision: int,
    expected_state_checksum: str,
) -> WorkflowRecoveryCase:
    """Authorize outside the mutation transaction so denial audit is never rolled back."""
    case = WorkflowRecoveryCase.objects.filter(public_id=recovery_public_id).first()
    actor_id = getattr(actor, "pk", None)
    if case is None:
        raise WorkflowRecoveryError("RECOVERY_NOT_FOUND")
    if actor_id is None or not can_admin_org(actor, case.organization_id):
        record_event(
            actor_type=ActorType.USER,
            actor_id=str(actor_id or "anonymous"),
            action="workflow.recovery_decide",
            outcome=Outcome.DENY,
            organization_id=case.organization_id,
            resource_type="workflow_recovery_case",
            resource_id=str(case.public_id),
            reason="RECOVERY_AUTHORIZATION_DENIED",
        )
        raise WorkflowRecoveryError("RECOVERY_AUTHORIZATION_DENIED")
    return _decide_recovery_case_authorized(
        recovery_public_id=recovery_public_id,
        actor=actor,
        action=action,
        reason=reason,
        expected_revision=expected_revision,
        expected_state_checksum=expected_state_checksum,
    )


@transaction.atomic
def _decide_recovery_case_authorized(
    *,
    recovery_public_id: Any,
    actor: Any,
    action: str,
    reason: str,
    expected_revision: int,
    expected_state_checksum: str,
) -> WorkflowRecoveryCase:
    """Record one authorized decision; never directly executes a tool or arbitrary node."""
    case = (
        WorkflowRecoveryCase.objects.select_for_update()
        .select_related("run")
        .filter(public_id=recovery_public_id)
        .first()
    )
    if case is None:
        raise WorkflowRecoveryError("RECOVERY_NOT_FOUND")
    actor_id = getattr(actor, "pk", None)
    if actor_id is None or not can_admin_org(actor, case.organization_id):
        record_event(
            actor_type=ActorType.USER,
            actor_id=str(actor_id or "anonymous"),
            action="workflow.recovery_decide",
            outcome=Outcome.DENY,
            organization_id=case.organization_id,
            resource_type="workflow_recovery_case",
            resource_id=str(case.public_id),
            reason="RECOVERY_AUTHORIZATION_DENIED",
        )
        raise WorkflowRecoveryError("RECOVERY_AUTHORIZATION_DENIED")
    if action not in RECOVERY_ACTIONS:
        raise WorkflowRecoveryError("RECOVERY_ACTION_INVALID")
    if action in {"reconcile_confirmed_success", "reconcile_confirmed_failure"} and (
        case.failure_class != "outcome_unknown"
    ):
        raise WorkflowRecoveryError("RECOVERY_ACTION_WRONG_STATE")
    if (
        action == "resume_compensation"
        and not case.run.compensation_entries.filter(
            status__in=[WorkflowCompensationStatus.PENDING, WorkflowCompensationStatus.BLOCKED]
        ).exists()
    ):
        raise WorkflowRecoveryError("RECOVERY_ACTION_WRONG_STATE")
    clean_reason = reason.strip()
    if not 3 <= len(clean_reason) <= 200:
        raise WorkflowRecoveryError("RECOVERY_REASON_INVALID")
    if (
        case.status
        not in {WorkflowRecoveryStatus.OPEN, WorkflowRecoveryStatus.AWAITING_SECOND_APPROVAL}
        or case.revision != expected_revision
        or case.state_checksum != expected_state_checksum
        or compute_checksum(case.run.redacted_state) != case.state_checksum
    ):
        raise WorkflowRecoveryError("RECOVERY_STALE")
    if case.run.status != WorkflowRunStatus.RECOVERY_REQUIRED:
        raise WorkflowRecoveryError("RECOVERY_WRONG_STATE")

    approval, created = WorkflowRecoveryApproval.objects.get_or_create(
        organization_id=case.organization_id,
        recovery_case=case,
        actor_id=actor_id,
        defaults={"action": action, "reason": clean_reason, "revision": expected_revision},
    )
    if not created and approval.action != action:
        raise WorkflowRecoveryError("RECOVERY_DECISION_CONFLICT")
    actions = set(case.approvals.values_list("action", flat=True))
    if len(actions) != 1:
        raise WorkflowRecoveryError("RECOVERY_DECISION_CONFLICT")
    approval_count = case.approvals.count()
    if action == "resume_compensation" and case.high_risk and approval_count < 2:
        case.status = WorkflowRecoveryStatus.AWAITING_SECOND_APPROVAL
        case.required_approvals = 2
        case.save(update_fields=["status", "required_approvals", "updated_at"])
        outcome = "awaiting_second_approval"
    else:
        case.status = WorkflowRecoveryStatus.RESOLVED
        case.resolved_action = action
        case.resolved_at = timezone.now()
        case.save(update_fields=["status", "resolved_action", "resolved_at", "updated_at"])
        if action == "terminate_failed":
            case.run.status = WorkflowRunStatus.FAILED
            case.run.error_code = case.reason_code
            case.run.finished_at = timezone.now()
            case.run.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
        else:
            # This merely releases the already compiled recovery policy. The runtime task still
            # revalidates terminal state, release pin, budgets and the resolved action.
            case.run.status = WorkflowRunStatus.QUEUED
            case.run.save(update_fields=["status", "updated_at"])
        outcome = "resolved"
    record_event(
        actor_type=ActorType.USER,
        actor_id=str(actor_id),
        action="workflow.recovery_decide",
        outcome=Outcome.SUCCESS,
        organization_id=case.organization_id,
        resource_type="workflow_recovery_case",
        resource_id=str(case.public_id),
        reason=action,
        after={"revision": case.revision, "status": outcome, "approval_count": approval_count},
    )
    return case
