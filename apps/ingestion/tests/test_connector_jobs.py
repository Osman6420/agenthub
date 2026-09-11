"""Real common-job/protocol boundaries; only remote payload delivery is synthetic."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connection,
    transaction,
)
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.documents import storage
from apps.documents.models import Document, DocumentVersion
from apps.ingestion.connector_jobs import (
    ConnectorJobError,
    change_connector_job,
    claim_connector_job,
    cleanup_connector_uploads,
    connector_write,
    create_connector_job,
    dispatch_connector_completion,
    execute_connector_job,
    fail_connector_job,
    reconcile_connector_jobs,
)
from apps.ingestion.job_lifecycle import (
    BuildJobError,
    cancel_build_job,
    claim_build_job,
    dispatch_outbox,
    retry_build_job,
    update_progress,
)
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    RestDocumentCursor,
    RestSyncRun,
    Source,
    StagedIndexBuildJob,
    StagedIndexBuildOutbox,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest import RestPullItem
from apps.ingestion.rest_sync import _execute_snapshot, execute_rest_sync
from apps.ingestion.scheduler import dispatch_due_schedules
from apps.ingestion.tests.test_confluence import _sync_page
from apps.ingestion.tests.test_confluence import _SyncClient as ConfluenceClient
from apps.ingestion.tests.test_confluence import governed_source as governed_source
from apps.ingestion.tests.test_rest_pull import _SyncClient as RestClient
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_delivery(monkeypatch, settings):
    storage.reset_in_memory_store()
    settings.CONFLUENCE_NETWORK_POLICIES = {"corp-confluence": ["10.0.0.0/8"]}
    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)
    yield
    storage.reset_in_memory_store()


def _rest_client():
    return RestClient([RestPullItem("a", "r1", "Doc A", False, "")], {"a": b"bounded content"})


def _rest_run(job: StagedIndexBuildJob) -> RestSyncRun:
    run = job.rest_sync_run
    assert isinstance(run, RestSyncRun)
    return run


def test_admission_is_atomic_idempotent_and_kind_scoped(governed_rest, monkeypatch):
    _, author, org, _, source = governed_rest
    job, created = create_connector_job(actor=author, source=source)
    replay, replay_created = create_connector_job(actor=author, source=source)
    assert created and not replay_created and job.pk == replay.pk
    assert job.rest_sync_run_id and job.document_set_version_id is None
    assert job.outbox.request_checksum == job.request_checksum
    assert RestSyncRun.objects.count() == 1
    for operation in (
        lambda: claim_build_job(public_id=str(job.public_id), organization_id=org.pk),
        lambda: cancel_build_job(job=job, actor="test"),
        lambda: retry_build_job(job=job, actor="test"),
        lambda: update_progress(
            job_id=job.pk, organization_id=org.pk, expected_attempt=0, documents=1, chunks=1
        ),
    ):
        with pytest.raises(BuildJobError, match="JOB_KIND_MISMATCH"):
            operation()
    assert execute_rest_sync(job.rest_sync_run_id, organization_id=org.pk) == "not_claimed"
    with pytest.raises(ConnectorJobError, match="SOURCE_BUSY"):
        create_connector_job(actor=author, source=source, max_attempts=2)
    calls = []
    monkeypatch.setattr(
        "apps.ingestion.tasks.run_connector_job.apply_async", lambda **kw: calls.append(kw)
    )
    assert dispatch_outbox(organization_id=org.pk) == 1
    assert calls == [
        {
            "args": [str(job.public_id)],
            "headers": {"organization_id": org.pk},
            "queue": "ingestion",
            "retry": False,
        }
    ]
    job.refresh_from_db()
    assert job.status == _rest_run(job).status == "queued"


def test_rest_snapshot_commits_one_authority_and_redelivery_noops(governed_rest):
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert isinstance(run, RestSyncRun)
    client = _rest_client()
    # Direct adapter call makes unexpected internal exceptions visible in this boundary test.
    _execute_snapshot(run, client)
    job.refresh_from_db()
    run.refresh_from_db()
    assert job.status == run.status == "succeeded"
    assert job.attempt == run.attempt == 1
    assert run.snapshot_complete and run.candidate_set_version_id
    assert DocumentVersion.objects.count() == 1
    assert (
        execute_connector_job(
            public_id=str(job.public_id), organization_id=org.pk, rest_client=client
        )
        == "not_claimed"
    )
    assert client.detail_calls == ["a"]
    assert dispatch_outbox(organization_id=org.pk) == 0


def test_confluence_uses_same_job_authority(governed_source):
    _, org, _, author, source = governed_source
    job, _ = create_connector_job(actor=author, source=source)
    page = _sync_page("100", 1, "Root")
    client = ConfluenceClient([page], {"100": (page, b"<p>bounded</p>")})
    assert (
        execute_connector_job(
            public_id=str(job.public_id), organization_id=org.pk, confluence_client=client
        )
        == "succeeded"
    )
    job.refresh_from_db()
    assert job.confluence_sync_run is not None
    assert job.status == job.confluence_sync_run.status == "succeeded"
    assert job.confluence_sync_run.snapshot_complete
    assert job.confluence_sync_run.candidate_set_version_id


@pytest.mark.parametrize("mutation", ["grant", "config"])
def test_live_revocation_or_drift_fences_document_writes(governed_rest, mutation):
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert isinstance(run, RestSyncRun)
    if mutation == "grant":
        TenantRestPullProfileGrant.objects.filter(organization=org).delete()
        code = "REST_PROFILE_NOT_GRANTED"
    else:
        Source.objects.filter(pk=source.pk).update(
            connector_config={"inputs": {"dataset": "other"}}
        )
        code = "SOURCE_CONFIG_CHANGED"
    with pytest.raises(Exception, match=code):
        _execute_snapshot(run, _rest_client())
    assert not Document.objects.exists()
    assert fail_connector_job(run, error_code=code) == "failed"
    job.refresh_from_db()
    assert _rest_run(job).status == "dead_letter"
    assert _rest_run(job).error_code == code


def test_stale_owner_cannot_write_or_reconcile_partial_snapshot(governed_rest):
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert isinstance(run, RestSyncRun)
    StagedIndexBuildJob.objects.filter(pk=job.pk).update(
        heartbeat_at=timezone.now() - timedelta(hours=1)
    )
    assert reconcile_connector_jobs() == 1
    with pytest.raises(ConnectorJobError, match="CONNECTOR_ATTEMPT_FENCED"):
        _execute_snapshot(run, _rest_client())
    assert fail_connector_job(run, error_code="LATE_ERROR") == "reconciliation_required"
    job.refresh_from_db()
    assert _rest_run(job).status == "dead_letter"
    assert not _rest_run(job).snapshot_complete
    assert not RestDocumentCursor.objects.exists()
    assert not Document.objects.exists()


def test_retry_dispatch_clears_projection_error_and_fences_old_attempt(governed_rest, monkeypatch):
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    old = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert old is not None
    assert (
        fail_connector_job(old, error_code="REST_UPSTREAM_UNAVAILABLE", retryable=True)
        == "retry_wait"
    )
    job.refresh_from_db()
    assert _rest_run(job).status == "retry"
    assert dispatch_outbox(organization_id=org.pk) == 0
    StagedIndexBuildOutbox.objects.filter(job=job).update(available_at=timezone.now())
    monkeypatch.setattr("apps.ingestion.tasks.run_connector_job.apply_async", lambda **kw: None)
    assert dispatch_outbox(organization_id=org.pk) == 1
    run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert isinstance(run, RestSyncRun) and run.attempt == 2 and run.error_code == ""
    with pytest.raises(ConnectorJobError, match="CONNECTOR_ATTEMPT_FENCED"):
        with connector_write(old):
            pytest.fail("stale worker was admitted")
    _execute_snapshot(run, _rest_client())


def test_required_audit_failure_rolls_back_admission(governed_rest, monkeypatch):
    _, author, _, _, source = governed_rest

    def fail(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.connector_jobs.record_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create_connector_job(actor=author, source=source)
    assert not StagedIndexBuildJob.objects.exists()
    assert not RestSyncRun.objects.exists()
    assert not StagedIndexBuildOutbox.objects.exists()
    assert not AuditEvent.objects.filter(action="ingestion.connector_job.admitted").exists()


def test_database_rejects_split_status_and_lineage(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL deferred projection and lineage triggers")
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    with pytest.raises(IntegrityError, match="INGESTION_JOB_PROJECTION_MISMATCH"):
        with transaction.atomic():
            RestSyncRun.objects.filter(pk=_rest_run(job).pk).update(status="running", attempt=1)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(OperationalError, match="INGESTION_JOB_IMMUTABLE"):
        with transaction.atomic():
            StagedIndexBuildJob.objects.filter(pk=job.pk).update(source_config_checksum="0" * 64)
    with pytest.raises(OperationalError, match="INGESTION_RUN_LINEAGE_IMMUTABLE"):
        with transaction.atomic():
            RestSyncRun.objects.filter(pk=_rest_run(job).pk).update(max_attempts=1)
    assert claim_connector_job(public_id=str(job.public_id), organization_id=org.pk) is not None
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def test_operator_cancel_retry_denies_other_users_and_old_attempts(governed_rest):
    _, author, org, _, source = governed_rest
    outsider = get_user_model().objects.create_user(username="outside")
    with pytest.raises(ConnectorJobError, match="SCENARIO_AUTHOR_REQUIRED"):
        create_connector_job(actor=outsider, source=source)
    assert AuditEvent.objects.filter(action="ingestion.connector_job.authorization_denied").exists()
    job, _ = create_connector_job(actor=author, source=source)
    run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert isinstance(run, RestSyncRun)
    with pytest.raises(ConnectorJobError, match="SCENARIO_AUTHOR_REQUIRED"):
        change_connector_job(
            public_id=str(job.public_id), organization_id=org.pk, actor=outsider, action="cancel"
        )
    cancelled = change_connector_job(
        public_id=str(job.public_id), organization_id=org.pk, actor=author, action="cancel"
    )
    assert cancelled.status == "cancelled" and _rest_run(cancelled).status == "dead_letter"
    with pytest.raises(ConnectorJobError, match="CONNECTOR_ATTEMPT_FENCED"):
        _execute_snapshot(run, _rest_client())
    retry = change_connector_job(
        public_id=str(job.public_id), organization_id=org.pk, actor=author, action="retry"
    )
    assert retry.pk == job.pk and _rest_run(retry).status == "queued"
    assert (
        execute_connector_job(
            public_id=str(job.public_id), organization_id=org.pk, rest_client=_rest_client()
        )
        == "succeeded"
    )


def test_console_opt_in_preserves_intent_and_deduplicates(governed_rest, settings, client):
    _, author, _, _, source = governed_rest
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    client.force_login(author)
    url = reverse("console:connector_source_run", args=[source.pk])
    assert client.post(url).status_code == 302
    assert client.post(url).status_code == 302
    assert StagedIndexBuildJob.objects.count() == RestSyncRun.objects.count() == 1
    job = StagedIndexBuildJob.objects.get()
    assert job.status == "dispatch_pending" and job.outbox.published_at is None


def test_schedule_and_completion_delivery_survive_broker_failure(
    governed_rest, settings, monkeypatch
):
    _, _, org, _, source = governed_rest
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    schedule = ConnectorSyncSchedule.objects.create(
        organization=org,
        source=source,
        enabled=True,
        interval_seconds=3600,
        next_run_at=timezone.now(),
        configured_by="test",
    )
    assert dispatch_due_schedules() == 1
    assert dispatch_due_schedules() == 0
    job = StagedIndexBuildJob.objects.get()
    assert _rest_run(job).schedule_id == schedule.pk
    assert (
        execute_connector_job(
            public_id=str(job.public_id), organization_id=org.pk, rest_client=_rest_client()
        )
        == "succeeded"
    )

    def unavailable(**kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "apps.ingestion.tasks.apply_connector_automation_task.apply_async", unavailable
    )
    assert dispatch_connector_completion(organization_id=org.pk) == 0
    outbox = StagedIndexBuildOutbox.objects.get(job=job)
    assert outbox.completion_error_code == "BROKER_UNAVAILABLE"
    assert outbox.completion_published_at is None
    job.refresh_from_db()
    assert _rest_run(job).snapshot_complete
    StagedIndexBuildOutbox.objects.filter(pk=outbox.pk).update(
        completion_available_at=timezone.now()
    )
    calls = []
    monkeypatch.setattr(
        "apps.ingestion.tasks.apply_connector_automation_task.apply_async",
        lambda **kwargs: calls.append(kwargs),
    )
    assert dispatch_connector_completion(organization_id=org.pk) == 1
    assert dispatch_connector_completion(organization_id=org.pk) == 0
    assert calls == [
        {
            "args": [schedule.pk, _rest_run(job).candidate_set_version_id, org.pk],
            "queue": "ingestion",
            "retry": False,
        }
    ]


def test_database_fences_evidence_and_competing_legacy_admission(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL source writer and evidence guards")
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    with pytest.raises(OperationalError, match="SOURCE_BUSY"):
        with transaction.atomic():
            RestSyncRun.objects.create(
                organization=org,
                source=source,
                rest_profile=source.rest_profile,
                rest_contract=source.rest_contract,
            )
    with pytest.raises(OperationalError, match="CONNECTOR_EVIDENCE_FENCED"):
        with transaction.atomic():
            RestSyncRun.objects.filter(pk=_rest_run(job).pk).update(discovered_count=100)
    run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert isinstance(run, RestSyncRun)
    _execute_snapshot(run, _rest_client())
    with pytest.raises(OperationalError, match="CONNECTOR_EVIDENCE_FENCED"):
        with transaction.atomic():
            RestSyncRun.objects.filter(pk=run.pk).update(snapshot_complete=False)
    next_job, _ = create_connector_job(actor=author, source=source)
    assert (
        claim_connector_job(public_id=str(next_job.public_id), organization_id=org.pk) is not None
    )
    with pytest.raises(OperationalError, match="CONNECTOR_EVIDENCE_FENCED"):
        with transaction.atomic():
            RestDocumentCursor.objects.filter(source=source).update(state="missing")


def test_non_owner_job_and_snapshot_keep_tenant_scope(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL non-owner RLS")
    from apps.tenancy.context import set_tenant_context

    _, author, org, _, source = governed_rest
    role = f"job_writer_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_restpullprofile, ingestion_confluenceprofile, "
            f'ingestion_connection FROM "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        set_tenant_context(org.pk)
        job, _ = create_connector_job(actor=author, source=source)
        run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
        assert isinstance(run, RestSyncRun)
        _execute_snapshot(run, _rest_client())
        job.refresh_from_db()
        assert job.status == "succeeded" and _rest_run(job).snapshot_complete
        set_tenant_context(org.pk + 50000)
        assert not StagedIndexBuildJob.objects.filter(pk=job.pk).exists()
        assert not RestSyncRun.objects.filter(pk=run.pk).exists()
        assert not Document.objects.exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


@pytest.mark.django_db(transaction=True)
def test_concurrent_admission_and_claim_have_one_committed_owner(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL concurrent row locks")
    _, author, org, _, source = governed_rest
    barrier = Barrier(2)

    def admit():
        close_old_connections()
        try:
            barrier.wait()
            job, created = create_connector_job(actor=author, source=source)
            return job.pk, str(job.public_id), created
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = list(pool.map(lambda _: admit(), range(2)))
    assert admitted[0][0] == admitted[1][0]
    assert sorted(item[2] for item in admitted) == [False, True]
    assert StagedIndexBuildJob.objects.count() == RestSyncRun.objects.count() == 1
    barrier = Barrier(2)

    def claim():
        close_old_connections()
        try:
            barrier.wait()
            run = claim_connector_job(public_id=admitted[0][1], organization_id=org.pk)
            return run.attempt if run is not None else None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: claim(), range(2)))
    assert claimed.count(1) == 1 and claimed.count(None) == 1
    job = StagedIndexBuildJob.objects.get()
    assert job.status == _rest_run(job).status == "running"
    assert job.attempt == _rest_run(job).attempt == 1


def test_lost_delivery_redrives_without_spending_an_attempt(governed_rest, monkeypatch):
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    monkeypatch.setattr("apps.ingestion.tasks.run_connector_job.apply_async", lambda **kw: None)
    assert dispatch_outbox(organization_id=org.pk) == 1
    StagedIndexBuildJob.objects.filter(pk=job.pk).update(
        queued_at=timezone.now() - timedelta(hours=1)
    )
    assert reconcile_connector_jobs() == 1
    job.refresh_from_db()
    assert job.status == "dispatch_pending" and job.attempt == 0
    assert job.outbox.published_at is None
    assert dispatch_outbox(organization_id=org.pk) == 1
    assert (
        execute_connector_job(
            public_id=str(job.public_id), organization_id=org.pk, rest_client=_rest_client()
        )
        == "succeeded"
    )


def test_cursor_failure_cleans_only_new_unreferenced_upload(governed_rest, monkeypatch):
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert isinstance(run, RestSyncRun)
    keys = []
    original_put = storage.InMemoryObjectStore.put

    def put(self, key, data, *, content_type):
        keys.append(key)
        original_put(self, key, data, content_type=content_type)

    def fail_cursor(self, *args, **kwargs):
        raise RuntimeError("cursor failed")

    monkeypatch.setattr(storage.InMemoryObjectStore, "put", put)
    monkeypatch.setattr(RestDocumentCursor, "save", fail_cursor)
    with pytest.raises(RuntimeError, match="cursor failed"):
        _execute_snapshot(run, _rest_client())
    assert len(keys) == 1 and not DocumentVersion.objects.exists()
    with pytest.raises(storage.StorageError, match="OBJECT_NOT_FOUND"):
        storage.get_object_store().get(keys[0])


def test_cleanup_preserves_committed_or_uncertain_upload(governed_rest, monkeypatch):
    _, author, org, _, source = governed_rest
    job, _ = create_connector_job(actor=author, source=source)
    run = claim_connector_job(public_id=str(job.public_id), organization_id=org.pk)
    assert isinstance(run, RestSyncRun)
    _execute_snapshot(run, _rest_client())
    key = DocumentVersion.objects.get().object_key
    cleanup_connector_uploads(organization_id=org.pk, created_keys=[key])
    assert storage.get_object_store().get(key) == b"bounded content"

    def unavailable(*args, **kwargs):
        raise OperationalError("database unavailable")

    monkeypatch.setattr(DocumentVersion.objects, "filter", unavailable)
    cleanup_connector_uploads(organization_id=org.pk, created_keys=[key])
    assert storage.get_object_store().get(key) == b"bounded content"
