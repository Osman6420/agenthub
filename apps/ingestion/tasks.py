"""Celery ingestion tasks; payloads contain identifiers only."""

from __future__ import annotations

from celery import shared_task
from django.db import transaction

from apps.ingestion.confluence_sync import execute_confluence_sync
from apps.ingestion.models import (
    ConfluenceSyncRun,
    ConfluenceSyncStatus,
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IndexStatus,
    IndexVersion,
    OcrProfile,
    OcrProfileStatus,
    RestSyncRun,
    RestSyncStatus,
    RunStatus,
    TenantEmbeddingProfileGrant,
    TenantOcrProfileGrant,
)
from apps.ingestion.rest_sync import execute_rest_sync
from apps.ingestion.services import execute_run
from apps.ingestion.vector_store import set_tenant_context


@shared_task(bind=True, queue="ingestion", max_retries=2)
def ingest_source(self: object, run_id: int, organization_id: int) -> str:
    status = execute_run(run_id, organization_id)
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


@shared_task(queue="ingestion")
def build_document_set_index_task(
    document_set_version_id: int,
    embedding_profile_id: int,
    organization_id: int,
    actor: str,
    ocr_profile_id: int | None = None,
) -> str:
    """Build one tenant-scoped staged index from identifier-only queue payloads."""
    from apps.documents.models import DocumentSetVersion
    from apps.ingestion.staged_build import build_staged_index

    with transaction.atomic():
        set_tenant_context(organization_id)
        set_version = DocumentSetVersion.objects.filter(
            pk=document_set_version_id, organization_id=organization_id
        ).first()
        embedding_profile = EmbeddingProfile.objects.filter(
            pk=embedding_profile_id,
            status=EmbeddingProfileStatus.ACTIVE,
            tenant_grants__organization_id=organization_id,
        ).first()
        ocr_profile = None
        if ocr_profile_id is not None:
            ocr_profile = OcrProfile.objects.filter(
                pk=ocr_profile_id,
                status=OcrProfileStatus.ACTIVE,
                tenant_grants__organization_id=organization_id,
            ).first()
        if set_version is None:
            raise ValueError("DOCUMENT_SET_VERSION_NOT_FOUND")
        if (
            embedding_profile is None
            or not TenantEmbeddingProfileGrant.objects.filter(
                organization_id=organization_id, embedding_profile_id=embedding_profile_id
            ).exists()
        ):
            raise ValueError("EMBEDDING_PROFILE_NOT_GRANTED")
        if ocr_profile_id is not None and (
            ocr_profile is None
            or not TenantOcrProfileGrant.objects.filter(
                organization_id=organization_id, ocr_profile_id=ocr_profile_id
            ).exists()
        ):
            raise ValueError("OCR_PROFILE_NOT_GRANTED")

        existing = (
            IndexVersion.objects.filter(
                organization_id=organization_id,
                document_set_version_id=document_set_version_id,
                embedding_profile_id=embedding_profile_id,
                status__in=[IndexStatus.BUILDING, IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
            )
            .order_by("-version")
            .first()
        )
    if existing is not None:
        return f"already_{existing.status}:{existing.pk}"
    index = build_staged_index(
        document_set_version=set_version,
        embedding_profile=embedding_profile,
        ocr_profile=ocr_profile,
        actor=actor,
    )
    return f"built:{index.pk}"


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
