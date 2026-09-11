"""Project canonical database events into bounded Prometheus counters."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.evaluations.models import EvalCaseResult
from apps.ingestion.models import IngestionRun
from apps.observability.metrics import (
    EVAL_CASES,
    INGESTION_RUNS,
    RELEASE_LIFECYCLE,
    RUNTIME_REQUESTS,
    SUPERADMIN_EVENTS,
    TOKENS,
    TOOL_APPROVALS,
    TOOL_INVOCATIONS,
    UNIFIED_RUN_ADMISSIONS,
    UNIFIED_RUN_EVENTS,
)
from apps.observability.models import UsageEvent
from apps.observability.tracing import current_trace_id
from apps.tools.models import (
    TERMINAL_INVOCATION_STATUSES,
    ApprovalRequest,
    ApprovalStatus,
    ToolInvocation,
)
from apps.workflows.models import (
    Run,
    RunEvent,
    RunEventType,
    RunExecutionMode,
)

_RUN_EVENT_TYPES = frozenset(str(value) for value in RunEventType.values)
_RUN_EXECUTION_MODES = frozenset(str(value) for value in RunExecutionMode.values)


def _bounded(value: str, allowed: frozenset[str]) -> str:
    return value if value in allowed else "other"


_DECIDED_APPROVAL_STATUSES = frozenset(
    {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.CANCELLED,
    }
)


@receiver(post_save, sender=UsageEvent, dispatch_uid="observability.usage_event")
def usage_saved(sender: Any, instance: UsageEvent, created: bool, **kwargs: Any) -> None:
    if not created:
        return
    operation = instance.operation if instance.operation in {"invoke", "query"} else "other"
    status = instance.status if instance.status in {"completed", "fallback", "error"} else "other"
    RUNTIME_REQUESTS.labels(operation=operation, status=status).inc()
    TOKENS.labels(operation=operation, direction="input").inc(instance.input_tokens)
    TOKENS.labels(operation=operation, direction="output").inc(instance.output_tokens)


@receiver(post_save, sender=IngestionRun, dispatch_uid="observability.ingestion_run")
def ingestion_saved(sender: Any, instance: IngestionRun, **kwargs: Any) -> None:
    INGESTION_RUNS.labels(status=instance.status).inc()


@receiver(post_save, sender=EvalCaseResult, dispatch_uid="observability.eval_case")
def eval_case_saved(sender: Any, instance: EvalCaseResult, created: bool, **kwargs: Any) -> None:
    if created:
        EVAL_CASES.labels(status="passed" if instance.passed else "failed").inc()


@receiver(post_save, sender=AuditEvent, dispatch_uid="observability.release_lifecycle")
def release_audit_saved(sender: Any, instance: AuditEvent, created: bool, **kwargs: Any) -> None:
    if not created or not instance.action.startswith("release."):
        return
    action = instance.action.removeprefix("release.")
    if action not in {"promote", "rollback", "canary_start", "canary_stop"}:
        action = "other"
    outcome = instance.outcome if instance.outcome in {"allow", "deny", "failure"} else "other"
    RELEASE_LIFECYCLE.labels(action=action, outcome=outcome).inc()


@receiver(post_save, sender=AuditEvent, dispatch_uid="observability.superadmin_event")
def superadmin_audit_saved(sender: Any, instance: AuditEvent, created: bool, **kwargs: Any) -> None:
    if not created or not instance.action.startswith("superadmin."):
        return
    kind = "login" if instance.action == "superadmin.login" else "action"
    SUPERADMIN_EVENTS.labels(kind=kind).inc()


@receiver(user_logged_in, dispatch_uid="observability.superadmin_login")
def superadmin_logged_in(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    """Audit the exceptional identity without recording username, IP or session data."""
    if not getattr(user, "is_superuser", False):
        return
    record_event(
        actor_type="user",
        actor_id=str(user.pk),
        action="superadmin.login",
        outcome="success",
        resource_type="authentication",
        resource_id="django_session",
        reason="exceptional_recovery_identity",
        request_id=str(getattr(request, "request_id", ""))[:64],
        trace_id=current_trace_id(),
    )


@receiver(post_save, sender=Run, dispatch_uid="observability.unified_run")
def unified_run_saved(sender: Any, instance: Run, created: bool, **kwargs: Any) -> None:
    if not created:
        return
    execution_mode = _bounded(str(instance.execution_mode), _RUN_EXECUTION_MODES)
    UNIFIED_RUN_ADMISSIONS.labels(execution_mode=execution_mode).inc()


@receiver(post_save, sender=RunEvent, dispatch_uid="observability.unified_run_event")
def unified_run_event_saved(sender: Any, instance: RunEvent, created: bool, **kwargs: Any) -> None:
    if not created:
        return
    event_type = _bounded(str(instance.event_type), _RUN_EVENT_TYPES)
    UNIFIED_RUN_EVENTS.labels(event_type=event_type).inc()


@receiver(post_save, sender=ToolInvocation, dispatch_uid="observability.tool_invocation")
def tool_invocation_saved(sender: Any, instance: ToolInvocation, **kwargs: Any) -> None:
    # Count each invocation once, when it reaches a terminal status.
    if instance.status in TERMINAL_INVOCATION_STATUSES:
        TOOL_INVOCATIONS.labels(status=str(instance.status)).inc()


@receiver(post_save, sender=ApprovalRequest, dispatch_uid="observability.tool_approval")
def tool_approval_saved(sender: Any, instance: ApprovalRequest, **kwargs: Any) -> None:
    if instance.status in _DECIDED_APPROVAL_STATUSES:
        TOOL_APPROVALS.labels(decision=str(instance.status)).inc()
