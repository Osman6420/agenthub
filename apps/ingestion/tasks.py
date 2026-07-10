"""Celery ingestion tasks; payloads contain identifiers only."""

from __future__ import annotations

from celery import shared_task

from apps.ingestion.models import RunStatus
from apps.ingestion.services import execute_run


@shared_task(bind=True, queue="ingestion", max_retries=2)
def ingest_source(self: object, run_id: int) -> str:
    status = execute_run(run_id)
    if status == RunStatus.RETRY:
        raise self.retry(countdown=30)  # type: ignore[attr-defined]
    return status
