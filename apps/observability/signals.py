"""Project canonical database events into bounded Prometheus counters."""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.audit.models import AuditEvent
from apps.evaluations.models import EvalCaseResult
from apps.ingestion.models import IngestionRun
from apps.observability.metrics import (
    EVAL_CASES,
    INGESTION_RUNS,
    RELEASE_LIFECYCLE,
    RUNTIME_REQUESTS,
    TOKENS,
    TOOL_APPROVALS,
    TOOL_INVOCATIONS,
    WORKFLOW_NODES,
    WORKFLOW_RUNS,
)
from apps.observability.models import UsageEvent
from apps.tools.models import (
    TERMINAL_INVOCATION_STATUSES,
    ApprovalRequest,
    ApprovalStatus,
    ToolInvocation,
)
from apps.workflows.compiler import BUILTIN_NODE_TYPES
from apps.workflows.models import WorkflowRun, WorkflowRunEvent

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


@receiver(post_save, sender=WorkflowRun, dispatch_uid="observability.workflow_run")
def workflow_run_saved(sender: Any, instance: WorkflowRun, **kwargs: Any) -> None:
    status = str(instance.status)
    if status not in {
        "requested",
        "queued",
        "running",
        "completed",
        "failed",
        "timed_out",
        "cancelled",
    }:
        status = "other"
    WORKFLOW_RUNS.labels(status=status).inc()


@receiver(post_save, sender=WorkflowRunEvent, dispatch_uid="observability.workflow_node")
def workflow_event_saved(
    sender: Any, instance: WorkflowRunEvent, created: bool, **kwargs: Any
) -> None:
    if not created or instance.event_type != "node_completed":
        return
    node_type = instance.outcome if instance.outcome in BUILTIN_NODE_TYPES else "other"
    WORKFLOW_NODES.labels(node_type=node_type).inc()


@receiver(post_save, sender=ToolInvocation, dispatch_uid="observability.tool_invocation")
def tool_invocation_saved(sender: Any, instance: ToolInvocation, **kwargs: Any) -> None:
    # Count each invocation once, when it reaches a terminal status.
    if instance.status in TERMINAL_INVOCATION_STATUSES:
        TOOL_INVOCATIONS.labels(status=str(instance.status)).inc()


@receiver(post_save, sender=ApprovalRequest, dispatch_uid="observability.tool_approval")
def tool_approval_saved(sender: Any, instance: ApprovalRequest, **kwargs: Any) -> None:
    if instance.status in _DECIDED_APPROVAL_STATUSES:
        TOOL_APPROVALS.labels(decision=str(instance.status)).inc()
