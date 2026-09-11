"""Link completed connector snapshots to the canonical durable preparation job."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.audit.services import record_event
from apps.documents.models import DocumentSetVersion, DocumentSetVersionStatus
from apps.documents.services import publish_document_set_version
from apps.ingestion.connector_jobs import _load_run, _lock_organization, _validate_inputs
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    DocumentSetPreparationProfile,
    EmbeddingProfile,
    OcrProfile,
    ScheduleAutomationMode,
    StagedIndexBuildJob,
    TenantEmbeddingProfileGrant,
    TenantOcrProfileGrant,
)
from apps.ingestion.preparation import automatic_preparation_job
from apps.ingestion.vector_store import set_tenant_context


class ConnectorPreparationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@transaction.atomic
def prepare_connector_snapshot(*, job_id: int, organization_id: int) -> StagedIndexBuildJob | None:
    """Commit publication, preparation intent, lineage and audit together; no remote I/O."""
    set_tenant_context(organization_id)
    _lock_organization(organization_id)
    source_job = StagedIndexBuildJob.objects.select_for_update().get(
        pk=job_id, organization_id=organization_id
    )
    if source_job.preparation_job_id is not None:
        return source_job.preparation_job
    run = _load_run(source_job)
    if (
        source_job.status != "succeeded"
        or not run.snapshot_complete
        or not run.candidate_set_version_id
    ):
        raise ConnectorPreparationError("PREPARATION_COMPLETE_SNAPSHOT_REQUIRED")
    if run.schedule_id is None or source_job.source_id is None:
        raise ConnectorPreparationError("PREPARATION_SCHEDULE_REQUIRED")
    schedule = (
        ConnectorSyncSchedule.objects.select_for_update(of=("self",))
        .select_related("embedding_profile", "ocr_profile")
        .filter(pk=run.schedule_id, organization_id=organization_id, source_id=source_job.source_id)
        .first()
    )
    if schedule is None:
        raise ConnectorPreparationError("PREPARATION_SCHEDULE_REQUIRED")
    if not schedule.enabled or schedule.automation_mode == ScheduleAutomationMode.DRAFT_ONLY:
        return None
    if schedule.automation_mode not in {
        ScheduleAutomationMode.STAGE_ONLY,
        ScheduleAutomationMode.PROMOTE_IF_SAFE,
    }:
        raise ConnectorPreparationError("PREPARATION_MODE_UNSUPPORTED")
    _validate_inputs(source_job, run)
    candidate = DocumentSetVersion.objects.select_for_update(no_key=True).get(
        pk=run.candidate_set_version_id,
        organization_id=organization_id,
        document_set_id=run.source.document_set_id,
    )
    policy = (
        DocumentSetPreparationProfile.objects.select_for_update(of=("self",))
        .select_related(
            "embedding_profile",
            "ocr_profile",
            "chunking_profile",
            "retrieval_profile",
            "summary_model_profile",
            "summary_prompt_contract",
        )
        .filter(organization_id=organization_id, document_set_id=candidate.document_set_id)
        .first()
    )
    if policy is None and (
        source_job.kind == "mcp_resource_sync"
        or schedule.automation_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE
    ):
        raise ConnectorPreparationError("PREPARATION_POLICY_REQUIRED")
    if schedule.automation_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE:
        from apps.ingestion.automation import _validate_promotion_authority

        _validate_promotion_authority(
            schedule=schedule,
            candidate=candidate,
            organization_id=organization_id,
            targets=list(
                schedule.promotion_targets.select_related("scenario__project").order_by("pk")[:201]
            ),
        )
    if policy is not None:
        if (policy.embedding_profile_id, policy.ocr_profile_id) != (
            schedule.embedding_profile_id,
            schedule.ocr_profile_id,
        ):
            raise ConnectorPreparationError("PREPARATION_POLICY_CONFLICT")
        try:
            policy.full_clean()
        except ValidationError as exc:
            raise ConnectorPreparationError("PREPARATION_POLICY_INVALID") from exc
    embedding = schedule.embedding_profile
    ocr = schedule.ocr_profile
    if embedding is None:
        raise ConnectorPreparationError("PREPARATION_EMBEDDING_NOT_GRANTED")
    return _link_preparation(
        source_job=source_job,
        candidate=candidate,
        policy=policy,
        embedding=embedding,
        ocr=ocr,
        actor=f"connector-preparation:{schedule.pk}",
        actor_type="system",
    )


def _link_preparation(
    *,
    source_job: StagedIndexBuildJob,
    candidate: DocumentSetVersion,
    policy: DocumentSetPreparationProfile | None,
    embedding: EmbeddingProfile,
    ocr: OcrProfile | None,
    actor: str,
    actor_type: str,
) -> StagedIndexBuildJob:
    """Caller owns org/job/candidate/policy locks and the transaction."""
    organization_id = source_job.organization_id
    if (
        embedding.status != "active"
        or not TenantEmbeddingProfileGrant.objects.filter(
            organization_id=organization_id, embedding_profile=embedding
        ).exists()
    ):
        raise ConnectorPreparationError("PREPARATION_EMBEDDING_NOT_GRANTED")
    if ocr is not None and (
        ocr.status != "active"
        or not TenantOcrProfileGrant.objects.filter(
            organization_id=organization_id, ocr_profile=ocr
        ).exists()
    ):
        raise ConnectorPreparationError("PREPARATION_OCR_NOT_GRANTED")
    if candidate.status == DocumentSetVersionStatus.DRAFT:
        candidate = publish_document_set_version(set_version=candidate, actor=actor)
    if candidate.status not in {
        DocumentSetVersionStatus.PROMOTABLE,
        DocumentSetVersionStatus.ACTIVE,
    }:
        raise ConnectorPreparationError("PREPARATION_CANDIDATE_NOT_PUBLISHED")
    build = automatic_preparation_job(
        document_set_version=candidate,
        embedding_profile=embedding,
        ocr_profile=ocr,
        policy=policy,
        actor=actor,
    )
    source_job.preparation_job = build
    source_job.revision += 1
    source_job.save(update_fields=["preparation_job", "revision", "updated_at"])
    record_event(
        actor_type=actor_type,
        actor_id=actor,
        action="ingestion.connector_job.preparation_linked",
        outcome="success",
        organization_id=organization_id,
        resource_type="ingestion_job",
        resource_id=str(source_job.public_id),
        request_id=source_job.request_id,
        after={"preparation_job": str(build.public_id), "preparation_state": build.status},
    )
    return build


def prepare_scheduled_candidate(
    *, schedule_id: int, candidate_set_version_id: int, organization_id: int
) -> tuple[bool, StagedIndexBuildJob | None]:
    """Route redelivered legacy task messages before their inline-build claim."""
    with transaction.atomic():
        set_tenant_context(organization_id)
        job = (
            StagedIndexBuildJob.objects.filter(
                Q(
                    rest_sync_run__schedule_id=schedule_id,
                    rest_sync_run__candidate_set_version_id=candidate_set_version_id,
                )
                | Q(
                    confluence_sync_run__schedule_id=schedule_id,
                    confluence_sync_run__candidate_set_version_id=candidate_set_version_id,
                ),
                organization_id=organization_id,
            )
            .order_by("-pk")
            .first()
        )
        if job is None:
            return False, None
        schedule = ConnectorSyncSchedule.objects.filter(
            pk=schedule_id, organization_id=organization_id
        ).first()
        if job.preparation_job_id is None and (
            schedule is None or schedule.automation_mode != ScheduleAutomationMode.STAGE_ONLY
        ):
            return False, None
    return True, prepare_connector_snapshot(job_id=job.pk, organization_id=organization_id)


def preparation_result(job: StagedIndexBuildJob | None) -> str:
    if job is None:
        return "draft_only"
    return "staged" if job.status == "succeeded" else f"preparation_{job.status}"


def continue_scheduled_publication(
    *, schedule_id: int, candidate_set_version_id: int, organization_id: int
) -> str | None:
    """Redirect old messages to the same durable publication; never run evaluation in SQL locks."""
    with transaction.atomic():
        set_tenant_context(organization_id)
        if not ConnectorSyncSchedule.objects.filter(
            pk=schedule_id,
            organization_id=organization_id,
            automation_mode="promote_if_safe",
        ).exists():
            return None
        job = (
            StagedIndexBuildJob.objects.filter(
                Q(
                    rest_sync_run__schedule_id=schedule_id,
                    rest_sync_run__candidate_set_version_id=candidate_set_version_id,
                )
                | Q(
                    confluence_sync_run__schedule_id=schedule_id,
                    confluence_sync_run__candidate_set_version_id=candidate_set_version_id,
                )
                | Q(
                    resource_snapshot__schedule_id=schedule_id,
                    resource_snapshot__candidate_set_version_id=candidate_set_version_id,
                ),
                organization_id=organization_id,
                status="succeeded",
            )
            .order_by("-pk")
            .first()
        )
        if job is None:
            raise ConnectorPreparationError("AUTOMATION_DURABLE_SOURCE_JOB_REQUIRED")
    preparation = prepare_connector_snapshot(job_id=job.pk, organization_id=organization_id)
    if preparation is None or preparation.status != "succeeded":
        return preparation_result(preparation)
    from apps.releases.source_publication import continue_source_publication

    return continue_source_publication(job_id=job.pk, organization_id=organization_id)
