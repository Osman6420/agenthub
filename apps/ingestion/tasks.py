"""Celery ingestion tasks; payloads contain identifiers only."""

from __future__ import annotations

from celery import shared_task

from apps.ingestion.confluence_sync import execute_confluence_sync
from apps.ingestion.models import ConfluenceSyncStatus, RunStatus
from apps.ingestion.services import execute_run


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
    return status
