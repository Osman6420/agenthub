"""Database-backed, no-catch-up dispatcher for governed connector schedules."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.ingestion.models import (
    ConfluenceSyncRun,
    ConnectorSyncSchedule,
    ConnectorType,
    RestSyncRun,
    SourceStatus,
    StagedIndexBuildJob,
)
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization

_ACTIVE = {"queued", "running", "retry"}
_REDRIVABLE = {"queued", "retry"}


def dispatch_due_schedules(*, now: datetime | None = None, limit_per_tenant: int = 100) -> int:
    """Claim due rows per tenant so FORCE RLS remains active during global Beat dispatch."""
    effective_now = now or timezone.now()
    enqueued = 0
    for organization_id in Organization.objects.order_by("id").values_list("id", flat=True):
        with transaction.atomic():
            set_tenant_context(organization_id)
            # Same root lock as manual admission; do not invert schedule/source locks
            # when legacy schedules coexist with already mapped common-job sources.
            Organization.objects.select_for_update(no_key=True).get(pk=organization_id)
            schedules = list(
                ConnectorSyncSchedule.objects.select_for_update(skip_locked=True)
                .select_related("source")
                .filter(
                    organization_id=organization_id,
                    enabled=True,
                    next_run_at__lte=effective_now,
                )
                .order_by("next_run_at", "id")[:limit_per_tenant]
            )
            for schedule in schedules:
                slot = schedule.next_run_at
                schedule.last_slot_at = slot
                # No backlog replay: the next slot is relative to dispatch time, not the stale slot.
                schedule.next_run_at = effective_now + timedelta(seconds=schedule.interval_seconds)
                schedule.save(update_fields=["last_slot_at", "next_run_at", "updated_at"])
                if schedule.source.connector_type == ConnectorType.MCP_RESOURCE and not getattr(
                    settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False
                ):
                    _audit_skip(schedule, "MCP_RESOURCE_SCHEDULE_UNAVAILABLE")
                    continue
                if schedule.source.status != SourceStatus.ACTIVE:
                    _audit_skip(schedule, "SOURCE_DISABLED")
                    continue
                pending_run_id = _pending_run_id(schedule)
                if pending_run_id is not None:
                    _enqueue_on_commit(schedule, pending_run_id)
                    enqueued += 1
                    _audit_redrive(schedule, pending_run_id)
                    continue
                if _has_active_run(schedule):
                    _audit_skip(schedule, "RUN_ALREADY_ACTIVE")
                    continue
                run_id = _create_scheduled_run(schedule, slot)
                if run_id is None:
                    _audit_skip(schedule, "SOURCE_BINDING_INVALID")
                    continue
                _enqueue_on_commit(schedule, run_id)
                enqueued += 1
                record_event(
                    actor_type=ActorType.SYSTEM,
                    actor_id="connector-scheduler",
                    action="connector_schedule.enqueued",
                    outcome=Outcome.SUCCESS,
                    organization_id=organization_id,
                    resource_type="connector_sync_schedule",
                    resource_id=str(schedule.pk),
                    after={"run_id": run_id, "connector_type": schedule.source.connector_type},
                )
    return enqueued


def _has_active_run(schedule: ConnectorSyncSchedule) -> bool:
    from apps.ingestion.job_lifecycle import ACTIVE_STATES

    if StagedIndexBuildJob.objects.filter(
        source=schedule.source, status__in=ACTIVE_STATES
    ).exists():
        return True
    if schedule.source.connector_type == ConnectorType.CONFLUENCE_DC:
        return ConfluenceSyncRun.objects.filter(source=schedule.source, status__in=_ACTIVE).exists()
    if schedule.source.connector_type == ConnectorType.GENERIC_REST:
        return RestSyncRun.objects.filter(source=schedule.source, status__in=_ACTIVE).exists()
    return False


def _pending_run_id(schedule: ConnectorSyncSchedule) -> int | None:
    if schedule.source.connector_type == ConnectorType.MCP_RESOURCE:
        return (
            StagedIndexBuildJob.objects.filter(
                organization_id=schedule.organization_id,
                source_id=schedule.source_id,
                kind="mcp_resource_sync",
                resource_snapshot__schedule=schedule,
                status__in={"dispatch_pending", "queued", "retry_wait"},
            )
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)
            .first()
        )
    if schedule.source.connector_type == ConnectorType.CONFLUENCE_DC:
        return (
            ConfluenceSyncRun.objects.filter(schedule=schedule, status__in=_REDRIVABLE)
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)
            .first()
        )
    if schedule.source.connector_type == ConnectorType.GENERIC_REST:
        return (
            RestSyncRun.objects.filter(schedule=schedule, status__in=_REDRIVABLE)
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)
            .first()
        )
    return None


def _create_scheduled_run(schedule: ConnectorSyncSchedule, slot: datetime) -> int | None:
    if getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        from apps.ingestion.confluence import ConfluenceError
        from apps.ingestion.connections import ConnectionError
        from apps.ingestion.connector_jobs import ConnectorJobError, create_scheduled_connector_job
        from apps.ingestion.mcp_resources import McpResourceError
        from apps.ingestion.rest import RestPullError

        try:
            job, _ = create_scheduled_connector_job(schedule=schedule, slot=slot)
        except (
            ConnectorJobError,
            ConnectionError,
            ConfluenceError,
            RestPullError,
            McpResourceError,
        ):
            return None
        if schedule.source.connector_type == ConnectorType.MCP_RESOURCE:
            return job.pk
        return job.rest_sync_run_id or job.confluence_sync_run_id
    source = schedule.source
    if source.connector_type == ConnectorType.CONFLUENCE_DC and source.confluence_profile_id:
        confluence_run = ConfluenceSyncRun.objects.create(
            organization_id=schedule.organization_id,
            source=source,
            confluence_profile_id=source.confluence_profile_id,
            schedule=schedule,
            schedule_slot=slot,
        )
        return confluence_run.pk
    if (
        source.connector_type == ConnectorType.GENERIC_REST
        and source.rest_profile_id
        and source.rest_contract_id
    ):
        rest_run = RestSyncRun.objects.create(
            organization_id=schedule.organization_id,
            source=source,
            rest_profile_id=source.rest_profile_id,
            rest_contract_id=source.rest_contract_id,
            schedule=schedule,
            schedule_slot=slot,
        )
        return rest_run.pk
    return None


def _enqueue_on_commit(schedule: ConnectorSyncSchedule, run_id: int) -> None:
    organization_id = schedule.organization_id
    connector_type = schedule.source.connector_type
    field = (
        "confluence_sync_run_id"
        if connector_type == ConnectorType.CONFLUENCE_DC
        else "rest_sync_run_id"
    )
    lookup = (
        {"pk": run_id, "kind": "mcp_resource_sync", "resource_snapshot__schedule_id": schedule.pk}
        if connector_type == ConnectorType.MCP_RESOURCE
        else {field: run_id}
    )
    job = StagedIndexBuildJob.objects.filter(
        organization_id=organization_id, source_id=schedule.source_id, **lookup
    ).first()
    if job is not None:
        from apps.ingestion.job_lifecycle import dispatch_outbox

        transaction.on_commit(
            lambda: dispatch_outbox(
                limit=1, job_public_id=job.public_id, organization_id=organization_id
            )
        )
        return

    if connector_type == ConnectorType.MCP_RESOURCE:
        return

    def enqueue() -> None:
        from apps.ingestion.tasks import sync_confluence_source, sync_rest_source

        task = (
            sync_confluence_source
            if connector_type == ConnectorType.CONFLUENCE_DC
            else sync_rest_source
        )
        task.apply_async(args=[run_id, organization_id], queue="ingestion")

    transaction.on_commit(enqueue)


def _audit_skip(schedule: ConnectorSyncSchedule, reason: str) -> None:
    record_event(
        actor_type=ActorType.SYSTEM,
        actor_id="connector-scheduler",
        action="connector_schedule.skipped",
        outcome=Outcome.DENY,
        organization_id=schedule.organization_id,
        resource_type="connector_sync_schedule",
        resource_id=str(schedule.pk),
        reason=reason,
    )


def _audit_redrive(schedule: ConnectorSyncSchedule, run_id: int) -> None:
    record_event(
        actor_type=ActorType.SYSTEM,
        actor_id="connector-scheduler",
        action="connector_schedule.redriven",
        outcome=Outcome.SUCCESS,
        organization_id=schedule.organization_id,
        resource_type="connector_sync_schedule",
        resource_id=str(schedule.pk),
        after={"run_id": run_id},
    )
