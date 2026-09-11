"""Manual preparation uses real snapshot, role, publication and build boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.documents import services
from apps.documents.models import DocumentSetVersion
from apps.documents.tests.test_phase_2_8_part_5 import _profiles
from apps.identity.models import DocumentSetResponsibility, DocumentSetResponsibilityAssignment
from apps.ingestion.connector_jobs import _load_run, create_connector_job, execute_connector_job
from apps.ingestion.job_lifecycle import cancel_build_job
from apps.ingestion.manual_preparation import PREPARATION_ERRORS, prepare_source_snapshot
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    DocumentSetPreparationProfile,
    Source,
    StagedIndexBuildJob,
    TenantConfluenceProfileGrant,
    TenantEmbeddingProfileGrant,
    TenantMcpResourceGrant,
    TenantRestPullProfileGrant,
)
from apps.ingestion.preparation import configure_preparation
from apps.ingestion.rest_setup_schedule import preparation_fingerprint
from apps.ingestion.tests.test_confluence import _sync_page, _SyncClient
from apps.ingestion.tests.test_confluence import governed_source as governed_source
from apps.ingestion.tests.test_connector_jobs import _rest_client
from apps.ingestion.tests.test_connector_jobs import isolated_delivery as isolated_delivery
from apps.ingestion.tests.test_mcp_services import create
from apps.ingestion.tests.test_mcp_services import setup as setup
from apps.ingestion.tests.test_mcp_sync import wire as wire
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["rest", "confluence", "mcp"])
def completed_source(request, settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    kwargs = {}
    if request.param == "rest":
        _, actor, _, _, source = request.getfixturevalue("governed_rest")
        kwargs["rest_client"] = _rest_client()
    elif request.param == "confluence":
        _, _, _, actor, source = request.getfixturevalue("governed_source")
        page = _sync_page("100", 1, "Synthetic page")
        kwargs["confluence_client"] = _SyncClient([page], {"100": (page, b"<p>Body</p>")})
    else:
        fixture = request.getfixturevalue("setup")
        actor = fixture[1]
        source = create(fixture, resource_prefixes=["file:///kb/"])
    job, _ = create_connector_job(actor=actor, source=source)
    assert (
        execute_connector_job(
            public_id=str(job.public_id), organization_id=source.organization_id, **kwargs
        )
        == "succeeded"
    )
    job.refresh_from_db()
    embedding, chunking, retrieval = _profiles(source.organization)
    policy = configure_preparation(
        document_set=source.document_set,
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=False,
        actor=str(actor.pk),
    )
    return actor, source, job, policy


def prepare(fixture, **overrides):
    actor, source, job, policy = fixture
    return prepare_source_snapshot(
        **(
            {
                "actor": actor,
                "source": source,
                "job_public_id": job.public_id,
                "expected_policy": preparation_fingerprint(policy),
            }
            | overrides
        )
    )


def assert_untouched(fixture):
    job = fixture[2]
    job.refresh_from_db()
    assert job.status == "succeeded" and job.preparation_job_id is None
    candidate = _load_run(job).candidate_set_version
    assert candidate is not None and candidate.status == "draft"
    assert not StagedIndexBuildJob.objects.filter(kind="index_build").exists()


def test_manual_snapshot_build_link_replay_and_terminal_reuse(completed_source):
    actor, source, job, policy = completed_source
    build = prepare(completed_source)
    assert build.status == "dispatch_pending" and build.result_index_version_id is None
    assert build.document_set_version_id == _load_run(job).candidate_set_version_id
    assert build.pipeline_fingerprint == preparation_fingerprint(policy)
    assert build.chunking_profile_id == policy.chunking_profile_id
    assert build.retrieval_profile_id == policy.retrieval_profile_id
    assert not ConnectorSyncSchedule.objects.filter(source=source).exists()
    assert DocumentSetVersion.objects.filter(
        pk=build.document_set_version_id, status="promotable"
    ).exists()
    assert prepare(completed_source).pk == build.pk
    cancel_build_job(job=build, actor=str(actor.pk))
    replay = prepare(completed_source)
    assert replay.pk == build.pk and replay.status == "cancelled" and replay.attempt == 0
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1
    audit = AuditEvent.objects.get(action="ingestion.connector_job.preparation_linked")
    assert audit.actor_type == "user" and audit.actor_id == str(actor.pk)
    assert audit.after == {
        "preparation_job": str(build.public_id),
        "preparation_state": "dispatch_pending",
    }


@pytest.mark.parametrize("blocker", ["role", "source_grant", "embedding", "changed_policy"])
def test_current_authority_and_review_are_required(completed_source, blocker):
    actor, source, job, policy = completed_source
    if blocker == "role":
        DocumentSetResponsibilityAssignment.objects.filter(membership__user=actor).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
    elif blocker == "source_grant":
        for model in (TenantRestPullProfileGrant, TenantConfluenceProfileGrant):
            model.objects.filter(document_set=source.document_set).delete()
        TenantMcpResourceGrant.objects.filter(document_set=source.document_set).update(
            enabled=False
        )
    elif blocker == "embedding":
        TenantEmbeddingProfileGrant.objects.filter(organization=source.organization).delete()
    else:
        DocumentSetPreparationProfile.objects.filter(pk=policy.pk).update(retrieval_profile=None)
    with pytest.raises(PREPARATION_ERRORS):
        prepare(completed_source)
    assert_untouched(completed_source)
    assert AuditEvent.objects.filter(
        action="ingestion.connector_job.preparation_denied", outcome="deny"
    ).exists()


def test_source_identity_config_and_audit_rollback(completed_source, monkeypatch):
    _, source, _, _ = completed_source
    with pytest.raises(PREPARATION_ERRORS, match="PREPARATION_SOURCE_JOB_NOT_FOUND"):
        prepare(completed_source, job_public_id=uuid4())
    with pytest.raises(PREPARATION_ERRORS, match="PREPARATION_REVIEW_REQUIRED"):
        prepare(completed_source, expected_policy="invalid")
    with pytest.raises(PREPARATION_ERRORS, match="SOURCE_CONFIG_CHANGED"):
        with transaction.atomic():
            Source.objects.filter(pk=source.pk).update(connector_config={})
            prepare(completed_source)

    def fail(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.connector_preparation.record_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        prepare(completed_source)
    assert_untouched(completed_source)


def test_snapshot_membership_cannot_be_changed_by_author_services(completed_source):
    actor, source, job, _ = completed_source
    candidate = _load_run(job).candidate_set_version
    assert candidate is not None
    membership = candidate.memberships.get()
    for operation in (
        lambda: services.remove_document_from_set_draft(
            set_version=candidate, membership_id=membership.pk, actor=str(actor.pk)
        ),
        lambda: services.upsert_document_in_set_draft(
            set_version=candidate, document_version=membership.document_version, actor=str(actor.pk)
        ),
        lambda: services.add_document_to_set_version(
            set_version=candidate, document_version=membership.document_version, actor=str(actor.pk)
        ),
        lambda: services.upload_document(
            organization=source.organization,
            logical_id="extra",
            title="Extra",
            mime_type="text/plain",
            data=b"synthetic",
            actor=str(actor.pk),
            document_set_version=candidate,
        ),
    ):
        with pytest.raises(services.DocumentError) as exc:
            operation()
        assert exc.value.code == "SET_SNAPSHOT_IMMUTABLE"
    assert list(candidate.memberships.values_list("pk", flat=True)) == [membership.pk]
    draft = services.get_or_create_manual_draft(
        document_set=source.document_set, actor=str(actor.pk)
    )
    assert draft.pk != candidate.pk
    assert not services.author_document_set_drafts(source.document_set).filter(pk=candidate.pk)


def test_console_review_csrf_same_job_and_no_schedule(completed_source):
    actor, source, job, _ = completed_source
    client = Client(enforce_csrf_checks=True)
    client.force_login(actor)
    detail = reverse("console:connector_source_detail", args=[source.pk])
    target = reverse("console:connector_source_prepare", args=[source.pk, job.public_id])
    page = client.get(detail)
    assert page.status_code == 200 and "Aramaya hazırla" in page.content.decode()
    assert "Model kullanımı maliyet oluşturabilir" in page.content.decode()
    payload = {"policy": page.context["preparation_review"]["fingerprint"]}
    assert client.get(target).status_code == 405
    assert client.post(target, payload).status_code == 403
    payload["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
    assert client.post(target, payload | {"owner": actor.pk}).status_code == 400
    response = client.post(target, payload, follow=True)
    assert response.status_code == 200 and "Hazırlama işi kaydedildi" in response.content.decode()
    assert "Aramaya hazırla</button>" not in response.content.decode()
    assert "Hazırlamayı iptal et" in response.content.decode()
    listing = client.get(
        reverse("console:document_set_connectors_public", args=[source.document_set.public_id])
    )
    assert "Bu yenilemenin hazırlanması:</strong> Sıraya alınıyor" in listing.content.decode()
    assert client.post(target, payload).status_code == 302
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1


def test_reader_and_cross_scope_cannot_prepare(completed_source, client):
    actor, source, job, policy = completed_source
    reader = get_user_model().objects.create_user("preparation-reader")
    membership = OrganizationMembership.objects.create(
        organization=source.organization, user=reader
    )
    DocumentSetResponsibilityAssignment.objects.create(
        organization=source.organization,
        membership=membership,
        document_set=source.document_set,
        responsibility=DocumentSetResponsibility.METADATA_VIEWER,
        assigned_by=actor,
    )
    client.force_login(reader)
    detail = reverse("console:connector_source_detail", args=[source.pk])
    target = reverse("console:connector_source_prepare", args=[source.pk, job.public_id])
    assert client.get(detail).context["preparation_review"] is None
    assert client.post(target, {"policy": preparation_fingerprint(policy)}).status_code == 403
    client.force_login(actor)
    with pytest.raises(PREPARATION_ERRORS, match="PREPARATION_SOURCE_JOB_NOT_FOUND"):
        other = Source(pk=source.pk + 100, organization=source.organization)
        prepare(completed_source, source=other)
    foreign = Organization.objects.create(slug="foreign-manual", name="Foreign")
    with pytest.raises(PREPARATION_ERRORS, match="PREPARATION_SOURCE_JOB_NOT_FOUND"):
        prepare(completed_source, source=Source(pk=source.pk, organization=foreign))
    set_tenant_context(source.organization_id)
    assert_untouched(completed_source)


def test_unfinished_job_missing_settings_and_disabled_gate(completed_source, settings, client):
    actor, source, _, policy = completed_source
    pending, _ = create_connector_job(actor=actor, source=source)
    with pytest.raises(PREPARATION_ERRORS, match="PREPARATION_COMPLETE_SNAPSHOT_REQUIRED"):
        prepare(completed_source, job_public_id=pending.public_id)
    # A missing policy is a blocker, never permission to silently pick a model.
    with pytest.raises(PREPARATION_ERRORS, match="REST_SETUP_PREPARATION_REQUIRED"):
        with transaction.atomic():
            DocumentSetPreparationProfile.objects.filter(pk=policy.pk).delete()
            prepare(completed_source)
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = False
    with pytest.raises(PREPARATION_ERRORS, match="PREPARATION_UNAVAILABLE"):
        prepare(completed_source)
    client.force_login(actor)
    assert (
        client.post(
            reverse("console:connector_source_prepare", args=[source.pk, pending.public_id]), {}
        ).status_code
        == 404
    )
    assert_untouched(completed_source)


def test_linked_replay_rechecks_grant_and_rejects_different_policy(completed_source):
    _, source, _, _ = completed_source
    build = prepare(completed_source)
    with pytest.raises(PREPARATION_ERRORS, match="PREPARATION_ALREADY_LINKED"):
        prepare(completed_source, expected_policy="0" * 64)
    Source.objects.filter(pk=source.pk).update(status="disabled")
    with pytest.raises(PREPARATION_ERRORS):
        prepare(completed_source)
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1
    build.refresh_from_db()
    assert build.status == "dispatch_pending" and build.attempt == 0


def test_author_branch_excludes_connector_draft(completed_source, client):
    actor, source, job, _ = completed_source
    candidate = _load_run(job).candidate_set_version
    assert candidate is not None
    author_draft = services.get_or_create_manual_draft(
        document_set=source.document_set, actor=str(actor.pk)
    )
    services.publish_document_set_version(set_version=author_draft, actor=str(actor.pk))
    clone = services.branch_document_set_version(source=candidate, actor=str(actor.pk))
    assert clone.pk != candidate.pk
    assert list(clone.memberships.values_list("document_version_id", flat=True)) == list(
        candidate.memberships.values_list("document_version_id", flat=True)
    )
    client.force_login(actor)
    page = client.get(
        reverse("console:document_set_detail_public", args=[source.document_set.public_id]),
        {"version": candidate.pk},
    )
    assert page.status_code == 200 and page.context["current_version"]["is_draft"]
    assert not page.context["current_version"]["can_edit_members"]
    assert "Taslak sürümden çıkar" not in page.content.decode()


@pytest.mark.django_db(transaction=True)
def test_concurrent_replays_share_the_exact_job(completed_source):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks")
    actor, source, job, policy = completed_source
    barrier = Barrier(2)

    def run():
        close_old_connections()
        try:
            with transaction.atomic():
                set_tenant_context(source.organization_id)
                user = get_user_model().objects.get(pk=actor.pk)
                current = Source.objects.get(pk=source.pk)
                barrier.wait(timeout=10)
                return prepare_source_snapshot(
                    actor=user,
                    source=current,
                    job_public_id=job.public_id,
                    expected_policy=preparation_fingerprint(policy),
                ).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(run), pool.submit(run)
        assert one.result(timeout=30) == two.result(timeout=30)
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1
