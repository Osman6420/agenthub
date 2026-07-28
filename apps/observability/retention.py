"""P2.6.11 bounded, audited, fail-closed retention/purge of bulky orchestration state.

The owner-approved policy (see the P2.6.11 plan) keeps all traceability/audit/eval/lineage
data indefinitely and purges only **bulky high-detail working state** older than a single
90-day window:

- ``run_state``         — unified ``Run.checkpoint`` / ``redacted_state`` working payloads.
  The run, counters and append-only event trail are retained.
- ``branch_state``      — ``RunBranch.input_state`` / ``result_state`` working payloads.
  The branch row (region/branch/status/reason/checksum lineage) is retained.
- ``wait_payload``      — unified ``RunWait.redacted_payload`` on resolved waits. The one-way
  resume-token hash and wait lineage remain for replay detection and audit.

Purge never deletes a row or any audit/eval record; it clears named columns in bounded,
audited batches. Report mode (the default) counts eligible rows without mutating anything.
Deletion is enabled only via ``commit=True`` (the management command's ``--commit`` flag, and
only after owner window approval). Audit persistence failure fails closed: the batch's
``UPDATE`` and its audit row share a transaction, so a failed audit rolls back the purge.
Re-runs are idempotent — a cleared row no longer matches its eligibility filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.services import record_event
from apps.workflows.models import (
    RUN_TERMINAL_STATUSES,
    Run,
    RunBranch,
    RunWait,
    RunWaitStatus,
)

RETENTION_DAYS = 90
DEFAULT_BATCH_SIZE = 500

# Resolved wait states whose correlation material is no longer needed for resumption.
_RESOLVED_WAIT_STATUSES = frozenset(
    {RunWaitStatus.RESUMED, RunWaitStatus.EXPIRED, RunWaitStatus.CANCELLED}
)


@dataclass(frozen=True)
class RetentionReport:
    retention_class: str
    eligible: int
    purged: int


def retention_cutoff(now: datetime | None = None) -> datetime:
    return (now or timezone.now()) - timedelta(days=RETENTION_DAYS)


def _purge_class(
    *,
    retention_class: str,
    queryset: QuerySet[Any],
    clear_fields: dict[str, Any],
    commit: bool,
    batch_size: int,
    actor: str,
) -> RetentionReport:
    model = queryset.model
    eligible = queryset.count()
    purged = 0
    if not commit or eligible == 0:
        return RetentionReport(retention_class, eligible, 0)
    while True:
        batch_ids = list(queryset.values_list("pk", flat=True)[:batch_size])
        if not batch_ids:
            break
        # Fail-closed: the column clear and its audit row commit together. If the audit
        # write raises, the transaction rolls back and nothing is purged.
        with transaction.atomic():
            count = model.objects.filter(pk__in=batch_ids).update(**clear_fields)
            record_event(
                actor_type="system",
                actor_id=actor,
                action="retention.purge",
                outcome="success",
                resource_type="retention_class",
                resource_id=retention_class,
                reason="window_exceeded",
                after={"class": retention_class, "window_days": RETENTION_DAYS, "count": count},
            )
            purged += count
    return RetentionReport(retention_class, eligible, purged)


def run_retention(
    *,
    commit: bool = False,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    actor: str = "retention-job",
) -> list[RetentionReport]:
    """Report (default) or purge bulky orchestration state older than the 90-day window."""
    cutoff = retention_cutoff(now)
    reports = [
        _purge_class(
            retention_class="run_state",
            queryset=Run.objects.filter(
                status__in=RUN_TERMINAL_STATUSES, finished_at__lt=cutoff
            ).exclude(Q(checkpoint={}) & Q(redacted_state={})),
            clear_fields={"checkpoint": {}, "redacted_state": {}},
            commit=commit,
            batch_size=batch_size,
            actor=actor,
        ),
        _purge_class(
            retention_class="branch_state",
            queryset=_branch_state_queryset(cutoff),
            clear_fields={"input_state": {}, "result_state": {}},
            commit=commit,
            batch_size=batch_size,
            actor=actor,
        ),
        _purge_class(
            retention_class="wait_payload",
            queryset=RunWait.objects.filter(
                status__in=_RESOLVED_WAIT_STATUSES, updated_at__lt=cutoff
            ).exclude(redacted_payload={}),
            clear_fields={"redacted_payload": {}},
            commit=commit,
            batch_size=batch_size,
            actor=actor,
        ),
    ]
    return reports


def _branch_state_queryset(cutoff: datetime) -> QuerySet[Any]:
    return RunBranch.objects.filter(
        run__status__in=RUN_TERMINAL_STATUSES, finished_at__lt=cutoff
    ).exclude(Q(input_state={}) & Q(result_state={}))
