from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.documents import storage
from apps.documents.models import DocumentSetVersion
from apps.ingestion.job_lifecycle import (
    BuildJobError,
    cancel_build_job,
    claim_build_job,
    compatible_worker_available,
    complete_build_job,
    config_fingerprint,
    create_build_job,
    dispatch_outbox,
    fail_build_job,
    reconcile_build_jobs,
    record_worker_heartbeat,
    update_progress,
)
from apps.ingestion.models import (
    EmbeddingProfile,
    IndexStatus,
    IndexVersion,
    IngestionWorkerHeartbeat,
    StagedIndexBuildJob,
    StagedIndexBuildJobStatus,
)
from apps.ingestion.tasks import run_staged_index_build_job
from apps.ingestion.tests.test_staged_build import _granted_profile, _published_set_version
from apps.ingestion.vector_store import drop_store
from apps.tenancy.models import Organization


@pytest.fixture
def lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Organization, DocumentSetVersion, EmbeddingProfile]:
    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)
    org = Organization.objects.create(slug="jobs", name="Jobs")
    return org, _published_set_version(org, ["bounded text"]), _granted_profile(org)


@pytest.mark.django_db
def test_request_is_durable_idempotent_and_checksum_immutable(
    lineage: tuple[Organization, DocumentSetVersion, EmbeddingProfile],
) -> None:
    org, set_version, profile = lineage
    first, created = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    replay, replay_created = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    assert created is True and replay_created is False
    assert replay.pk == first.pk
    assert len(first.request_checksum) == 64
    assert first.outbox.request_checksum == first.request_checksum
    assert first.organization_id == org.pk


@pytest.mark.django_db
def test_claim_redelivery_progress_and_cancel_are_terminal(
    lineage: tuple[Organization, DocumentSetVersion, EmbeddingProfile],
) -> None:
    org, set_version, profile = lineage
    job, _ = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    job.status = StagedIndexBuildJobStatus.QUEUED
    job.save(update_fields=["status", "updated_at"])
    claimed = claim_build_job(public_id=str(job.public_id), organization_id=org.pk)
    assert claimed is not None and claimed.attempt == 1
    assert claim_build_job(public_id=str(job.public_id), organization_id=org.pk) is None
    update_progress(job_id=job.pk, organization_id=org.pk, documents=1, chunks=2)
    with pytest.raises(BuildJobError, match="PROGRESS_NOT_MONOTONIC"):
        update_progress(job_id=job.pk, organization_id=org.pk, documents=0, chunks=2)
    cancel_build_job(job=job, actor="owner")
    job.refresh_from_db()
    assert job.status == StagedIndexBuildJobStatus.CANCELLED


@pytest.mark.django_db
def test_late_result_cannot_resurrect_cancelled_job(
    lineage: tuple[Organization, DocumentSetVersion, EmbeddingProfile],
) -> None:
    org, set_version, profile = lineage
    job, _ = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    cancel_build_job(job=job, actor="owner")
    index = IndexVersion.objects.create(
        organization=org,
        document_set_version=set_version,
        embedding_profile=profile,
        dimensions=profile.dimensions,
        index_type=profile.index_type,
        version=1,
        status=IndexStatus.PROMOTABLE,
        pipeline_fingerprint=job.pipeline_fingerprint,
    )
    complete_build_job(job_id=job.pk, organization_id=org.pk, index=index)
    job.refresh_from_db()
    assert job.status == StagedIndexBuildJobStatus.CANCELLED
    assert job.result_index_version_id is None
    index.refresh_from_db()
    assert index.status == IndexStatus.FAILED


@pytest.mark.django_db
def test_ambiguous_failure_requires_reconciliation(
    lineage: tuple[Organization, DocumentSetVersion, EmbeddingProfile],
) -> None:
    org, set_version, profile = lineage
    job, _ = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    fail_build_job(
        job_id=job.pk,
        organization_id=org.pk,
        error_code="PROVIDER_OUTCOME_UNKNOWN",
        ambiguous=True,
    )
    job.refresh_from_db()
    assert job.status == StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED
    assert job.finished_at is None


@pytest.mark.django_db
def test_broker_failure_retains_durable_pending_intent(
    lineage: tuple[Organization, DocumentSetVersion, EmbeddingProfile],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, set_version, profile = lineage
    job, _ = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )

    def unavailable(*args: object, **kwargs: object) -> None:
        raise OSError("broker unavailable")

    monkeypatch.setattr("apps.ingestion.tasks.run_staged_index_build_job.apply_async", unavailable)
    assert dispatch_outbox(limit=1, organization_id=org.pk) == 0
    job.refresh_from_db()
    job.outbox.refresh_from_db()
    assert job.status == StagedIndexBuildJobStatus.DISPATCH_PENDING
    assert job.outbox.published_at is None
    assert job.outbox.last_error_code == "BROKER_UNAVAILABLE"


