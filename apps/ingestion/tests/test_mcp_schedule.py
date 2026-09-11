"""Scheduled resources cross real policy, queue, snapshot and preparation boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connection,
    transaction,
)
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.documents.tests.test_phase_2_8_part_5 import _profiles
from apps.identity.models import DocumentSetResponsibility, DocumentSetResponsibilityAssignment
from apps.ingestion.connector_jobs import (
    create_scheduled_connector_job,
    dispatch_connector_completion,
    execute_connector_job,
)
from apps.ingestion.job_lifecycle import dispatch_outbox
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.mcp_schedule import configure_mcp_schedule
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    DocumentSetPreparationProfile,
    ResourceSnapshot,
    StagedIndexBuildJob,
    StagedIndexBuildOutbox,
    TenantEmbeddingProfileGrant,
    TenantMcpResourceGrant,
)
from apps.ingestion.preparation import configure_preparation
from apps.ingestion.rest_setup_schedule import preparation_fingerprint
from apps.ingestion.scheduler import dispatch_due_schedules
from apps.ingestion.tests.test_mcp_services import setup as setup
from apps.ingestion.tests.test_mcp_sync import source as source
from apps.ingestion.tests.test_mcp_sync import wire as wire
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.context import set_tenant_scope
from apps.tenancy.models import OrganizationMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def enabled(settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True


@pytest.fixture
def policy(setup):
    embedding, chunking, retrieval = _profiles(setup[2])
    return configure_preparation(
        document_set=setup[3],
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=False,
        actor=str(setup[1].pk),
    )


def configure(setup, source, policy=None, **kwargs):
    return configure_mcp_schedule(
        **{
            "actor": setup[1],
            "source": source,
            "enabled": True,
            "interval_seconds": 3600,
            "automation_mode": "stage_only" if policy else "draft_only",
            "expected_policy": preparation_fingerprint(policy) if policy else "",
        }
        | kwargs
    )


def execute(job):
    assert (
        execute_connector_job(public_id=str(job.public_id), organization_id=job.organization_id)
        == "succeeded"
    )
    job.refresh_from_db()


@pytest.mark.parametrize("auto_prepare", [False, True])
def test_scheduled_snapshot_links_exact_policy_once_without_activation(
    setup, source, policy, auto_prepare
):
    DocumentSetPreparationProfile.objects.filter(pk=policy.pk).update(auto_prepare=auto_prepare)
    schedule = configure(setup, source, policy)
    slot = schedule.next_run_at
    job, created = create_scheduled_connector_job(schedule=schedule, slot=slot)
    assert created and job.resource_snapshot.schedule_id == schedule.pk
    assert job.resource_snapshot.schedule_slot == slot
    execute(job)
    assert dispatch_connector_completion(organization_id=source.organization_id) == 1
    job.refresh_from_db()
    build = job.preparation_job
    assert build is not None
    assert build.document_set_version_id == job.resource_snapshot.candidate_set_version_id
    assert build.embedding_profile_id == policy.embedding_profile_id
    assert build.chunking_profile_id == policy.chunking_profile_id
    assert build.document_set_version is not None
    assert build.document_set_version.status == "promotable"
    assert build.status == "dispatch_pending" and build.result_index_version_id is None
    assert dispatch_connector_completion(organization_id=source.organization_id) == 0
    same, created = create_scheduled_connector_job(schedule=schedule, slot=slot)
    assert same.pk == job.pk and not created
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1
    next_job, created = create_scheduled_connector_job(
        schedule=schedule, slot=slot + timedelta(hours=1)
    )
    assert created
    execute(next_job)
    assert next_job.resource_snapshot.candidate_set_version_id is None
    assert dispatch_connector_completion(organization_id=source.organization_id) == 0
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1


@pytest.mark.parametrize("pause", [False, True])
def test_draft_or_paused_plan_does_not_dispatch_legacy_automation(
    setup, source, policy, pause, monkeypatch
):
    schedule = configure(setup, source, policy if pause else None)
    job, _ = create_scheduled_connector_job(schedule=schedule, slot=schedule.next_run_at)
    execute(job)
    if pause:
        configure(setup, source, policy, enabled=False)
    monkeypatch.setattr(
        "apps.ingestion.tasks.apply_connector_automation_task.apply_async",
        lambda **kwargs: pytest.fail("MCP must never enter the legacy REST task"),
    )
    assert dispatch_connector_completion(organization_id=source.organization_id) == 1
    assert not StagedIndexBuildJob.objects.filter(kind="index_build").exists()


def test_dispatch_skips_backlog_and_running_source_and_redrives_one_pending_job(setup, source):
    schedule = configure(setup, source)
    now = timezone.now()
    ConnectorSyncSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(days=8))
    assert dispatch_due_schedules(now=now) == 1
    job = StagedIndexBuildJob.objects.get(source=source)
    schedule.refresh_from_db()
    assert schedule.next_run_at == now + timedelta(hours=1)
    assert dispatch_due_schedules(now=now) == 0
    assert dispatch_due_schedules(now=now + timedelta(hours=1)) == 1
    assert StagedIndexBuildJob.objects.filter(source=source).count() == 1
    from apps.ingestion.connector_jobs import claim_connector_job

    assert claim_connector_job(public_id=str(job.public_id), organization_id=source.organization_id)
    assert dispatch_due_schedules(now=now + timedelta(hours=2)) == 0
    assert StagedIndexBuildJob.objects.filter(source=source).count() == 1


def test_broker_failure_retains_same_intent_and_dispatches_common_task(setup, source, monkeypatch):
    schedule = configure(setup, source)
    job, _ = create_scheduled_connector_job(schedule=schedule, slot=schedule.next_run_at)

    def fail(**kwargs):
        raise OSError("synthetic queue outage")

    monkeypatch.setattr("apps.ingestion.tasks.run_connector_job.apply_async", fail)
    assert dispatch_outbox(organization_id=source.organization_id) == 0
    outbox = StagedIndexBuildOutbox.objects.get(job=job)
    assert outbox.last_error_code == "BROKER_UNAVAILABLE" and outbox.published_at is None
    StagedIndexBuildOutbox.objects.filter(pk=outbox.pk).update(available_at=timezone.now())
    delivered = []
    monkeypatch.setattr(
        "apps.ingestion.tasks.run_connector_job.apply_async", lambda **kw: delivered.append(kw)
    )
    monkeypatch.setattr(
        "apps.ingestion.tasks.sync_rest_source.apply_async",
        lambda **kw: pytest.fail("legacy dispatch"),
    )
    assert dispatch_outbox(organization_id=source.organization_id) == 1
    assert delivered[0]["args"] == [str(job.public_id)]
    assert delivered[0]["headers"] == {"organization_id": source.organization_id}
    assert dispatch_outbox(organization_id=source.organization_id) == 0


@pytest.mark.parametrize("reason", ["gate", "grant", "source"])
def test_schedule_admission_rechecks_gate_and_live_source(setup, source, settings, reason):
    schedule = configure(setup, source)
    if reason == "gate":
        settings.INGESTION_DURABLE_CONNECTOR_JOBS = False
    elif reason == "grant":
        TenantMcpResourceGrant.objects.filter(pk=setup[-1].pk).update(enabled=False)
    else:
        type(source).objects.filter(pk=source.pk).update(status="disabled")
    assert dispatch_due_schedules(now=schedule.next_run_at) == 0
    assert not StagedIndexBuildJob.objects.filter(source=source).exists()


@pytest.mark.parametrize("revoke", ["grant", "embedding", "policy"])
def test_completion_rechecks_permission_and_policy_without_paid_job(setup, source, policy, revoke):
    schedule = configure(setup, source, policy)
    job, _ = create_scheduled_connector_job(schedule=schedule, slot=schedule.next_run_at)
    execute(job)
    if revoke == "grant":
        TenantMcpResourceGrant.objects.filter(pk=setup[-1].pk).update(enabled=False)
    elif revoke == "embedding":
        TenantEmbeddingProfileGrant.objects.filter(organization=setup[2]).delete()
    else:
        DocumentSetPreparationProfile.objects.filter(pk=policy.pk).delete()
    assert dispatch_connector_completion(organization_id=source.organization_id) == 0
    assert not StagedIndexBuildJob.objects.filter(kind="index_build").exists()
    job.refresh_from_db()
    assert job.preparation_job_id is None
    assert job.outbox.completion_error_code and job.outbox.completion_published_at is None


def test_reviewed_policy_is_required_and_pause_survives_revoked_grants(setup, source, policy):
    with pytest.raises(McpResourceError, match="PREPARATION_CHANGED"):
        configure(setup, source, policy, expected_policy="0" * 64)
    assert not ConnectorSyncSchedule.objects.filter(source=source).exists()
    assert AuditEvent.objects.filter(
        action="mcp_resource.schedule.configured", outcome="deny"
    ).exists()
    configure(setup, source, policy)
    TenantMcpResourceGrant.objects.filter(pk=setup[-1].pk).update(enabled=False)
    TenantEmbeddingProfileGrant.objects.filter(organization=setup[2]).delete()
    paused = configure(setup, source, policy, enabled=False, expected_policy="")
    assert not paused.enabled and paused.embedding_profile_id == policy.embedding_profile_id
    with pytest.raises(McpResourceError):
        configure(setup, source, policy)


@pytest.mark.parametrize(
    "values",
    [
        {"automation_mode": "promote_if_safe"},
        {"interval_seconds": 1},
        {"interval_seconds": True},
        {"enabled": "false"},
        {"automation_mode": "stage_only", "expected_policy": ""},
    ],
)
def test_invalid_schedule_has_no_mutation_and_safe_denial_audit(setup, source, values):
    with pytest.raises(McpResourceError):
        configure(setup, source, **values)
    assert not ConnectorSyncSchedule.objects.filter(source=source).exists()
    audit = AuditEvent.objects.get(action="mcp_resource.schedule.configured")
    assert audit.outcome == "deny" and "secret:" not in str(audit.after)


def test_schedule_and_success_audit_are_atomic(setup, source, monkeypatch):
    original = import_module("apps.ingestion.mcp_services").record_event

    def audit(**kwargs):
        if (
            kwargs["action"] == "mcp_resource.schedule.configured"
            and kwargs["outcome"] == "success"
        ):
            raise RuntimeError("synthetic audit outage")
        return original(**kwargs)

    monkeypatch.setattr("apps.ingestion.mcp_services.record_event", audit)
    with pytest.raises(RuntimeError, match="audit outage"):
        configure(setup, source)
    assert not ConnectorSyncSchedule.objects.filter(source=source).exists()


def test_console_review_and_closed_post_keep_choices_on_failure(client, setup, source, policy):
    client.force_login(setup[1])
    url = reverse("console:mcp_schedule_configure", args=[source.pk])
    page = client.get(url)
    assert page.status_code == 200
    assert page.context["navigation_section"] == "documents"
    assert "Aramaya hazırla" in page.content.decode() and "promote_if_safe" in page.content.decode()
    assert "mcp.example.com" not in page.content.decode() and "secret:" not in page.content.decode()
    assert (
        client.post(
            url,
            {
                "enabled": "on",
                "interval_seconds": "3600",
                "automation_mode": "promote_if_safe",
                "policy": preparation_fingerprint(policy),
                "scenarios": ["999999"],
            },
        ).status_code
        == 400
    )
    assert not ConnectorSyncSchedule.objects.filter(source=source).exists()
    payload = {
        "enabled": "on",
        "interval_seconds": "3600",
        "automation_mode": "stage_only",
        "policy": preparation_fingerprint(policy),
    }
    invalid = client.post(url, payload | {"policy": "0" * 64})
    assert invalid.status_code == 400 and "ayarları değişti" in invalid.content.decode()
    assert invalid.context["form"]["interval_seconds"].value() == "3600"
    assert client.post(url, payload | {"source": "123"}).status_code == 400
    assert client.post(url, payload).status_code == 302
    detail = client.get(reverse("console:connector_source_detail", args=[source.pk]))
    assert "Periyodik" in detail.content.decode() and url in detail.content.decode()
    listing = client.get(
        reverse("console:document_set_connectors_public", args=[setup[3].public_id])
    )
    assert url in listing.content.decode() and "Sonraki yenileme:" in listing.content.decode()


def test_console_requires_csrf_and_exact_collection_manager(setup, source, policy):
    url = reverse("console:mcp_schedule_configure", args=[source.pk])
    client = Client(enforce_csrf_checks=True)
    client.force_login(setup[1])
    assert client.post(url, {}).status_code == 403
    assert client.get(url).status_code == 200
    payload = {
        "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        "enabled": "on",
        "interval_seconds": "3600",
        "automation_mode": "draft_only",
    }
    assert client.post(url, payload).status_code == 302
    viewer = get_user_model().objects.create_user("mcp-schedule-viewer")
    membership = OrganizationMembership.objects.create(organization=setup[2], user=viewer)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=setup[2],
        document_set=setup[3],
        membership=membership,
        responsibility=DocumentSetResponsibility.METADATA_VIEWER,
        assigned_by=setup[1],
    )
    client.force_login(viewer)
    assert client.get(url).status_code == 403
    assert client.post(url, payload).status_code == 403
    detail = client.get(reverse("console:connector_source_detail", args=[source.pk]))
    assert detail.status_code == 200 and url not in detail.content.decode()
    with pytest.raises(McpResourceError, match="FORBIDDEN"):
        configure(setup, source, actor=viewer)
    outsider = get_user_model().objects.create_user("outside-schedule")
    client.force_login(outsider)
    assert client.get(url).status_code == 404


def test_postgres_schedule_lineage_constraints_and_protected_rollback(setup, source):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL schedule and snapshot triggers")
    schedule = configure(setup, source)
    job, _ = create_scheduled_connector_job(schedule=schedule, slot=schedule.next_run_at)
    with pytest.raises(OperationalError, match="IMMUTABLE"), transaction.atomic():
        ResourceSnapshot.objects.filter(job=job).update(schedule_slot=timezone.now())
    with pytest.raises(OperationalError, match="IMMUTABLE"), transaction.atomic():
        ConnectorSyncSchedule.objects.filter(pk=schedule.pk).update(
            source=setup[3].connector_sources.get(connector_type="generic_rest")
        )
    with pytest.raises(IntegrityError, match="SCOPE_INVALID"), transaction.atomic():
        ConnectorSyncSchedule.objects.filter(pk=schedule.pk).update(
            automation_mode="promote_if_safe"
        )
    migration = import_module("apps.ingestion.migrations.0032_resource_snapshot_schedule")
    with pytest.raises(RuntimeError, match="EMPTY_HISTORY"):
        migration.reverse(apps, connection.schema_editor(atomic=False))


def test_postgres_runtime_role_can_schedule_only_scoped_resources(setup, source, policy):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL FORCE RLS")
    role = f"mcp_schedule_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT DELETE ON ingestion_connectorschedulepromotiontarget TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        schedule = configure(setup, source, policy)
        job, _ = create_scheduled_connector_job(schedule=schedule, slot=schedule.next_run_at)
        execute(job)
        assert dispatch_connector_completion(organization_id=source.organization_id) == 1
        set_tenant_scope(())
        assert not ResourceSnapshot.objects.exists()
        assert not ConnectorSyncSchedule.objects.exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


@pytest.mark.django_db(transaction=True)
def test_postgres_parallel_same_slot_admits_only_one_job(setup, source):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL concurrent admission")
    schedule = configure(setup, source)

    def admit():
        close_old_connections()
        try:
            return create_scheduled_connector_job(schedule=schedule, slot=schedule.next_run_at)[
                0
            ].pk
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(admit) for _ in range(2)]
        assert futures[0].result() == futures[1].result()
    assert StagedIndexBuildJob.objects.filter(source=source).count() == 1
