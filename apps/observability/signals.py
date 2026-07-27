"""Project canonical database events into bounded Prometheus counters."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.agents.models import AgentRun, AgentRunEvent
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.evaluations.models import EvalCaseResult
from apps.ingestion.models import IngestionRun
from apps.observability.metrics import (
    AGENT_RUNS,
    AGENT_STEPS,
    EVAL_CASES,
    INGESTION_RUNS,
    RELEASE_LIFECYCLE,
    RUNTIME_REQUESTS,
    SUPERADMIN_EVENTS,
    TOKENS,
    TOOL_APPROVALS,
    TOOL_INVOCATIONS,
    WORKFLOW_BRANCHES,
    WORKFLOW_CHILDREN,
    WORKFLOW_COMPENSATIONS,
    WORKFLOW_JOINS,
    WORKFLOW_NODES,
    WORKFLOW_RETRIES,
    WORKFLOW_RUNS,
    WORKFLOW_WAITS,
)
from apps.observability.models import UsageEvent
from apps.observability.tracing import current_trace_id
from apps.tools.models import (
    TERMINAL_INVOCATION_STATUSES,
    ApprovalRequest,
    ApprovalStatus,
    ToolInvocation,
)
from apps.workflows.compiler import BUILTIN_NODE_TYPES
from apps.workflows.models import (
    WorkflowBranch,
    WorkflowChildLink,
    WorkflowCompensationEntry,
    WorkflowJoin,
    WorkflowNodeAttempt,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowWait,
)

_BRANCH_OUTCOMES = frozenset({"succeeded", "failed", "cancelled"})
_JOIN_MODES = frozenset({"all", "threshold", "fail_fast"})
_JOIN_OUTCOMES = frozenset({"succeeded", "failed", "cancelled"})
_WAIT_KINDS = frozenset({"event", "timer", "human"})
_WAIT_RESOLVED = frozenset({"resumed", "expired", "cancelled"})
_FAILURE_CLASSES = frozenset(
    {"validation", "authorization", "permanent", "transient", "outcome_unknown"}
)
_COMPENSATION_OUTCOMES = frozenset({"succeeded", "blocked", "cancelled"})
_CHILD_KINDS = frozenset({"workflow", "agent"})
_CHILD_TERMINAL = frozenset({"completed", "failed", "cancelled"})


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


@receiver(post_save, sender=AgentRun, dispatch_uid="observability.agent_run")
def agent_run_saved(sender: Any, instance: AgentRun, **kwargs: Any) -> None:
    status = str(instance.status)
    if status not in {
        "requested",
        "queued",
        "running",
        "waiting_approval",
        "completed",
        "failed",
        "timed_out",
        "cancelled",
    }:
        status = "other"
    AGENT_RUNS.labels(status=status).inc()


@receiver(post_save, sender=AgentRunEvent, dispatch_uid="observability.agent_step")
def agent_event_saved(sender: Any, instance: AgentRunEvent, created: bool, **kwargs: Any) -> None:
    if not created or instance.event_type != "step_completed":
        return
    decision = (
        instance.decision if instance.decision in {"retrieve", "tool", "respond"} else "other"
    )
    AGENT_STEPS.labels(decision=decision).inc()


@receiver(post_save, sender=WorkflowBranch, dispatch_uid="observability.workflow_branch")
def workflow_branch_saved(sender: Any, instance: WorkflowBranch, **kwargs: Any) -> None:
    if str(instance.status) in _BRANCH_OUTCOMES:
        WORKFLOW_BRANCHES.labels(outcome=str(instance.status)).inc()


@receiver(post_save, sender=WorkflowJoin, dispatch_uid="observability.workflow_join")
def workflow_join_saved(sender: Any, instance: WorkflowJoin, **kwargs: Any) -> None:
    if str(instance.status) in _JOIN_OUTCOMES:
        WORKFLOW_JOINS.labels(
            mode=_bounded(str(instance.mode), _JOIN_MODES),
            outcome=str(instance.status),
        ).inc()


@receiver(post_save, sender=WorkflowWait, dispatch_uid="observability.workflow_wait")
def workflow_wait_saved(sender: Any, instance: WorkflowWait, created: bool, **kwargs: Any) -> None:
    kind = _bounded(str(instance.kind), _WAIT_KINDS)
    if created:
        WORKFLOW_WAITS.labels(kind=kind, phase="created").inc()
    elif str(instance.status) in _WAIT_RESOLVED:
        WORKFLOW_WAITS.labels(kind=kind, phase=str(instance.status)).inc()


@receiver(post_save, sender=WorkflowNodeAttempt, dispatch_uid="observability.workflow_retry")
def workflow_attempt_saved(sender: Any, instance: WorkflowNodeAttempt, **kwargs: Any) -> None:
    # A scheduled retry is the retry-storm signal; count when an attempt enters retry_wait.
    if str(instance.status) == "retry_wait":
        WORKFLOW_RETRIES.labels(
            failure_class=_bounded(str(instance.failure_class), _FAILURE_CLASSES)
        ).inc()


@receiver(
    post_save, sender=WorkflowCompensationEntry, dispatch_uid="observability.workflow_compensation"
)
def workflow_compensation_saved(
    sender: Any, instance: WorkflowCompensationEntry, **kwargs: Any
) -> None:
    if str(instance.status) in _COMPENSATION_OUTCOMES:
        WORKFLOW_COMPENSATIONS.labels(outcome=str(instance.status)).inc()


@receiver(post_save, sender=WorkflowChildLink, dispatch_uid="observability.workflow_child")
def workflow_child_saved(sender: Any, instance: WorkflowChildLink, **kwargs: Any) -> None:
    if str(instance.status) in _CHILD_TERMINAL:
        WORKFLOW_CHILDREN.labels(
            kind=_bounded(str(instance.child_kind), _CHILD_KINDS),
            status=str(instance.status),
        ).inc()


@receiver(post_save, sender=ToolInvocation, dispatch_uid="observability.tool_invocation")
def tool_invocation_saved(sender: Any, instance: ToolInvocation, **kwargs: Any) -> None:
    # Count each invocation once, when it reaches a terminal status.
    if instance.status in TERMINAL_INVOCATION_STATUSES:
        TOOL_INVOCATIONS.labels(status=str(instance.status)).inc()


@receiver(post_save, sender=ApprovalRequest, dispatch_uid="observability.tool_approval")
def tool_approval_saved(sender: Any, instance: ApprovalRequest, **kwargs: Any) -> None:
    if instance.status in _DECIDED_APPROVAL_STATUSES:
        TOOL_APPROVALS.labels(decision=str(instance.status)).inc()