@pytest.mark.django_db
def test_reconciler_links_exact_promotable_result_after_lost_final_update(
    lineage: tuple[Organization, DocumentSetVersion, EmbeddingProfile], settings: object
) -> None:
    org, set_version, profile = lineage
    job, _ = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    stale = timezone.now() - timedelta(minutes=10)
    StagedIndexBuildJob.objects.filter(pk=job.pk).update(
        status=StagedIndexBuildJobStatus.RUNNING,
        claimed_at=stale,
        heartbeat_at=stale,
        attempt=1,
    )
    job.outbox.published_at = stale
    job.outbox.save(update_fields=["published_at", "updated_at"])
    index = IndexVersion.objects.create(
        organization=org,
        document_set_version=set_version,
        embedding_profile=profile,
        dimensions=profile.dimensions,
        index_type=profile.index_type,
        version=1,
        status=IndexStatus.PROMOTABLE,
        pipeline_fingerprint=job.pipeline_fingerprint,
    )
    settings.INGESTION_RUNNING_STALE_SECONDS = 1  # type: ignore[attr-defined]
    assert reconcile_build_jobs(limit=10) == 1
    job.refresh_from_db()
    assert job.status == StagedIndexBuildJobStatus.SUCCEEDED
    assert job.result_index_version_id == index.pk


@pytest.mark.django_db
def test_worker_compatibility_rejects_stale_and_config_drift(settings: object) -> None:
    settings.INGESTION_WORKER_HEARTBEAT_TTL_SECONDS = 30  # type: ignore[attr-defined]
    heartbeat = record_worker_heartbeat()
    assert compatible_worker_available()
    heartbeat.config_fingerprint = "0" * 64
    heartbeat.save(update_fields=["config_fingerprint", "updated_at"])
    assert not compatible_worker_available()
    heartbeat.config_fingerprint = config_fingerprint()
    heartbeat.last_seen_at = timezone.now() - timedelta(seconds=31)
    heartbeat.save(update_fields=["config_fingerprint", "last_seen_at", "updated_at"])
    assert not compatible_worker_available()


@pytest.mark.django_db
def test_constraints_bound_attempts_and_active_duplicates(
    lineage: tuple[Organization, DocumentSetVersion, EmbeddingProfile],
) -> None:
    org, set_version, profile = lineage
    job, _ = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    job.request_checksum = "f" * 64
    with pytest.raises(IntegrityError), transaction.atomic():
        StagedIndexBuildJob.objects.create(
            organization=org,
            document_set_version=set_version,
            embedding_profile=profile,
            request_checksum="e" * 64,
            pipeline_fingerprint=job.pipeline_fingerprint,
            requested_by="other",
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        StagedIndexBuildJob.objects.filter(pk=job.pk).update(attempt=4, max_attempts=3)


@pytest.mark.django_db
def test_metric_contract_has_only_bounded_labels() -> None:
    from apps.observability.metrics import INGESTION_BUILD_JOBS, INGESTION_RECONCILIATIONS

    assert INGESTION_BUILD_JOBS._labelnames == ("status", "failure_class")
    assert INGESTION_RECONCILIATIONS._labelnames == ("outcome",)
    forbidden = {"organization", "tenant", "job", "document", "worker", "instance"}
    assert forbidden.isdisjoint(INGESTION_BUILD_JOBS._labelnames)


@pytest.mark.django_db
def test_worker_heartbeat_persists_no_endpoint_or_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    record_worker_heartbeat()
    persisted = " ".join(
        str(value) for value in IngestionWorkerHeartbeat.objects.values().get().values()
    )
    assert "test-access" not in persisted
    assert "test-secret" not in persisted


@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL constraint proof")
@pytest.mark.django_db
def test_postgres_partial_unique_constraint_is_concurrency_backstop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)
    org = Organization.objects.create(slug="pg-jobs", name="PG Jobs")
    set_version = _published_set_version(org, ["text"])
    profile = _granted_profile(org)
    first, _ = create_build_job(
        document_set_version=set_version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        StagedIndexBuildJob.objects.create(
            organization=org,
            document_set_version=set_version,
            embedding_profile=profile,
            request_checksum="a" * 64,
            pipeline_fingerprint=first.pipeline_fingerprint,
            requested_by="racer",
        )


@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL RLS proof")
@pytest.mark.django_db
def test_job_and_outbox_force_rls_under_non_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)
    org = Organization.objects.create(slug="rls-job", name="RLS Job")
    other = Organization.objects.create(slug="rls-other", name="RLS Other")
    version = _published_set_version(org, ["text"])
    profile = _granted_profile(org)
    create_build_job(
        document_set_version=version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="owner",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "DO $$ BEGIN CREATE ROLE ingestion_job_rls_probe NOSUPERUSER NOLOGIN; "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
        cursor.execute(
            "GRANT SELECT ON ingestion_stagedindexbuildjob, "
            "ingestion_stagedindexbuildoutbox TO ingestion_job_rls_probe"
        )
        cursor.execute(
            "GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) "
            "TO ingestion_job_rls_probe"
        )
        for scope, expected in (("", 0), (str(other.pk), 0), (str(org.pk), 1)):
            cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [scope])
            cursor.execute("SET ROLE ingestion_job_rls_probe")
            try:
                cursor.execute("SELECT count(*) FROM ingestion_stagedindexbuildjob")
                assert cursor.fetchone()[0] == expected
                cursor.execute("SELECT count(*) FROM ingestion_stagedindexbuildoutbox")
                assert cursor.fetchone()[0] == expected
            finally:
                cursor.execute("RESET ROLE")
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname IN "
            "('ingestion_stagedindexbuildjob', 'ingestion_stagedindexbuildoutbox')"
        )
        assert all(row[1:] == (True, True) for row in cursor.fetchall())


