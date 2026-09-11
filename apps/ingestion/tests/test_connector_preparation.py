"""Completed snapshots enter one durable preparation path, with exact lineage."""

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
from django.urls import reverse
from django.utils import timezone

from apps.documents.models import DocumentSet, DocumentSetVersion
from apps.documents.services import publish_document_set_version
from apps.documents.tests.test_phase_2_8_part_5 import _profiles
from apps.identity.models import DocumentSetResponsibilityAssignment
from apps.ingestion.automation import apply_connector_automation
from apps.ingestion.connector_jobs import (
    create_scheduled_connector_job,
    dispatch_connector_completion,
    execute_connector_job,
)
from apps.ingestion.connector_preparation import (
    ConnectorPreparationError,
    prepare_connector_snapshot,
)
from apps.ingestion.job_lifecycle import cancel_build_job, create_build_job, dispatch_outbox
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    StagedIndexBuildJob,
    StagedIndexBuildOutbox,
    TenantEmbeddingProfileGrant,
    TenantRestPullProfileGrant,
)
from apps.ingestion.preparation import configure_preparation
from apps.ingestion.tasks import apply_connector_automation_task
from apps.ingestion.tests.test_confluence import _sync_page, _SyncClient
from apps.ingestion.tests.test_confluence import governed_source as governed_source
from apps.ingestion.tests.test_connector_jobs import _rest_client
from apps.ingestion.tests.test_connector_jobs import isolated_delivery as isolated_delivery
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


def scheduled(source, author):
    embedding, chunking, retrieval = _profiles(source.organization)
    schedule = ConnectorSyncSchedule.objects.create(
        organization=source.organization,
        source=source,
        enabled=True,
        next_run_at=timezone.now(),
        automation_mode="stage_only",
        embedding_profile=embedding,
        configured_by=str(author.pk),
    )
    job, _ = create_scheduled_connector_job(schedule=schedule, slot=schedule.next_run_at)
    return job, schedule, embedding, chunking, retrieval


@pytest.fixture
def finished(governed_rest):
    result = scheduled(governed_rest[4], governed_rest[1])
    job = result[0]
    assert (
        execute_connector_job(
            public_id=str(job.public_id),
            organization_id=job.organization_id,
            rest_client=_rest_client(),
        )
        == "succeeded"
    )
    job.refresh_from_db()
    assert job.rest_sync_run is not None and job.rest_sync_run.candidate_set_version_id
    return result


def policy_for(setup, auto=True):
    job, schedule, embedding, chunking, retrieval = setup
    assert job.source is not None and job.source.document_set is not None
    return configure_preparation(
        document_set=job.source.document_set,
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=auto,
        actor="test",
    )


def prepare(job):
    return prepare_connector_snapshot(job_id=job.pk, organization_id=job.organization_id)


@pytest.mark.parametrize("auto", [False, True])
def test_exact_policy_and_publication_share_one_job_and_outbox(finished, auto):
    job, _, embedding, chunking, retrieval = finished
    policy_for(finished, auto=auto)
    build = prepare(job)
    assert build is not None
    job.refresh_from_db()
    assert job.status == "succeeded" and job.preparation_job_id == build.pk
    assert build.status == "dispatch_pending" and build.result_index_version_id is None
    assert build.embedding_profile_id == embedding.pk and build.chunking_profile_id == chunking.pk
    assert build.retrieval_profile_id == retrieval.pk
    assert (
        build.document_set_version is not None and build.document_set_version.status == "promotable"
    )
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1
    assert StagedIndexBuildOutbox.objects.filter(job__kind="index_build").count() == 1
    assert prepare(job).pk == build.pk


def test_schedule_without_policy_keeps_legacy_chunking(finished):
    build = prepare(finished[0])
    assert build is not None
    assert build.embedding_profile_id == finished[2].pk
    assert build.chunking_profile_id is None and build.retrieval_profile_id is None


