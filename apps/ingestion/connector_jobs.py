"""Typed connector adapters for the existing durable ingestion job and outbox."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import record_event
from apps.documents.models import DocumentSetStatus, DocumentVersion
from apps.ingestion.connections import verify_source_connection
from apps.ingestion.job_lifecycle import ACTIVE_STATES, TERMINAL_STATES, _canonical_checksum
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.models import (
    ConfluenceSyncRun,
    ConnectorSyncSchedule,
    ConnectorType,
    IngestionJobKind,
    ResourceSnapshot,
    RestSyncRun,
    Source,
    StagedIndexBuildJob,
    StagedIndexBuildJobStatus,
    StagedIndexBuildOutbox,
)
from apps.ingestion.vector_store import set_tenant_context

if TYPE_CHECKING:
    from apps.ingestion.confluence_sync import ConfluenceSyncClient
    from apps.ingestion.rest_sync import RestSyncClient
    from apps.tenancy.services import UserLike

ProtocolRun = RestSyncRun | ConfluenceSyncRun | ResourceSnapshot


class ConnectorJobError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _lock_organization(organization_id: int) -> None:
    from apps.tenancy.models import Organization

    # Operator admission/access changes lock the organization before jobs/sources.
    # Keep that order during writes too; document tenant FKs must not invert it.
    Organization.objects.select_for_update(no_key=True).get(pk=organization_id)


def source_checksum(source: Source) -> str:
    """Pin inputs and exact profile/contract references without copying their payloads."""
    profile = verify_source_connection(source)
    if profile is None or source.connection_id is None:
        raise ConnectorJobError("SOURCE_CONNECTION_REQUIRED")
    contract_checksum = (
        _canonical_checksum(source.rest_contract.definition) if source.rest_contract else None
    )
    return _canonical_checksum(
        {
            "schema": "ingestion-source/v1",
            "organization_id": source.organization_id,
            "source_id": source.pk,
            "document_set_id": source.document_set_id,
            "connection_id": source.connection_id,
            "connector_type": source.connector_type,
            "connector_config": source.connector_config,
            "rest_contract_id": source.rest_contract_id,
            "rest_contract_checksum": contract_checksum,
        }
    )


def _run_field(run: ProtocolRun) -> str:
    if isinstance(run, ResourceSnapshot):
        # Snapshot primary key is its owning common job's primary key.
        return "pk"
    return "rest_sync_run_id" if isinstance(run, RestSyncRun) else "confluence_sync_run_id"


def _load_run(job: StagedIndexBuildJob, *, lock: bool = False) -> ProtocolRun:
    if job.kind == IngestionJobKind.MCP_RESOURCE_SYNC:
        snapshots = ResourceSnapshot.objects.select_related("job__source__document_set", "schedule")
        if lock:
            snapshots = snapshots.select_for_update(of=("self",))
        return snapshots.get(pk=job.pk, organization_id=job.organization_id)
    if job.kind == IngestionJobKind.REST_SYNC and job.rest_sync_run_id is not None:
        query = RestSyncRun.objects.select_related(
            "source__document_set", "rest_profile", "rest_contract", "schedule"
        )
        if lock:
            query = query.select_for_update(of=("self",))
        return query.get(pk=job.rest_sync_run_id, organization_id=job.organization_id)
    if job.kind == IngestionJobKind.CONFLUENCE_SYNC and job.confluence_sync_run_id is not None:
        confluence_query = ConfluenceSyncRun.objects.select_related(
            "source__document_set", "confluence_profile", "schedule"
        )
        if lock:
            confluence_query = confluence_query.select_for_update(of=("self",))
        return confluence_query.get(
            pk=job.confluence_sync_run_id, organization_id=job.organization_id
        )
    raise ConnectorJobError("JOB_KIND_MISMATCH")


def _validate_inputs(job: StagedIndexBuildJob, run: ProtocolRun) -> None:
    from apps.ingestion.confluence_sync import _validate_runtime_grant as validate_confluence
    from apps.ingestion.rest_sync import _validate_runtime_grant as validate_rest
    from apps.tenancy.models import Organization, OrganizationStatus

    if not Organization.objects.filter(
        pk=job.organization_id, status=OrganizationStatus.ACTIVE
    ).exists():
        raise ConnectorJobError("TENANT_DISABLED")

    if (
        run.organization_id != job.organization_id
        or run.source_id != job.source_id
        or run.source.document_set is None
        or run.source.document_set.organization_id != job.organization_id
        or run.source.document_set.status != DocumentSetStatus.ACTIVE
    ):
        raise ConnectorJobError("INGESTION_JOB_SOURCE_INVALID")
    if source_checksum(run.source) != job.source_config_checksum:
        raise ConnectorJobError("SOURCE_CONFIG_CHANGED")
    if isinstance(run, RestSyncRun):
        validate_rest(run)
    elif isinstance(run, ConfluenceSyncRun):
        validate_confluence(run)
    else:
        from apps.ingestion.mcp_services import validate_mcp_source

        validate_mcp_source(run.source)


def _audit(job: StagedIndexBuildJob, action: str, *, actor: str = "ingestion-worker") -> None:
    record_event(
        actor_type="system" if actor in {"ingestion-worker", "connector-scheduler"} else "user",
        actor_id=actor,
        action=f"ingestion.connector_job.{action}",
        outcome="failure"
        if action in {"failed", "rejected", "reconciliation_required"}
        else "success",
        organization_id=job.organization_id,
        resource_type="ingestion_job",
        resource_id=str(job.public_id),
        request_id=job.request_id[:64],
        reason=job.error_code,
        after={"kind": job.kind, "state": job.status, "attempt": job.attempt},
    )


def _project(job: StagedIndexBuildJob) -> None:
    """Called under the job lock, in the same transaction as its state change."""
    run = _load_run(job, lock=True)
    if isinstance(run, ResourceSnapshot):
        if run.attempt != job.attempt:
            _set_write_context(job)
            ResourceSnapshot.objects.filter(pk=job.pk).update(
                attempt=job.attempt,
                snapshot_complete=False,
                material_change=False,
                discovered_count=0,
                changed_count=0,
                unchanged_count=0,
                missing_count=0,
                fetched_bytes=0,
                candidate_set_version=None,
            )
        return
    status = {
        "dispatch_pending": "queued",
        "queued": "queued",
        "running": "running",
        "retry_wait": "retry",
        "succeeded": "succeeded",
    }.get(job.status, "dead_letter")
    run.status = status
    run.attempt = job.attempt
    run.error_code = job.error_code
    run.finished_at = job.finished_at
    run.started_at = job.claimed_at
    run.save(
        update_fields=["status", "attempt", "error_code", "finished_at", "started_at", "updated_at"]
    )


def _save_state(job: StagedIndexBuildJob) -> None:
    job.revision += 1
    job.save()
    _project(job)


def create_connector_job(
    *, actor: UserLike, source: Source, max_attempts: int = 3, request_id: str = ""
) -> tuple[StagedIndexBuildJob, bool]:
    try:
        return _create_connector_job(
            actor=actor, source=source, max_attempts=max_attempts, request_id=request_id
        )
    except ConnectorJobError as exc:
        if exc.code == "SCENARIO_AUTHOR_REQUIRED":
            with transaction.atomic():
                set_tenant_context(source.organization_id)
                record_event(
                    actor_type="user",
                    actor_id=str(actor.pk),
                    action="ingestion.connector_job.authorization_denied",
                    outcome="deny",
                    organization_id=source.organization_id,
                    resource_type="source",
                    resource_id=str(source.pk),
                    reason=exc.code,
                    request_id=request_id[:64],
                )
        raise


@transaction.atomic
def _create_connector_job(
    *, actor: UserLike, source: Source, max_attempts: int, request_id: str
) -> tuple[StagedIndexBuildJob, bool]:
    from apps.tenancy.models import Organization
    from apps.tenancy.services import can_manage_documents

    set_tenant_context(source.organization_id)
    Organization.objects.select_for_update().get(pk=source.organization_id)
    source = Source.objects.select_for_update().get(
        pk=source.pk, organization_id=source.organization_id
    )
    if source.document_set is None or not can_manage_documents(
        actor, source.organization_id, document_set=source.document_set
    ):
        raise ConnectorJobError("SCENARIO_AUTHOR_REQUIRED")
    if isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
        raise ConnectorJobError("JOB_ATTEMPTS_INVALID")
    return _admit_connector_job(
        source=source, actor_id=str(actor.pk), max_attempts=max_attempts, request_id=request_id
    )


def _admit_connector_job(
    *,
    source: Source,
    actor_id: str,
    max_attempts: int = 3,
    request_id: str = "",
    schedule: ConnectorSyncSchedule | None = None,
    slot: datetime | None = None,
) -> tuple[StagedIndexBuildJob, bool]:
    """Internal admission after a scoped operator or persisted schedule authorization."""
    if schedule is not None and slot is not None:
        previous = StagedIndexBuildJob.objects.filter(
            Q(rest_sync_run__schedule=schedule, rest_sync_run__schedule_slot=slot)
            | Q(confluence_sync_run__schedule=schedule, confluence_sync_run__schedule_slot=slot)
            | Q(resource_snapshot__schedule=schedule, resource_snapshot__schedule_slot=slot),
            source=source,
            organization_id=source.organization_id,
        ).first()
        if previous is not None:
            return previous, False
    checksum = source_checksum(source)
    from apps.ingestion.rest_services import RestServiceError
    from apps.ingestion.source_revisions import assert_revision_sync, family_source_ids

    try:
        assert_revision_sync(source, scheduled=schedule is not None)
    except RestServiceError as exc:
        raise ConnectorJobError(exc.code) from exc
    siblings = family_source_ids(source)
    if (
        StagedIndexBuildJob.objects.filter(source_id__in=siblings, status__in=ACTIVE_STATES)
        .exclude(source=source)
        .exists()
        or RestSyncRun.objects.filter(
            source_id__in=siblings, status__in=["queued", "running", "retry"]
        )
        .exclude(source=source)
        .exists()
        or ConfluenceSyncRun.objects.filter(
            source_id__in=siblings, status__in=["queued", "running", "retry"]
        )
        .exclude(source=source)
        .exists()
    ):
        raise ConnectorJobError("SOURCE_BUSY")
    kinds: dict[str, str] = {
        ConnectorType.GENERIC_REST: IngestionJobKind.REST_SYNC,
        ConnectorType.CONFLUENCE_DC: IngestionJobKind.CONFLUENCE_SYNC,
        ConnectorType.MCP_RESOURCE: IngestionJobKind.MCP_RESOURCE_SYNC,
    }
    kind = kinds.get(source.connector_type)
    if kind is None:
        raise ConnectorJobError("JOB_KIND_MISMATCH")
    request_checksum = _canonical_checksum(
        {
            "schema": "ingestion-job/v1",
            "kind": kind,
            "source": checksum,
            "attempts": max_attempts,
            "schedule_id": schedule.pk if schedule else None,
            "slot": slot.isoformat() if slot else None,
        }
    )
    existing = StagedIndexBuildJob.objects.filter(
        source=source, organization_id=source.organization_id, status__in=ACTIVE_STATES
    ).first()
    if existing is not None:
        if existing.request_checksum != request_checksum:
            raise ConnectorJobError("SOURCE_BUSY")
        _validate_inputs(existing, _load_run(existing))
        return existing, False
    for model in (RestSyncRun, ConfluenceSyncRun):
        if model.objects.filter(source=source, status__in=["queued", "running", "retry"]).exists():
            raise ConnectorJobError("SOURCE_BUSY")
    job = StagedIndexBuildJob(
        organization_id=source.organization_id,
        kind=kind,
        source=source,
        source_config_checksum=checksum,
        request_checksum=request_checksum,
        pipeline_fingerprint=checksum,
        requested_by=actor_id,
        request_id=request_id[:128],
        max_attempts=max_attempts,
    )
    if kind == IngestionJobKind.REST_SYNC:
        if source.rest_profile_id is None or source.rest_contract_id is None:
            raise ConnectorJobError("INGESTION_JOB_SOURCE_INVALID")
        run: ProtocolRun = RestSyncRun(
            organization_id=source.organization_id,
            source=source,
            rest_profile_id=source.rest_profile_id,
            rest_contract_id=source.rest_contract_id,
            max_attempts=max_attempts,
            schedule=schedule,
            schedule_slot=slot,
        )
    elif kind == IngestionJobKind.CONFLUENCE_SYNC:
        if source.confluence_profile_id is None:
            raise ConnectorJobError("INGESTION_JOB_SOURCE_INVALID")
        run = ConfluenceSyncRun(
            organization_id=source.organization_id,
            source=source,
            confluence_profile_id=source.confluence_profile_id,
            max_attempts=max_attempts,
            schedule=schedule,
            schedule_slot=slot,
        )
    else:
        run = ResourceSnapshot(
            job=job, organization_id=source.organization_id, schedule=schedule, schedule_slot=slot
        )
    _validate_inputs(job, run)
    if isinstance(run, ResourceSnapshot):
        job.save()
        run.job = job
        run.save()
    else:
        run.full_clean()
        run.save()
        setattr(job, _run_field(run), run.pk)
        job.save()
    StagedIndexBuildOutbox.objects.create(
        organization_id=job.organization_id,
        job=job,
        request_checksum=job.request_checksum,
        available_at=timezone.now(),
    )
    _audit(job, "admitted", actor=actor_id)
    from apps.ingestion.job_lifecycle import dispatch_outbox

    transaction.on_commit(
        lambda: dispatch_outbox(
            limit=1, job_public_id=job.public_id, organization_id=job.organization_id
        )
    )
    return job, True


@transaction.atomic
def create_scheduled_connector_job(
    *, schedule: ConnectorSyncSchedule, slot: datetime
) -> tuple[StagedIndexBuildJob, bool]:
    from apps.tenancy.models import Organization

    set_tenant_context(schedule.organization_id)
    Organization.objects.select_for_update().get(pk=schedule.organization_id)
    schedule = ConnectorSyncSchedule.objects.select_for_update().get(
        pk=schedule.pk, organization_id=schedule.organization_id
    )
    if not schedule.enabled:
        raise ConnectorJobError("SCHEDULE_DISABLED")
    source = Source.objects.select_for_update().get(
        pk=schedule.source_id, organization_id=schedule.organization_id
    )
    if source.connector_type == ConnectorType.MCP_RESOURCE and (
        not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False)
        or schedule.automation_mode not in {"draft_only", "stage_only", "promote_if_safe"}
    ):
        raise ConnectorJobError("MCP_RESOURCE_SCHEDULE_UNAVAILABLE")
    # The existing persisted schedule is a system delegation; live source, profile,
    # set quarantine and exact tenant/set grants are still checked at admission and I/O.
    return _admit_connector_job(
        source=source, actor_id="connector-scheduler", schedule=schedule, slot=slot
    )


@transaction.atomic(durable=True)
def claim_connector_job(*, public_id: str, organization_id: int) -> ProtocolRun | None:
    set_tenant_context(organization_id)
    _lock_organization(organization_id)
    job = StagedIndexBuildJob.objects.select_for_update().get(
        public_id=public_id, organization_id=organization_id
    )
    run = _load_run(job, lock=True)
    if job.status not in {"dispatch_pending", "queued"}:
        return None
    try:
        _validate_inputs(job, run)
    except Exception as exc:
        job.status = StagedIndexBuildJobStatus.FAILED
        code = str(getattr(exc, "code", "INGESTION_JOB_INPUT_INVALID"))
        job.error_code = (
            code if code.isupper() and len(code) <= 64 else "INGESTION_JOB_INPUT_INVALID"
        )
        job.finished_at = timezone.now()
        _save_state(job)
        _audit(job, "rejected")
        return None
    if job.attempt >= job.max_attempts:
        job.status = StagedIndexBuildJobStatus.FAILED
        job.error_code = "MAX_ATTEMPTS_EXCEEDED"
        job.finished_at = timezone.now()
        _save_state(job)
        _audit(job, "rejected")
        return None
    job.status = StagedIndexBuildJobStatus.RUNNING
    job.attempt += 1
    job.claimed_at = job.heartbeat_at = timezone.now()
    job.error_code = ""
    job.finished_at = None
    _save_state(job)
    _audit(job, "claimed")
    return _load_run(job)


@contextmanager
def connector_write(run: ProtocolRun) -> Iterator[StagedIndexBuildJob | None]:
    """Fence each snapshot write before documents/cursors, keeping remote reads outside."""
    with transaction.atomic():
        set_tenant_context(run.organization_id)
        _lock_organization(run.organization_id)
        job = (
            StagedIndexBuildJob.objects.select_for_update()
            .filter(organization_id=run.organization_id, **{_run_field(run): run.pk})
            .first()
        )
        if job is not None:
            if job.status != StagedIndexBuildJobStatus.RUNNING or job.attempt != run.attempt:
                raise ConnectorJobError("CONNECTOR_ATTEMPT_FENCED")
            current = _load_run(job, lock=True)
            current.source = Source.objects.select_for_update().get(
                pk=current.source_id, organization_id=job.organization_id
            )
            _validate_inputs(job, current)
            if current.attempt != run.attempt or current.status != "running":
                raise ConnectorJobError("CONNECTOR_ATTEMPT_FENCED")
            _set_write_context(job)
            job.heartbeat_at = timezone.now()
            job.save(update_fields=["heartbeat_at", "updated_at"])
        yield job


def _set_write_context(job: StagedIndexBuildJob) -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.ingestion_job_id', %s, true), "
                "set_config('app.ingestion_job_attempt', %s, true)",
                [str(job.pk), str(job.attempt)],
            )


def cleanup_connector_uploads(*, organization_id: int, created_keys: list[str]) -> None:
    """Delete only newly owned blobs proven unreferenced after rollback, never on uncertainty."""
    from apps.documents.services import _best_effort_delete

    for key in created_keys:
        try:
            with transaction.atomic():
                set_tenant_context(organization_id)
                referenced = DocumentVersion.objects.filter(
                    organization_id=organization_id, object_key=key
                ).exists()
        except Exception:
            # A lost commit acknowledgement is not proof that metadata rolled back.
            return
        if not referenced:
            _best_effort_delete(key)


def complete_connector_snapshot(run: ProtocolRun) -> None:
    """The caller holds connector_write across candidate creation and final run evidence."""
    job = (
        StagedIndexBuildJob.objects.select_for_update()
        .filter(organization_id=run.organization_id, **{_run_field(run): run.pk})
        .first()
    )
    if job is None:
        return
    if job.status != "running" or job.attempt != run.attempt:
        raise ConnectorJobError("CONNECTOR_ATTEMPT_FENCED")
    job.status = StagedIndexBuildJobStatus.SUCCEEDED
    job.finished_at = job.heartbeat_at = timezone.now()
    # Final snapshot evidence and the compatibility status are written by the caller
    # before this transaction commits; the deferred database projection checks both.
    job.revision += 1
    job.save()
    _audit(job, "succeeded")


@transaction.atomic
def fail_connector_job(
    run: ProtocolRun, *, error_code: str, ambiguous: bool = False, retryable: bool = False
) -> str:
    set_tenant_context(run.organization_id)
    _lock_organization(run.organization_id)
    job = StagedIndexBuildJob.objects.select_for_update().get(
        organization_id=run.organization_id, **{_run_field(run): run.pk}
    )
    if job.status != "running" or job.attempt != run.attempt:
        return job.status
    job.error_code = (
        error_code if error_code.isupper() and len(error_code) <= 64 else "CONNECTOR_SYNC_FAILED"
    )
    if ambiguous:
        job.status = StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED
    elif retryable and job.attempt < job.max_attempts:
        job.status = StagedIndexBuildJobStatus.RETRY_WAIT
        outbox = StagedIndexBuildOutbox.objects.select_for_update().get(job=job)
        outbox.published_at = None
        outbox.available_at = timezone.now() + timedelta(seconds=30)
        outbox.save(update_fields=["published_at", "available_at", "updated_at"])
    else:
        job.status = StagedIndexBuildJobStatus.FAILED
    job.finished_at = timezone.now() if job.status in TERMINAL_STATES else None
    _save_state(job)
    _audit(job, "failed")
    return job.status


def change_connector_job(
    *, public_id: str, organization_id: int, actor: UserLike, action: str
) -> StagedIndexBuildJob:
    """Exact data-manager action; ambiguous outcomes never enter automatic retry."""
    try:
        return _change_connector_job(
            public_id=public_id, organization_id=organization_id, actor=actor, action=action
        )
    except ConnectorJobError as exc:
        if exc.code == "SCENARIO_AUTHOR_REQUIRED":
            with transaction.atomic():
                set_tenant_context(organization_id)
                record_event(
                    actor_type="user",
                    actor_id=str(actor.pk),
                    action="ingestion.connector_job.authorization_denied",
                    outcome="deny",
                    organization_id=organization_id,
                    resource_type="ingestion_job",
                    resource_id=public_id,
                    reason=exc.code,
                )
        raise


@transaction.atomic
def _change_connector_job(
    *, public_id: str, organization_id: int, actor: UserLike, action: str
) -> StagedIndexBuildJob:
    from apps.tenancy.models import Organization
    from apps.tenancy.services import can_manage_documents

    set_tenant_context(organization_id)
    Organization.objects.select_for_update().get(pk=organization_id)
    job = StagedIndexBuildJob.objects.select_for_update().get(
        public_id=public_id, organization_id=organization_id
    )
    run = _load_run(job, lock=True)
    if run.source.document_set is None or not can_manage_documents(
        actor, organization_id, document_set=run.source.document_set
    ):
        raise ConnectorJobError("SCENARIO_AUTHOR_REQUIRED")
    if action == "cancel":
        if job.status in TERMINAL_STATES:
            return job
        if job.status == "reconciliation_required":
            raise ConnectorJobError("JOB_RECONCILIATION_REQUIRED")
        if (
            job.status == "running"
            and isinstance(run, RestSyncRun)
            and run.rest_profile.method == "POST"
        ):
            job.status = StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED
            job.error_code = "REST_POST_CANCEL_OUTCOME_UNKNOWN"
            job.finished_at = None
        else:
            job.status = StagedIndexBuildJobStatus.CANCELLED
            job.error_code = "CANCELLED_BY_OPERATOR"
            job.finished_at = timezone.now()
    elif action == "retry":
        if job.status not in {"failed", "cancelled"} or job.attempt >= job.max_attempts:
            raise ConnectorJobError("JOB_NOT_RETRYABLE")
        _validate_inputs(job, run)
        job.status = StagedIndexBuildJobStatus.DISPATCH_PENDING
        job.error_code = ""
        job.finished_at = None
        outbox = StagedIndexBuildOutbox.objects.select_for_update().get(job=job)
        outbox.published_at = None
        outbox.available_at = timezone.now()
        outbox.last_error_code = ""
        outbox.save(update_fields=["published_at", "available_at", "last_error_code", "updated_at"])
        from apps.ingestion.job_lifecycle import dispatch_outbox

        transaction.on_commit(
            lambda: dispatch_outbox(
                limit=1, job_public_id=job.public_id, organization_id=organization_id
            )
        )
    else:
        raise ConnectorJobError("JOB_ACTION_INVALID")
    _save_state(job)
    _audit(job, action, actor=str(actor.pk))
    return job


def execute_connector_job(
    *,
    public_id: str,
    organization_id: int,
    rest_client: RestSyncClient | None = None,
    confluence_client: ConfluenceSyncClient | None = None,
) -> str:
    from apps.documents.services import DocumentError
    from apps.ingestion.confluence import ConfluenceDataCenterClient, ConfluenceError
    from apps.ingestion.confluence_sync import _execute_snapshot as confluence_snapshot
    from apps.ingestion.connections import ConnectionError
    from apps.ingestion.rest import GovernedRestClient, RestPullError
    from apps.ingestion.rest_sync import _execute_snapshot as rest_snapshot
    from apps.ingestion.services import source_lock

    run = claim_connector_job(public_id=public_id, organization_id=organization_id)
    if run is None:
        return "not_claimed"
    try:
        with source_lock(run.source_id) as acquired:
            if not acquired:
                raise ConnectorJobError("SOURCE_BUSY")
            if isinstance(run, RestSyncRun):
                rest_snapshot(run, rest_client or GovernedRestClient())
            elif isinstance(run, ConfluenceSyncRun):
                confluence_snapshot(run, confluence_client or ConfluenceDataCenterClient())
            else:
                from apps.ingestion.mcp_sync import execute_snapshot

                execute_snapshot(run)
    except (
        RestPullError,
        ConfluenceError,
        DocumentError,
        ConnectorJobError,
        ConnectionError,
        McpResourceError,
    ) as exc:
        code = str(getattr(exc, "code", "CONNECTOR_SYNC_FAILED"))
        return fail_connector_job(
            run,
            error_code=code,
            ambiguous=code == "REST_POST_OUTCOME_UNKNOWN",
            retryable=code
            in {"SOURCE_BUSY", "REST_UPSTREAM_UNAVAILABLE", "CONFLUENCE_UPSTREAM_UNAVAILABLE"},
        )
    except Exception:
        # Unknown interruption may have persisted a blob or completed an external request.
        return fail_connector_job(run, error_code="CONNECTOR_OUTCOME_UNKNOWN", ambiguous=True)
    return "succeeded"


def reconcile_connector_jobs(*, limit: int = 100) -> int:
    """Fence expired owners; a snapshot cannot be reconstructed from partial cursors."""
    from apps.tenancy.models import Organization

    cutoff = timezone.now() - timedelta(
        seconds=int(getattr(settings, "INGESTION_RUNNING_STALE_SECONDS", 300))
    )
    count = 0
    for organization_id in Organization.objects.order_by("pk").values_list("pk", flat=True)[:100]:
        if count >= limit:
            break
        with transaction.atomic():
            set_tenant_context(organization_id)
            _lock_organization(organization_id)
            jobs = list(
                StagedIndexBuildJob.objects.select_for_update(skip_locked=True)
                .filter(
                    organization_id=organization_id,
                    kind__in=[
                        IngestionJobKind.REST_SYNC,
                        IngestionJobKind.CONFLUENCE_SYNC,
                        IngestionJobKind.MCP_RESOURCE_SYNC,
                    ],
                    status="running",
                    heartbeat_at__lt=cutoff,
                )
                .order_by("heartbeat_at", "pk")[: limit - count]
            )
            for job in jobs:
                job.status = StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED
                job.error_code = "WORKER_HEARTBEAT_STALE"
                _save_state(job)
                _audit(job, "reconciliation_required")
                count += 1
            if count < limit:
                queued = list(
                    StagedIndexBuildJob.objects.select_for_update(of=("self",), skip_locked=True)
                    .filter(
                        organization_id=organization_id,
                        kind__in=[
                            IngestionJobKind.REST_SYNC,
                            IngestionJobKind.CONFLUENCE_SYNC,
                            IngestionJobKind.MCP_RESOURCE_SYNC,
                        ],
                        status="queued",
                        queued_at__lt=cutoff,
                        outbox__published_at__isnull=False,
                    )
                    .order_by("queued_at", "pk")[: limit - count]
                )
                for job in queued:
                    outbox = StagedIndexBuildOutbox.objects.select_for_update().get(job=job)
                    outbox.published_at = None
                    outbox.available_at = timezone.now()
                    outbox.last_error_code = "DELIVERY_NOT_CLAIMED"
                    outbox.save(
                        update_fields=[
                            "published_at",
                            "available_at",
                            "last_error_code",
                            "updated_at",
                        ]
                    )
                    job.status = StagedIndexBuildJobStatus.DISPATCH_PENDING
                    _save_state(job)
                    _audit(job, "delivery_redriven")
                    count += 1
        dispatch_connector_completion(organization_id=organization_id, limit=limit)
    return count


def dispatch_connector_completion(
    *, organization_id: int, public_id: str | None = None, limit: int = 100
) -> int:
    """Persist preparation handoff or legacy delivery; neither depends on broker uptime."""
    from apps.ingestion.connector_preparation import prepare_connector_snapshot
    from apps.ingestion.tasks import apply_connector_automation_task

    with transaction.atomic():
        set_tenant_context(organization_id)
        query = StagedIndexBuildOutbox.objects.filter(
            Q(completion_available_at__isnull=True)
            | Q(completion_available_at__lte=timezone.now()),
            Q(
                job__rest_sync_run__schedule__isnull=False,
                job__rest_sync_run__candidate_set_version__isnull=False,
            )
            | Q(
                job__confluence_sync_run__schedule__isnull=False,
                job__confluence_sync_run__candidate_set_version__isnull=False,
            )
            | Q(
                job__resource_snapshot__schedule__isnull=False,
                job__resource_snapshot__candidate_set_version__isnull=False,
            ),
            organization_id=organization_id,
            job__status="succeeded",
            job__kind__in=[
                IngestionJobKind.REST_SYNC,
                IngestionJobKind.CONFLUENCE_SYNC,
                IngestionJobKind.MCP_RESOURCE_SYNC,
            ],
            completion_published_at__isnull=True,
        )
        if public_id is not None:
            query = query.filter(job__public_id=public_id)
        job_ids = list(query.order_by("pk").values_list("job_id", flat=True)[:limit])
    published = 0
    for job_id in job_ids:
        needs_publication = False
        waiting_preparation = False
        with transaction.atomic():
            set_tenant_context(organization_id)
            _lock_organization(organization_id)
            job = StagedIndexBuildJob.objects.select_for_update().get(
                pk=job_id, organization_id=organization_id
            )
            outbox = StagedIndexBuildOutbox.objects.select_for_update().get(job=job)
            if outbox.completion_published_at is not None or job.status != "succeeded":
                continue
            if (
                outbox.completion_available_at is not None
                and outbox.completion_available_at > timezone.now()
            ):
                continue
            run = _load_run(job)
            if not run.schedule_id or not run.candidate_set_version_id or not run.snapshot_complete:
                continue
            outbox.completion_publish_attempts += 1
            shared_preparation = (
                job.preparation_job_id is not None
                or (
                    run.schedule is not None
                    and run.schedule.automation_mode in {"stage_only", "promote_if_safe"}
                )
                or isinstance(run, ResourceSnapshot)
            )
            try:
                with transaction.atomic():
                    if shared_preparation:
                        preparation = prepare_connector_snapshot(
                            job_id=job.pk, organization_id=organization_id
                        )
                        if (
                            run.schedule is not None
                            and run.schedule.automation_mode == "promote_if_safe"
                        ):
                            needs_publication = (
                                preparation is not None and preparation.status == "succeeded"
                            )
                            waiting_preparation = not needs_publication
                    else:
                        apply_connector_automation_task.apply_async(
                            args=[run.schedule_id, run.candidate_set_version_id, organization_id],
                            queue="ingestion",
                            retry=False,
                        )
            except Exception as exc:
                code = str(getattr(exc, "code", "PREPARATION_INTERNAL_ERROR"))
                safe_code = (
                    code
                    if code.isascii()
                    and code.isupper()
                    and len(code) <= 64
                    and code.replace("_", "").isalnum()
                    else "PREPARATION_INTERNAL_ERROR"
                )
                outbox.completion_error_code = (
                    safe_code if shared_preparation else "BROKER_UNAVAILABLE"
                )
                # Admission blockers create no build or paid retry. Rechecking the
                # same intent is bounded; transport retries belong to the build outbox.
                outbox.completion_available_at = timezone.now() + timedelta(
                    seconds=300 if shared_preparation else 30
                )
            else:
                if needs_publication or waiting_preparation:
                    outbox.completion_available_at = timezone.now() + timedelta(seconds=300)
                else:
                    outbox.completion_published_at = timezone.now()
                    published += 1
                outbox.completion_error_code = (
                    "PUBLICATION_PREPARATION_PENDING" if waiting_preparation else ""
                )
            outbox.save(
                update_fields=[
                    "completion_published_at",
                    "completion_available_at",
                    "completion_error_code",
                    "completion_publish_attempts",
                    "updated_at",
                ]
            )
        if needs_publication:
            from apps.releases.source_publication import continue_source_publication

            error = ""
            try:
                continue_source_publication(job_id=job_id, organization_id=organization_id)
            except Exception as exc:
                raw = str(getattr(exc, "code", "PUBLICATION_INTERNAL_ERROR"))
                error = (
                    raw
                    if (
                        raw.isascii()
                        and raw.isupper()
                        and len(raw) <= 64
                        and raw.replace("_", "").isalnum()
                    )
                    else "PUBLICATION_INTERNAL_ERROR"
                )
            with transaction.atomic():
                set_tenant_context(organization_id)
                _lock_organization(organization_id)
                outbox = StagedIndexBuildOutbox.objects.select_for_update().get(job_id=job_id)
                if outbox.completion_published_at is not None:
                    continue
                outbox.completion_error_code = error
                if error:
                    outbox.completion_available_at = timezone.now() + timedelta(seconds=300)
                else:
                    outbox.completion_published_at = timezone.now()
                    published += 1
                outbox.save(
                    update_fields=[
                        "completion_published_at",
                        "completion_available_at",
                        "completion_error_code",
                        "updated_at",
                    ]
                )
    return published