@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL worker RLS proof")
@pytest.mark.django_db(transaction=True)
def test_durable_worker_builds_with_pinned_artifacts_as_non_owner(
    monkeypatch: pytest.MonkeyPatch, settings: object
) -> None:
    """Exercise the real commit boundary that owner-backed/transactional tests can mask."""

    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"  # type: ignore[attr-defined]
    storage.reset_in_memory_store()
    org = Organization.objects.create(slug="worker-rls", name="Worker RLS")
    version = _published_set_version(org, ["bounded text"])
    profile = _granted_profile(org)
    chunking = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.CHUNKING_PROFILE,
        logical_id="worker-chunking",
        body={
            "api_version": "agenthub/chunking/v1",
            "kind": "ChunkingProfile",
            "strategy": "characters",
            "size": 500,
            "overlap": 50,
            "max_chunks": 100,
        },
        created_by="owner",
    )
    job, _ = create_build_job(
        document_set_version=version,
        embedding_profile=profile,
        ocr_profile=None,
        chunking_profile=chunking,
        actor="owner",
    )
    job.status = StagedIndexBuildJobStatus.QUEUED
    job.save(update_fields=["status", "updated_at"])

    role = "ingestion_worker_scope_probe"
    with connection.cursor() as cursor:
        cursor.execute(
            f'DO $$ BEGIN CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN; '
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"  # noqa: S608
        )
        cursor.execute(
            f'GRANT SELECT, UPDATE ON ingestion_stagedindexbuildjob TO "{role}"'  # noqa: S608
        )
        cursor.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{role}"')  # noqa: S608
        cursor.execute(
            f'GRANT UPDATE ON documents_documentsetversion, documents_documentset TO "{role}"'  # noqa: S608
        )
        cursor.execute(
            f'GRANT SELECT, INSERT, UPDATE ON ingestion_ingestionworkerheartbeat TO "{role}"'  # noqa: S608
        )
        cursor.execute(
            f'GRANT INSERT, UPDATE ON ingestion_indexversion TO "{role}"'  # noqa: S608
        )
        cursor.execute(
            f'GRANT UPDATE ON documents_documentversion TO "{role}"'  # noqa: S608
        )
        cursor.execute(f'GRANT INSERT ON audit_auditevent TO "{role}"')  # noqa: S608
        cursor.execute(
            f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'  # noqa: S608
        )
        cursor.execute(
            f"GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint), "
            f"agenthub_provision_index_store(bigint), agenthub_drop_index_store(bigint) "
            f'TO "{role}"'  # noqa: S608
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SET SESSION AUTHORIZATION "{role}"')  # noqa: S608
        try:
            run_staged_index_build_job.push_request(headers={"organization_id": org.pk})
            try:
                result = run_staged_index_build_job.run(str(job.public_id))
            finally:
                run_staged_index_build_job.pop_request()
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET SESSION AUTHORIZATION")

        job.refresh_from_db()
        assert result.startswith("built:")
        assert job.status == StagedIndexBuildJobStatus.SUCCEEDED
        assert job.result_index_version is not None
        assert job.result_index_version.chunking_profile_id == chunking.pk
        drop_store(job.result_index_version)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET SESSION AUTHORIZATION")
            cursor.execute(f'DROP OWNED BY "{role}"')  # noqa: S608
            cursor.execute(f'DROP ROLE "{role}"')  # noqa: S608