def test_previous_cancelled_auto_job_is_linked_without_paid_retry(finished):
    policy_for(finished)
    job = finished[0]
    assert job.rest_sync_run is not None and job.rest_sync_run.candidate_set_version is not None
    candidate = publish_document_set_version(
        set_version=job.rest_sync_run.candidate_set_version, actor="test"
    )
    old = StagedIndexBuildJob.objects.get(document_set_version=candidate)
    cancel_build_job(job=old, actor="test")
    build = prepare(job)
    assert build is not None and build.pk == old.pk and build.status == "cancelled"
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1


def test_unrelated_pipeline_is_not_mistaken_for_prepared_work(finished):
    job, _, embedding, _, _ = finished
    assert job.rest_sync_run is not None and job.rest_sync_run.candidate_set_version is not None
    candidate = publish_document_set_version(
        set_version=job.rest_sync_run.candidate_set_version, actor="test"
    )
    old, _ = create_build_job(
        document_set_version=candidate, embedding_profile=embedding, ocr_profile=None, actor="test"
    )
    policy_for(finished)
    build = prepare(job)
    assert (
        build is not None
        and build.pk != old.pk
        and build.pipeline_fingerprint != old.pipeline_fingerprint
    )


@pytest.mark.parametrize("blocker", ["source_grant", "embedding_grant", "policy", "source_config"])
def test_live_admission_blockers_preserve_draft_and_create_no_work(finished, blocker):
    job, schedule, embedding, *_ = finished
    if blocker == "source_grant":
        TenantRestPullProfileGrant.objects.filter(organization_id=job.organization_id).delete()
    elif blocker == "embedding_grant":
        TenantEmbeddingProfileGrant.objects.filter(organization_id=job.organization_id).delete()
    elif blocker == "policy":
        policy_for(finished)
        ConnectorSyncSchedule.objects.filter(pk=schedule.pk).update(embedding_profile=None)
    else:
        assert job.source is not None
        type(job.source).objects.filter(pk=job.source_id).update(
            connector_config={"inputs": {"dataset": "changed"}}
        )
    assert dispatch_connector_completion(organization_id=job.organization_id) == 0
    job.refresh_from_db()
    assert job.preparation_job_id is None and job.status == "succeeded"
    assert job.outbox.completion_error_code and job.outbox.completion_published_at is None
    assert job.outbox.completion_available_at > timezone.now()
    assert not StagedIndexBuildJob.objects.filter(kind="index_build").exists()
    assert job.rest_sync_run is not None and job.rest_sync_run.candidate_set_version is not None
    assert job.rest_sync_run.candidate_set_version.status == "draft"
    assert dispatch_connector_completion(organization_id=job.organization_id) == 0


