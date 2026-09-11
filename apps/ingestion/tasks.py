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


@shared_task(bind=True, queue="ingestion", acks_late=True)
def run_staged_index_build_job(self: object, job_public_id: str) -> str:
    """Claim and converge one identifier-only durable build request."""
    from apps.ingestion.embedding import EmbeddingOutcomeUnknown
    from apps.ingestion.job_lifecycle import (
        claim_build_job,
        complete_build_job,
        fail_build_job,
        record_worker_heartbeat,
        update_progress,
    )
    from apps.ingestion.ocr import OcrOutcomeUnknown
    from apps.ingestion.staged_build import StagedBuildError, build_staged_index

    headers = getattr(getattr(self, "request", None), "headers", None) or {}
    try:
        organization_id = int(headers["organization_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("TENANT_CONTEXT_REQUIRED") from exc
    record_worker_heartbeat()
    job = claim_build_job(public_id=job_public_id, organization_id=organization_id)
    if job is None:
        return "already_converged"
    # claim_build_job validates the closed build target before committing ownership.
    if job.document_set_version is None or job.embedding_profile is None:
        raise ValueError("JOB_INPUT_LINEAGE_INVALID")
    try:
        index = build_staged_index(
            document_set_version=job.document_set_version,
            embedding_profile=job.embedding_profile,
            ocr_profile=job.ocr_profile,
            chunking_profile=job.chunking_profile,
            retrieval_profile=job.retrieval_profile,
            summary_model_profile=job.summary_model_profile,
            summary_prompt_contract=job.summary_prompt_contract,
            actor=job.requested_by,
            build_job=job,
            request_id=job.request_id,
            progress_callback=lambda documents, chunks: update_progress(
                job_id=job.pk,
                organization_id=organization_id,
                expected_attempt=job.attempt,
                documents=documents,
                chunks=chunks,
            ),
        )
        complete_build_job(
            job_id=job.pk,
            organization_id=organization_id,
            expected_attempt=job.attempt,
            index=index,
        )
    except (EmbeddingOutcomeUnknown, OcrOutcomeUnknown) as exc:
        fail_build_job(
            job_id=job.pk,
            organization_id=organization_id,
            error_code=str(getattr(exc, "code", "PROVIDER_OUTCOME_UNKNOWN")),
            expected_attempt=job.attempt,
            ambiguous=True,
        )
        raise
    except StagedBuildError as exc:
        fail_build_job(
            job_id=job.pk,
            organization_id=organization_id,
            error_code=exc.code,
            expected_attempt=job.attempt,
            ambiguous=False,
        )
        raise
    except Exception:
        fail_build_job(
            job_id=job.pk,
            organization_id=organization_id,
            error_code="BUILD_INTERNAL_ERROR",
            expected_attempt=job.attempt,
            ambiguous=False,
        )
        raise
    return f"built:{index.pk}"


@shared_task(queue="ingestion")
def reconcile_staged_index_build_jobs() -> int:
    from apps.ingestion.connector_jobs import reconcile_connector_jobs
    from apps.ingestion.job_lifecycle import reconcile_build_jobs, record_worker_heartbeat

    record_worker_heartbeat()
    return reconcile_build_jobs() + reconcile_connector_jobs()


@shared_task(bind=True, queue="ingestion", acks_late=True)
def run_connector_job(self: object, job_public_id: str) -> str:
    from apps.ingestion.connector_jobs import dispatch_connector_completion, execute_connector_job
    from apps.ingestion.job_lifecycle import record_worker_heartbeat

    headers = getattr(getattr(self, "request", None), "headers", None) or {}
    try:
        organization_id = int(headers["organization_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("TENANT_CONTEXT_REQUIRED") from exc
    record_worker_heartbeat()
    status = execute_connector_job(public_id=job_public_id, organization_id=organization_id)
    dispatch_connector_completion(organization_id=organization_id, public_id=job_public_id)
    return status


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
    from apps.ingestion.connector_preparation import (
        continue_scheduled_publication,
        preparation_result,
        prepare_scheduled_candidate,
    )

    publication = continue_scheduled_publication(
        schedule_id=schedule_id,
        candidate_set_version_id=candidate_set_version_id,
        organization_id=organization_id,
    )
    if publication is not None:
        return publication

    handled, preparation = prepare_scheduled_candidate(
        schedule_id=schedule_id,
        candidate_set_version_id=candidate_set_version_id,
        organization_id=organization_id,
    )
    if handled:
        return preparation_result(preparation)

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
