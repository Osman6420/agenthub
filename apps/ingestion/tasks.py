"""Celery ingestion tasks; payloads contain identifiers only."""

from __future__ import annotations

from celery import shared_task
from django.db import transaction

from apps.ingestion.confluence_sync import execute_confluence_sync
from apps.ingestion.models import (
    ConfluenceSyncRun,
    ConfluenceSyncStatus,
    RestSyncRun,
    RestSyncStatus,
    RunStatus,
)
from apps.ingestion.rest_sync import execute_rest_sync
from apps.ingestion.services import execute_run
from apps.ingestion.vector_store import set_tenant_context


@shared_task(bind=True, queue="ingestion", max_retries=2)
def ingest_source(self: object, run_id: int) -> str:
    status = execute_run(run_id)
    if status == RunStatus.RETRY:
        raise self.retry(countdown=30)  # type: ignore[attr-defined]
    return status


@shared_task(bind=True, queue="ingestion", max_retries=2)
def sync_confluence_source(self: object, run_id: int, organization_id: int) -> str:
    status = execute_confluence_sync(run_id, organization_id=organization_id)
    if status == ConfluenceSyncStatus.RETRY:
        raise self.retry(countdown=30)  # type: ignore[attr-defined]
    if status == ConfluenceSyncStatus.SUCCEEDED:
        with transaction.atomic():
            set_tenant_context(organization_id)
            run = ConfluenceSyncRun.objects.filter(
                pk=run_id, organization_id=organization_id
            ).first()
        if run and run.schedule_id and run.candidate_set_version_id:
            apply_connector_automation_task.apply_async(
                args=[run.schedule_id, run.candidate_set_version_id, organization_id],
                queue="ingestion",
            )
    return status


@shared_task(bind=True, queue="ingestion", max_retries=2)
def sync_rest_source(self: object, run_id: int, organization_id: int) -> str:
    status = execute_rest_sync(run_id, organization_id=organization_id)
    if status == RestSyncStatus.RETRY:
        raise self.retry(countdown=30)  # type: ignore[attr-defined]
    if status == RestSyncStatus.SUCCEEDED:
        with transaction.atomic():
            set_tenant_context(organization_id)
            run = RestSyncRun.objects.filter(pk=run_id, organization_id=organization_id).first()
        if run and run.schedule_id and run.candidate_set_version_id:
            apply_connector_automation_task.apply_async(
                args=[run.schedule_id, run.candidate_set_version_id, organization_id],
                queue="ingestion",
            )
    return status


@shared_task(queue="ingestion")
def dispatch_connector_schedules() -> int:
    from apps.ingestion.scheduler import dispatch_due_schedules

    return dispatch_due_schedules()


@shared_task(bind=True, queue="ingestion", max_retries=80)
def apply_connector_automation_task(
    self: object, schedule_id: int, candidate_set_version_id: int, organization_id: int
) -> str:
    from apps.ingestion.automation import (
        ConnectorAutomationError,
        apply_connector_automation,
        claim_connector_automation,
        finish_connector_automation,
    )

    try:
        claimed = claim_connector_automation(
            schedule_id=schedule_id,
            candidate_set_version_id=candidate_set_version_id,
            organization_id=organization_id,
        )
    except ConnectorAutomationError as exc:
        if exc.code == "AUTOMATION_ALREADY_RUNNING":
            raise self.retry(countdown=30) from exc  # type: ignore[attr-defined]
        raise
    if not claimed:
        return "already_processed"
    try:
        result = apply_connector_automation(
            schedule_id=schedule_id,
            candidate_set_version_id=candidate_set_version_id,
            organization_id=organization_id,
        )
    except ConnectorAutomationError as exc:
        finish_connector_automation(
            schedule_id=schedule_id,
            candidate_set_version_id=candidate_set_version_id,
            organization_id=organization_id,
            succeeded=False,
            error_code=exc.code,
        )
        raise
    except Exception as exc:
        finish_connector_automation(
            schedule_id=schedule_id,
            candidate_set_version_id=candidate_set_version_id,
            organization_id=organization_id,
            succeeded=False,
            error_code=str(getattr(exc, "code", "AUTOMATION_INTERNAL_ERROR")),
        )
        raise
    finish_connector_automation(
        schedule_id=schedule_id,
        candidate_set_version_id=candidate_set_version_id,
        organization_id=organization_id,
        succeeded=True,
    )
    return result