def test_audit_failure_rolls_back_publication_link_and_preparation(finished, monkeypatch):
    job = finished[0]
    policy_for(finished)

    def fail(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.connector_preparation.record_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        prepare(job)
    job.refresh_from_db()
    assert (
        job.preparation_job_id is None
        and not StagedIndexBuildJob.objects.filter(kind="index_build").exists()
    )
    assert job.rest_sync_run is not None and job.rest_sync_run.candidate_set_version is not None
    assert job.rest_sync_run.candidate_set_version.status == "draft"


def test_broker_failure_cannot_lose_preparation_handoff(finished, monkeypatch):
    job = finished[0]

    def fail(**kwargs):
        raise OSError("broker unavailable")

    monkeypatch.setattr("apps.ingestion.tasks.run_staged_index_build_job.apply_async", fail)
    monkeypatch.setattr("apps.ingestion.tasks.apply_connector_automation_task.apply_async", fail)
    assert dispatch_connector_completion(organization_id=job.organization_id) == 1
    job.refresh_from_db()
    assert job.preparation_job_id and job.outbox.completion_published_at
    assert dispatch_outbox(organization_id=job.organization_id) == 0
    build = job.preparation_job
    assert build is not None and build.status == "dispatch_pending"
    assert build.outbox.last_error_code == "BROKER_UNAVAILABLE"
    assert build.outbox.published_at is None
    assert dispatch_connector_completion(organization_id=job.organization_id) == 0


def test_old_task_redelivery_never_claims_or_runs_inline_build(finished, monkeypatch):
    job, schedule, *_ = finished

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy inline preparation invoked")

    monkeypatch.setattr("apps.ingestion.automation.claim_connector_automation", forbidden)
    monkeypatch.setattr("apps.ingestion.automation.build_staged_index", forbidden)
    assert job.rest_sync_run is not None
    kwargs = {
        "schedule_id": schedule.pk,
        "candidate_set_version_id": job.rest_sync_run.candidate_set_version_id,
        "organization_id": job.organization_id,
    }
    assert apply_connector_automation_task(**kwargs) == "preparation_dispatch_pending"
    assert apply_connector_automation(**kwargs) == "preparation_dispatch_pending"
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1
    schedule.refresh_from_db()
    assert schedule.automation_status == "idle"  # not falsely marked prepared when only queued


def test_confluence_joins_same_preparation_path(governed_source):
    _, org, _, author, source = governed_source
    job, *_ = scheduled(source, author)
    page = _sync_page("100", 1, "Root")
    client = _SyncClient([page], {"100": (page, b"<p>bounded</p>")})
    assert (
        execute_connector_job(
            public_id=str(job.public_id), organization_id=org.pk, confluence_client=client
        )
        == "succeeded"
    )
    build = prepare(job)
    assert build is not None
    job.refresh_from_db()
    assert job.confluence_sync_run is not None
    assert build.document_set_version_id == job.confluence_sync_run.candidate_set_version_id


def test_unfinished_parent_and_link_mutation_are_denied(governed_rest, finished):
    job = finished[0]
    build = prepare(job)
    assert build is not None
    job.refresh_from_db()
    job.preparation_job = None
    with pytest.raises(ValueError, match="LINK_IMMUTABLE"):
        job.save(update_fields=["preparation_job"])
    build.preparation_job = build
    with pytest.raises(ValueError, match="LINK_INVALID"):
        build.save(update_fields=["preparation_job"])
    assert build.document_set_version is not None
    # A new scheduled snapshot must finish before it can refer to this prior work.
    next_job, _ = create_scheduled_connector_job(
        schedule=finished[1], slot=timezone.now() + timedelta(hours=1)
    )
    with pytest.raises(ConnectorPreparationError, match="COMPLETE_SNAPSHOT_REQUIRED"):
        prepare(next_job)


def test_postgres_link_and_target_integrity(finished):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL lineage trigger")
    job = finished[0]
    build = prepare(job)
    assert build is not None
    with pytest.raises(OperationalError, match="LINK_IMMUTABLE"), transaction.atomic():
        StagedIndexBuildJob.objects.filter(pk=job.pk).update(preparation_job=None)
    with pytest.raises(OperationalError, match="TARGET_IMMUTABLE"), transaction.atomic():
        StagedIndexBuildJob.objects.filter(pk=build.pk).update(pipeline_fingerprint="f" * 64)
    with pytest.raises(IntegrityError, match="PARENT_INVALID"), transaction.atomic():
        StagedIndexBuildJob.objects.filter(pk=build.pk).update(preparation_job=build)
    migration = import_module("apps.ingestion.migrations.0031_source_preparation_link")
    with pytest.raises(RuntimeError, match="REQUIRES_NO_LINKS"):
        migration.reverse(apps, connection.schema_editor(atomic=False))


def test_postgres_rejects_foreign_and_wrong_candidate_links(finished):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL lineage trigger")
    job = finished[0]
    for org in (job.organization, Organization.objects.create(slug="foreign-prep", name="Foreign")):
        docset = DocumentSet.objects.create(organization=org, logical_id="other", name="Other")
        version = DocumentSetVersion.objects.create(
            organization=org, document_set=docset, version=1
        )
        build, _ = create_build_job(
            document_set_version=version,
            embedding_profile=finished[2],
            ocr_profile=None,
            actor="test",
        )
        with pytest.raises(IntegrityError, match="TARGET_INVALID"), transaction.atomic():
            StagedIndexBuildJob.objects.filter(pk=job.pk).update(preparation_job=build)
    assert StagedIndexBuildJob.objects.get(pk=job.pk).preparation_job_id is None


def test_non_owner_runtime_can_link_only_visible_preparation(finished):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL FORCE RLS")
    job = finished[0]
    policy_for(finished)
    role = f"prep_writer_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        result = prepare(job)
        assert result is not None
        assert StagedIndexBuildJob.objects.get(pk=job.pk).preparation_job_id == result.pk
        set_tenant_context(999999)
        assert not StagedIndexBuildJob.objects.filter(pk__in=[job.pk, result.pk]).exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


def test_console_separates_fetch_and_prepare_and_preserves_action_authority(
    client, finished, governed_rest
):
    job = finished[0]
    result = prepare(job)
    assert result is not None
    viewer = get_user_model().objects.create_user(username="prep-viewer")
    membership = OrganizationMembership.objects.create(organization=governed_rest[2], user=viewer)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=governed_rest[2],
        membership=membership,
        document_set=governed_rest[3],
        responsibility="document_set_metadata_viewer",
        assigned_by=governed_rest[0],
    )
    url = reverse("console:connector_source_detail", args=[job.source_id])
    cancel = reverse("console:document_set_cancel_build_job", args=[result.public_id])
    client.force_login(viewer)
    response = client.get(url)
    assert response.status_code == 200
    assert response.context["job_status_label"] == "Tamamlandı"
    assert response.context["source_preparation"]["label"] == "Sıraya alınıyor"
    listing = client.get(
        reverse("console:document_set_connectors_public", args=[governed_rest[3].public_id])
    )
    source_row = next(
        row for row in listing.context["sources"] if row["object"].pk == job.source_id
    )
    assert source_row["preparation"]["job"].pk == result.pk
    assert "Bu yenilemenin hazırlanması:</strong> Sıraya alınıyor" in listing.content.decode()
    assert "Hazırlamayı iptal et" not in response.content.decode()
    assert client.post(cancel).status_code == 403
    client.force_login(governed_rest[1])
    assert "Hazırlamayı iptal et" in client.get(url).content.decode()
    assert client.post(cancel).status_code == 302
    job.refresh_from_db()
    assert job.status == "succeeded" and job.preparation_job is not None
    assert job.preparation_job.status == "cancelled"
    assert "Hazırlamayı yeniden dene" in client.get(url).content.decode()
    assert (
        client.post(
            reverse("console:document_set_retry_build_job", args=[result.public_id])
        ).status_code
        == 302
    )
    assert StagedIndexBuildJob.objects.get(pk=result.pk).status == "dispatch_pending"


