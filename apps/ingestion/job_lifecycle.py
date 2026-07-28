"""Durable staged-index build lifecycle; PostgreSQL is authority, Celery is delivery."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.audit.services import record_event
from apps.ingestion.models import (
    EmbeddingProfile,
    IndexStatus,
    IndexVersion,
    IngestionWorkerHeartbeat,
    OcrProfile,
    StagedIndexBuildJob,
    StagedIndexBuildJobStatus,
    StagedIndexBuildOutbox,
)
from apps.ingestion.vector_store import set_tenant_context
from apps.observability.metrics import (
    INGESTION_BUILD_DURATION,
    INGESTION_BUILD_JOBS,
    INGESTION_CLAIM_LATENCY,
    INGESTION_OLDEST_QUEUE_AGE,
    INGESTION_RECONCILIATIONS,
    INGESTION_WORKER_COMPATIBLE,
    INGESTION_WORKER_HEARTBEAT_AGE,
)

if TYPE_CHECKING:
    from apps.documents.models import DocumentSetVersion

CONTRACT_REVISION = 2
TERMINAL_STATES = frozenset(
    {
        StagedIndexBuildJobStatus.SUCCEEDED,
        StagedIndexBuildJobStatus.FAILED,
        StagedIndexBuildJobStatus.CANCELLED,
    }
)
ACTIVE_STATES = frozenset(
    {
        StagedIndexBuildJobStatus.DISPATCH_PENDING,
        StagedIndexBuildJobStatus.QUEUED,
        StagedIndexBuildJobStatus.RUNNING,
        StagedIndexBuildJobStatus.RETRY_WAIT,
        StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED,
    }
)
_INSTANCE_ID = uuid.uuid4()


class BuildJobError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical_checksum(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def config_fingerprint() -> str:
    """Fingerprint non-secret role/config identity; credentials are presence bits only."""
    object_store = getattr(settings, "OBJECT_STORE", {})
    endpoint = str(object_store.get("endpoint_url", ""))
    bucket = str(object_store.get("bucket", ""))
    broker = str(getattr(settings, "CELERY_BROKER_URL", ""))
    payload = {
        "schema": 1,
        "broker_scheme": broker.split(":", 1)[0].lower(),
        "object_store_endpoint": endpoint.rstrip("/").lower(),
        "object_store_bucket": bucket,
        "object_store_credentials_present": bool(
            os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")
        ),
    }
    return _canonical_checksum(payload)


def record_worker_heartbeat() -> IngestionWorkerHeartbeat:
    now = timezone.now()
    heartbeat, _ = IngestionWorkerHeartbeat.objects.update_or_create(
        instance_id=_INSTANCE_ID,
        defaults={
            "queue_role": "ingestion",
            "service_revision": os.environ.get("AGENTHUB_SERVICE_REVISION", "development")[:64],
            "contract_revision": CONTRACT_REVISION,
            "config_fingerprint": config_fingerprint(),
            "last_seen_at": now,
        },
    )
    return heartbeat


def compatible_worker_available(*, now: datetime | None = None) -> bool:
    current = now or timezone.now()
    ttl = int(getattr(settings, "INGESTION_WORKER_HEARTBEAT_TTL_SECONDS", 30))
    compatible = IngestionWorkerHeartbeat.objects.filter(
        queue_role="ingestion",
        contract_revision=CONTRACT_REVISION,
        config_fingerprint=config_fingerprint(),
        last_seen_at__gte=current - timedelta(seconds=ttl),
    )
    freshest = compatible.order_by("-last_seen_at").values_list("last_seen_at", flat=True).first()
    available = freshest is not None
    INGESTION_WORKER_COMPATIBLE.set(1 if available else 0)
    INGESTION_WORKER_HEARTBEAT_AGE.set(
        max(0.0, (current - freshest).total_seconds()) if freshest is not None else ttl
    )
    return available


def _observe(status: str, failure_class: str = "none") -> None:
    INGESTION_BUILD_JOBS.labels(status=status, failure_class=failure_class).inc()


def create_build_job(
    *,
    document_set_version: DocumentSetVersion,
    embedding_profile: EmbeddingProfile,
    ocr_profile: OcrProfile | None,
    chunking_profile: ArtifactVersion | None = None,
    retrieval_profile: ArtifactVersion | None = None,
    summary_model_profile: ArtifactVersion | None = None,
    summary_prompt_contract: ArtifactVersion | None = None,
    actor: str,
    request_id: str = "",
) -> tuple[StagedIndexBuildJob, bool]:
    from apps.ingestion.staged_build import pipeline_fingerprint

    organization_id = document_set_version.organization_id
    pipeline = pipeline_fingerprint(
        embedding_profile=embedding_profile,
        chunker="fixed",
        ocr_profile=ocr_profile,
        chunking_profile=chunking_profile,
        retrieval_profile=retrieval_profile,
        summary_model_profile=summary_model_profile,
        summary_prompt_contract=summary_prompt_contract,
    )
    checksum = _canonical_checksum(
        {
            "schema": 2,
            "organization_id": organization_id,
            "document_set_version_id": document_set_version.pk,
            "embedding_profile_id": int(embedding_profile.pk),
            "ocr_profile_id": int(ocr_profile.pk) if ocr_profile else None,
            "chunking_profile_id": int(chunking_profile.pk) if chunking_profile else None,
            "retrieval_profile_id": int(retrieval_profile.pk) if retrieval_profile else None,
            "summary_model_profile_id": int(summary_model_profile.pk)
            if summary_model_profile
            else None,
            "summary_prompt_contract_id": int(summary_prompt_contract.pk)
            if summary_prompt_contract
            else None,
            "pipeline_fingerprint": pipeline,
        }
    )
    now = timezone.now()
    try:
        with transaction.atomic():
            set_tenant_context(organization_id)
            job = StagedIndexBuildJob.objects.create(
                organization_id=organization_id,
                document_set_version=document_set_version,
                embedding_profile=embedding_profile,
                ocr_profile=ocr_profile,
                chunking_profile=chunking_profile,
                retrieval_profile=retrieval_profile,
                summary_model_profile=summary_model_profile,
                summary_prompt_contract=summary_prompt_contract,
                request_checksum=checksum,
                pipeline_fingerprint=pipeline,
                requested_by=actor[:255],
                request_id=request_id[:128],
                max_attempts=int(getattr(settings, "INGESTION_BUILD_MAX_ATTEMPTS", 3)),
            )
            StagedIndexBuildOutbox.objects.create(
                organization_id=organization_id,
                job=job,
                request_checksum=checksum,
                available_at=now,
            )
            record_event(
                actor_type="user",
                actor_id=actor,
                action="ingestion.staged_index.job_requested",
                outcome="success",
                organization_id=organization_id,
                resource_type="staged_index_build_job",
                resource_id=str(job.public_id),
                request_id=request_id,
                after={"state": job.status},
            )
            transaction.on_commit(
                lambda: dispatch_outbox(
                    limit=1, job_public_id=job.public_id, organization_id=organization_id
                )
            )
            _observe(StagedIndexBuildJobStatus.DISPATCH_PENDING)
        return job, True
    except IntegrityError:
        with transaction.atomic():
            set_tenant_context(organization_id)
            existing = StagedIndexBuildJob.objects.filter(
                organization_id=organization_id, request_checksum=checksum
            ).first()
            if existing is None:
                existing = StagedIndexBuildJob.objects.filter(
                    organization_id=organization_id,
                    document_set_version=document_set_version,
                    embedding_profile=embedding_profile,
                    pipeline_fingerprint=pipeline,
                    status__in=ACTIVE_STATES,
                ).first()
            if existing is None:
                raise
            return existing, False


def dispatch_outbox(
    *,
    limit: int = 100,
    job_public_id: uuid.UUID | None = None,
    organization_id: int | None = None,
) -> int:
    from apps.ingestion.tasks import run_staged_index_build_job
    from apps.tenancy.models import Organization

    published = 0
    organization_ids = (
        [organization_id]
        if organization_id is not None
        else list(Organization.objects.order_by("pk").values_list("pk", flat=True)[:100])
    )
    for scoped_organization_id in organization_ids:
        if published >= limit:
            break
        with transaction.atomic():
            set_tenant_context(scoped_organization_id)
            query = StagedIndexBuildOutbox.objects.filter(
                organization_id=scoped_organization_id,
                published_at__isnull=True,
                available_at__lte=timezone.now(),
            ).select_related("job")
            if job_public_id is not None:
                query = query.filter(job__public_id=job_public_id)
            outbox_ids = list(
                query.order_by("available_at", "pk").values_list("pk", flat=True)[
                    : limit - published
                ]
            )
        for outbox_id in outbox_ids:
            with transaction.atomic():
                set_tenant_context(scoped_organization_id)
                outbox = (
                    StagedIndexBuildOutbox.objects.select_for_update()
                    .select_related("job")
                    .get(pk=outbox_id, organization_id=scoped_organization_id)
                )
                if outbox.published_at is not None or outbox.job.status in TERMINAL_STATES:
                    continue
                now = timezone.now()
                outbox.publish_attempts += 1
                outbox.job.dispatch_attempted_at = now
                try:
                    run_staged_index_build_job.apply_async(
                        args=[str(outbox.job.public_id)],
                        headers={"organization_id": outbox.job.organization_id},
                        queue="ingestion",
                        retry=False,
                    )
                except Exception:
                    outbox.last_error_code = "BROKER_UNAVAILABLE"
                    outbox.available_at = now + timedelta(seconds=30)
                    outbox.save(
                        update_fields=[
                            "publish_attempts",
                            "last_error_code",
                            "available_at",
                            "updated_at",
                        ]
                    )
                    outbox.job.save(update_fields=["dispatch_attempted_at", "updated_at"])
                    continue
                outbox.published_at = now
                outbox.last_error_code = ""
                outbox.save(
                    update_fields=[
                        "publish_attempts",
                        "published_at",
                        "last_error_code",
                        "updated_at",
                    ]
                )
                outbox.job.status = StagedIndexBuildJobStatus.QUEUED
                outbox.job.queued_at = now
                outbox.job.revision += 1
                outbox.job.save(
                    update_fields=[
                        "status",
                        "queued_at",
                        "dispatch_attempted_at",
                        "revision",
                        "updated_at",
                    ]
                )
                published += 1
                _observe(StagedIndexBuildJobStatus.QUEUED)
    return published


def claim_build_job(*, public_id: str, organization_id: int) -> StagedIndexBuildJob | None:
    with transaction.atomic():
        set_tenant_context(organization_id)
        job = (
            StagedIndexBuildJob.objects.select_for_update()
            .filter(public_id=public_id, organization_id=organization_id)
            .first()
        )
        if job is None:
            raise BuildJobError("JOB_NOT_FOUND")
        if job.status == StagedIndexBuildJobStatus.SUCCEEDED:
            return None
        if job.status in {StagedIndexBuildJobStatus.CANCELLED, StagedIndexBuildJobStatus.FAILED}:
            return None
        if job.status == StagedIndexBuildJobStatus.RUNNING:
            return None
        if job.attempt >= job.max_attempts:
            job.status = StagedIndexBuildJobStatus.FAILED
            job.error_code = "MAX_ATTEMPTS_EXCEEDED"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
            return None
        now = timezone.now()
        if job.queued_at is not None:
            INGESTION_CLAIM_LATENCY.observe(max(0.0, (now - job.queued_at).total_seconds()))
        job.status = StagedIndexBuildJobStatus.RUNNING
        job.attempt += 1
        job.claimed_at = now
        job.heartbeat_at = now
        job.error_code = ""
        job.revision += 1
        job.save(
            update_fields=[
                "status",
                "attempt",
                "claimed_at",
                "heartbeat_at",
                "error_code",
                "revision",
                "updated_at",
            ]
        )
        _observe(StagedIndexBuildJobStatus.RUNNING)
        return job


def update_progress(*, job_id: int, organization_id: int, documents: int, chunks: int) -> None:
    with transaction.atomic():
        set_tenant_context(organization_id)
        job = StagedIndexBuildJob.objects.select_for_update().get(
            pk=job_id, organization_id=organization_id
        )
        if job.status != StagedIndexBuildJobStatus.RUNNING:
            return
        if documents < job.documents_completed or chunks < job.chunks_completed:
            raise BuildJobError("PROGRESS_NOT_MONOTONIC")
        job.documents_completed = min(documents, 5_000)
        job.chunks_completed = min(chunks, 200_000)
        job.heartbeat_at = timezone.now()
        job.save(
            update_fields=["documents_completed", "chunks_completed", "heartbeat_at", "updated_at"]
        )


def complete_build_job(*, job_id: int, organization_id: int, index: IndexVersion) -> None:
    with transaction.atomic():
        set_tenant_context(organization_id)
        job = StagedIndexBuildJob.objects.select_for_update().get(
            pk=job_id, organization_id=organization_id
        )
        if job.status in TERMINAL_STATES:
            if (
                job.status == StagedIndexBuildJobStatus.CANCELLED
                and index.organization_id == organization_id
                and index.document_set_version_id == job.document_set_version_id
                and index.embedding_profile_id == job.embedding_profile_id
                and index.pipeline_fingerprint == job.pipeline_fingerprint
            ):
                IndexVersion.objects.filter(pk=index.pk, status=IndexStatus.PROMOTABLE).update(
                    status=IndexStatus.FAILED
                )
            return
        if (
            index.organization_id != organization_id
            or index.document_set_version_id != job.document_set_version_id
            or index.embedding_profile_id != job.embedding_profile_id
            or index.pipeline_fingerprint != job.pipeline_fingerprint
            or index.status != IndexStatus.PROMOTABLE
        ):
            raise BuildJobError("RESULT_LINEAGE_MISMATCH")
        job.status = StagedIndexBuildJobStatus.SUCCEEDED
        job.result_index_version = index
        job.documents_completed = index.document_count
        job.chunks_completed = index.chunk_count
        job.heartbeat_at = timezone.now()
        job.finished_at = timezone.now()
        job.error_code = ""
        job.revision += 1
        job.save(
            update_fields=[
                "status",
                "result_index_version",
                "documents_completed",
                "chunks_completed",
                "heartbeat_at",
                "finished_at",
                "error_code",
                "revision",
                "updated_at",
            ]
        )
        if job.claimed_at is not None:
            INGESTION_BUILD_DURATION.observe(
                max(0.0, (job.finished_at - job.claimed_at).total_seconds())
            )
        record_event(
            actor_type="system",
            actor_id="ingestion-worker",
            action="ingestion.staged_index.job_succeeded",
            outcome="success",
            organization_id=organization_id,
            resource_type="staged_index_build_job",
            resource_id=str(job.public_id),
            request_id=job.request_id,
            after={"state": job.status, "index_version_id": index.pk},
        )
        _observe(StagedIndexBuildJobStatus.SUCCEEDED)


def fail_build_job(*, job_id: int, organization_id: int, error_code: str, ambiguous: bool) -> None:
    safe_code = error_code if error_code.isupper() and len(error_code) <= 64 else "BUILD_FAILED"
    with transaction.atomic():
        set_tenant_context(organization_id)
        job = StagedIndexBuildJob.objects.select_for_update().get(
            pk=job_id, organization_id=organization_id
        )
        if job.status in TERMINAL_STATES:
            return
        job.status = (
            StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED
            if ambiguous
            else StagedIndexBuildJobStatus.FAILED
        )
        job.error_code = safe_code
        job.finished_at = None if ambiguous else timezone.now()
        job.revision += 1
        job.save(update_fields=["status", "error_code", "finished_at", "revision", "updated_at"])
        _observe(job.status, "ambiguous" if ambiguous else "build")


def cancel_build_job(*, job: StagedIndexBuildJob, actor: str) -> StagedIndexBuildJob:
    with transaction.atomic():
        set_tenant_context(job.organization_id)
        locked = StagedIndexBuildJob.objects.select_for_update().get(pk=job.pk)
        if locked.status in TERMINAL_STATES:
            return locked
        locked.status = StagedIndexBuildJobStatus.CANCELLED
        locked.finished_at = timezone.now()
        locked.error_code = "CANCELLED_BY_OPERATOR"
        locked.revision += 1
        locked.save(update_fields=["status", "finished_at", "error_code", "revision", "updated_at"])
        record_event(
            actor_type="user",
            actor_id=actor,
            action="ingestion.staged_index.job_cancelled",
            outcome="success",
            organization_id=locked.organization_id,
            resource_type="staged_index_build_job",
            resource_id=str(locked.public_id),
        )
        _observe(StagedIndexBuildJobStatus.CANCELLED)
        return locked


def retry_build_job(*, job: StagedIndexBuildJob, actor: str) -> StagedIndexBuildJob:
    with transaction.atomic():
        set_tenant_context(job.organization_id)
        locked = StagedIndexBuildJob.objects.select_for_update().get(pk=job.pk)
        if (
            locked.status != StagedIndexBuildJobStatus.FAILED
            or locked.attempt >= locked.max_attempts
        ):
            raise BuildJobError("JOB_NOT_RETRYABLE")
        locked.status = StagedIndexBuildJobStatus.DISPATCH_PENDING
        locked.error_code = ""
        locked.finished_at = None
        locked.revision += 1
        locked.save(update_fields=["status", "error_code", "finished_at", "revision", "updated_at"])
        outbox, _ = StagedIndexBuildOutbox.objects.get_or_create(
            job=locked,
            defaults={
                "organization_id": locked.organization_id,
                "request_checksum": locked.request_checksum,
                "available_at": timezone.now(),
            },
        )
        outbox.published_at = None
        outbox.available_at = timezone.now()
        outbox.last_error_code = ""
        outbox.save(update_fields=["published_at", "available_at", "last_error_code", "updated_at"])
        record_event(
            actor_type="user",
            actor_id=actor,
            action="ingestion.staged_index.job_retried",
            outcome="success",
            organization_id=locked.organization_id,
            resource_type="staged_index_build_job",
            resource_id=str(locked.public_id),
        )
        transaction.on_commit(
            lambda: dispatch_outbox(
                limit=1,
                job_public_id=locked.public_id,
                organization_id=locked.organization_id,
            )
        )
        _observe(StagedIndexBuildJobStatus.DISPATCH_PENDING)
        return locked


def reconcile_build_jobs(*, limit: int = 100) -> int:
    """Bounded convergence for pending dispatch, stale claims and lost final job updates."""
    dispatch_outbox(limit=limit)
    cutoff = timezone.now() - timedelta(
        seconds=int(getattr(settings, "INGESTION_RUNNING_STALE_SECONDS", 300))
    )
    reconciled = 0
    from apps.tenancy.models import Organization

    candidates: list[tuple[int, int]] = []
    oldest_queue_age = 0.0
    for organization_id in Organization.objects.order_by("pk").values_list("pk", flat=True)[:100]:
        if len(candidates) >= limit:
            break
        with transaction.atomic():
            set_tenant_context(organization_id)
            oldest = (
                StagedIndexBuildJob.objects.filter(
                    organization_id=organization_id,
                    status__in=[
                        StagedIndexBuildJobStatus.DISPATCH_PENDING,
                        StagedIndexBuildJobStatus.QUEUED,
                    ],
                )
                .order_by("created_at")
                .values_list("created_at", flat=True)
                .first()
            )
            if oldest is not None:
                oldest_queue_age = max(
                    oldest_queue_age, max(0.0, (timezone.now() - oldest).total_seconds())
                )
            ids = (
                StagedIndexBuildJob.objects.filter(
                    organization_id=organization_id,
                    status=StagedIndexBuildJobStatus.RUNNING,
                    heartbeat_at__lt=cutoff,
                )
                .order_by("heartbeat_at", "pk")
                .values_list("pk", flat=True)[: limit - len(candidates)]
            )
            candidates.extend((organization_id, job_id) for job_id in ids)
    INGESTION_OLDEST_QUEUE_AGE.set(oldest_queue_age)
    for organization_id, job_id in candidates:
        with transaction.atomic():
            set_tenant_context(organization_id)
            job = StagedIndexBuildJob.objects.select_for_update().get(
                pk=job_id, organization_id=organization_id
            )
            exact = (
                IndexVersion.objects.filter(
                    organization_id=job.organization_id,
                    document_set_version_id=job.document_set_version_id,
                    embedding_profile_id=job.embedding_profile_id,
                    pipeline_fingerprint=job.pipeline_fingerprint,
                    status=IndexStatus.PROMOTABLE,
                    created_at__gte=job.claimed_at,
                )
                .order_by("-created_at", "-pk")
                .first()
            )
            if exact is not None:
                complete_build_job(job_id=job.pk, organization_id=job.organization_id, index=exact)
                INGESTION_RECONCILIATIONS.labels(outcome="linked").inc()
            else:
                job.status = StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED
                job.error_code = "WORKER_HEARTBEAT_STALE"
                job.revision += 1
                job.save(update_fields=["status", "error_code", "revision", "updated_at"])
                _observe(StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED, "worker_stale")
                INGESTION_RECONCILIATIONS.labels(outcome="required").inc()
            reconciled += 1
    return reconciled
