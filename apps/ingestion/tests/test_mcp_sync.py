"""Real durable job and document boundaries with offline MCP wire responses."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, OperationalError, connection, transaction
from django.utils import timezone

from apps.documents import storage
from apps.documents.models import DocumentVersion
from apps.ingestion.connector_jobs import (
    ConnectorJobError,
    change_connector_job,
    claim_connector_job,
    connector_write,
    create_connector_job,
    execute_connector_job,
    fail_connector_job,
    reconcile_connector_jobs,
)
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.mcp_sync import execute_snapshot
from apps.ingestion.models import (
    ResourceSnapshot,
    SourceDocumentCursor,
    StagedIndexBuildJob,
    TenantMcpResourceGrant,
)
from apps.ingestion.tests.test_mcp_resources import Harness
from apps.ingestion.tests.test_mcp_services import create
from apps.ingestion.tests.test_mcp_services import setup as setup
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.context import set_tenant_context, set_tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def source(setup):
    return create(setup, resource_prefixes=["file:///kb/"])


@pytest.fixture(autouse=True)
def wire(monkeypatch):
    storage.reset_in_memory_store()
    harness = Harness()
    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)
    monkeypatch.setattr("apps.ingestion.mcp_resources._default_connection_factory", harness.factory)
    monkeypatch.setattr(
        "apps.ingestion.mcp_resources._default_resolver",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", port))],
    )
    monkeypatch.setattr(
        "apps.ingestion.mcp_sync.EnvSecretResolver.resolve", lambda self, ref: "synthetic"
    )
    yield harness
    storage.reset_in_memory_store()


def admit(setup, source):
    return create_connector_job(actor=setup[1], source=source)[0]


def claim(job):
    run = claim_connector_job(public_id=str(job.public_id), organization_id=job.organization_id)
    assert isinstance(run, ResourceSnapshot)
    return run


def test_snapshot_uses_one_job_and_duplicate_delivery_does_not_read_again(setup, source, wire):
    job = admit(setup, source)
    same, created = create_connector_job(actor=setup[1], source=source)
    assert same.pk == job.pk and not created
    assert job.rest_sync_run_id is None and job.confluence_sync_run_id is None
    assert not (
        {"status", "error_code", "max_attempts"} & {f.name for f in ResourceSnapshot._meta.fields}
    )
    run = claim(job)
    execute_snapshot(run)
    job.refresh_from_db()
    evidence = ResourceSnapshot.objects.get(pk=job.pk)
    assert job.status == "succeeded" and evidence.snapshot_complete and evidence.material_change
    assert evidence.attempt == 1 and evidence.discovered_count == evidence.changed_count == 1
    assert evidence.candidate_set_version is not None
    assert evidence.candidate_set_version.memberships.count() == 1
    assert DocumentVersion.objects.count() == 1 and job.documents_completed == 1
    calls = len(wire.requests)
    assert (
        execute_connector_job(public_id=str(job.public_id), organization_id=job.organization_id)
        == "not_claimed"
    )
    assert len(wire.requests) == calls


def test_unchanged_scan_reuses_document_and_candidate_without_upload(setup, source, wire):
    first = admit(setup, source)
    execute_snapshot(claim(first))
    cursor = SourceDocumentCursor.objects.get(source=source)
    second = admit(setup, source)
    execute_snapshot(claim(second))
    evidence = ResourceSnapshot.objects.get(pk=second.pk)
    assert evidence.snapshot_complete and not evidence.material_change
    assert evidence.candidate_set_version_id is None and evidence.unchanged_count == 1
    assert DocumentVersion.objects.count() == 1
    cursor.refresh_from_db()
    assert cursor.last_seen_job_id == second.pk and cursor.document_version_id is not None


def test_partial_scan_never_marks_missing_or_commits_success(setup, source, wire):
    first = admit(setup, source)
    execute_snapshot(claim(first))
    wire.resources = []
    wire.next_cursor = "repeating"
    second = admit(setup, source)
    assert (
        execute_connector_job(
            public_id=str(second.public_id), organization_id=source.organization_id
        )
        == "failed"
    )
    second.refresh_from_db()
    assert second.error_code == "MCP_RESOURCE_CURSOR_INVALID"
    assert not ResourceSnapshot.objects.get(pk=second.pk).snapshot_complete
    assert SourceDocumentCursor.objects.get(source=source).state == "active"
    assert DocumentVersion.objects.count() == 1


def test_complete_empty_scan_creates_missing_candidate_without_deleting_document(
    setup, source, wire
):
    execute_snapshot(claim(admit(setup, source)))
    wire.resources = []
    job = admit(setup, source)
    execute_snapshot(claim(job))
    evidence = ResourceSnapshot.objects.get(pk=job.pk)
    assert evidence.snapshot_complete and evidence.missing_count == 1
    assert evidence.candidate_set_version is not None
    assert evidence.candidate_set_version.memberships.count() == 0
    assert SourceDocumentCursor.objects.get(source=source).state == "missing"
    assert DocumentVersion.objects.count() == 1


def test_partial_attempt_markers_do_not_hide_missing_on_retry(setup, source, wire):
    job = admit(setup, source)
    old = claim(job)
    wire.next_cursor = "repeating"
    with pytest.raises(McpResourceError):
        execute_snapshot(old)
    assert SourceDocumentCursor.objects.get(source=source).last_seen_attempt == 1
    fail_connector_job(old, error_code="MCP_RESOURCE_CURSOR_INVALID")
    change_connector_job(
        public_id=str(job.public_id),
        organization_id=source.organization_id,
        actor=setup[1],
        action="retry",
    )
    current = claim(job)
    assert current.attempt == 2
    with pytest.raises(ConnectorJobError, match="ATTEMPT_FENCED"):
        with connector_write(old):
            pytest.fail("stale owner admitted")
    wire.resources, wire.next_cursor = [], None
    execute_snapshot(current)
    evidence = ResourceSnapshot.objects.get(pk=job.pk)
    assert evidence.missing_count == 1 and evidence.discovered_count == 0
    assert SourceDocumentCursor.objects.get(source=source).state == "missing"


def test_revocation_before_next_request_prevents_resource_read(setup, source, wire):
    job = admit(setup, source)
    original = wire.response

    def revoke(message, headers):
        response = original(message, headers)
        if message["method"] == "resources/list":
            TenantMcpResourceGrant.objects.filter(pk=setup[-1].pk).update(enabled=False)
        return response

    wire.response = revoke
    assert (
        execute_connector_job(public_id=str(job.public_id), organization_id=source.organization_id)
        == "failed"
    )
    assert not DocumentVersion.objects.exists()
    assert [row[2]["method"] for row in wire.requests] == [
        "initialize",
        "notifications/initialized",
        "resources/list",
    ]


def test_cancel_and_stale_heartbeat_fence_mcp_writes(setup, source):
    job = admit(setup, source)
    old = claim(job)
    change_connector_job(
        public_id=str(job.public_id),
        organization_id=source.organization_id,
        actor=setup[1],
        action="cancel",
    )
    with pytest.raises(ConnectorJobError, match="FENCED"):
        execute_snapshot(old)
    assert fail_connector_job(old, error_code="LATE") == "cancelled"
    later = admit(setup, source)
    run = claim(later)
    StagedIndexBuildJob.objects.filter(pk=later.pk).update(
        heartbeat_at=timezone.now() - timedelta(hours=1)
    )
    assert reconcile_connector_jobs() == 1
    with pytest.raises(ConnectorJobError, match="FENCED"):
        execute_snapshot(run)
    assert not DocumentVersion.objects.exists()


def test_sql_snapshot_success_and_cursor_updates_require_current_owner(setup, source):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL deferred evidence and attempt guards")
    job = admit(setup, source)
    with pytest.raises(IntegrityError, match="PROJECTION_MISMATCH"), transaction.atomic():
        StagedIndexBuildJob.objects.filter(pk=job.pk).update(status="succeeded")
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    run = claim(job)
    with pytest.raises(OperationalError, match="ATTEMPT_FENCED"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.ingestion_job_id', '', true)")
        ResourceSnapshot.objects.filter(pk=job.pk).update(discovered_count=1)
    execute_snapshot(run)
    with pytest.raises(OperationalError, match="FENCED"), transaction.atomic():
        SourceDocumentCursor.objects.filter(source=source).update(state="missing")


def test_non_owner_resource_snapshot_and_cursor_are_scoped_and_writable(setup, source):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL runtime RLS")
    role = f"resource_worker_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_mcpresourceprofile, ingestion_connection, "
            f'ingestion_tenantmcpresourcegrant FROM "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        set_tenant_context(source.organization_id)
        job = admit(setup, source)
        execute_snapshot(claim(job))
        assert ResourceSnapshot.objects.get(pk=job.pk).snapshot_complete
        assert SourceDocumentCursor.objects.filter(source=source).count() == 1
        set_tenant_scope(())
        assert not ResourceSnapshot.objects.exists() and not SourceDocumentCursor.objects.exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