def test_console_shows_policy_conflict_without_claiming_preparation_success(
    client, finished, governed_rest
):
    policy_for(finished)
    job, schedule, *_ = finished
    ConnectorSyncSchedule.objects.filter(pk=schedule.pk).update(embedding_profile=None)
    assert dispatch_connector_completion(organization_id=job.organization_id) == 0
    client.force_login(governed_rest[1])
    page = client.get(reverse("console:connector_source_detail", args=[job.source_id]))
    assert (
        "Yenileme planı ile doküman setinin hazırlama ayarları uyuşmuyor" in page.content.decode()
    )
    assert page.context["source_preparation"]["job"] is None


def test_disabled_schedule_is_not_shown_as_waiting_for_preparation(client, finished, governed_rest):
    job, schedule, *_ = finished
    ConnectorSyncSchedule.objects.filter(pk=schedule.pk).update(enabled=False)
    client.force_login(governed_rest[1])
    page = client.get(reverse("console:connector_source_detail", args=[job.source_id]))
    assert page.context["source_preparation"]["label"] == "Hazırlama planı kapalı"
    assert prepare(job) is None
    assert not StagedIndexBuildJob.objects.filter(kind="index_build").exists()


@pytest.mark.django_db(transaction=True)
def test_parallel_preparation_replays_link_one_build(finished):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks")
    job = finished[0]
    policy_for(finished)

    def run():
        close_old_connections()
        try:
            result = prepare(job)
            assert result is not None
            return result.pk
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        assert futures[0].result() == futures[1].result()
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1
