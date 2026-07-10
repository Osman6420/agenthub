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
)
from apps.observability.models import UsageEvent


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
