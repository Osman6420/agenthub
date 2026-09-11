"""Focused real-data proof for the shared source publication transaction."""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.catalog.models import ScenarioAlias
from apps.console.connector_presentation import source_preparation
from apps.evaluations.tests.test_prepared import completed_source as completed_source
from apps.evaluations.tests.test_prepared import governed_rest as governed_rest
from apps.evaluations.tests.test_prepared import governed_source as governed_source
from apps.evaluations.tests.test_prepared import isolated_delivery as isolated_delivery
from apps.evaluations.tests.test_prepared import prepared as prepared
from apps.evaluations.tests.test_prepared import prepared_layout as prepared_layout
from apps.evaluations.tests.test_prepared import setup as setup
from apps.evaluations.tests.test_prepared import wire as wire
from apps.ingestion.connector_jobs import (
    create_scheduled_connector_job,
    dispatch_connector_completion,
    execute_connector_job,
)
from apps.ingestion.mcp_schedule import configure_mcp_schedule
from apps.ingestion.models import ConnectorSyncSchedule, StagedIndexBuildOutbox
from apps.ingestion.rest import RestPullItem
from apps.ingestion.rest_services import configure_sync_schedule
from apps.ingestion.rest_setup_schedule import preparation_fingerprint
from apps.ingestion.staged_build import promote_staged_index
from apps.ingestion.tests.test_confluence import _sync_page
from apps.ingestion.tests.test_confluence import _SyncClient as ConfluenceClient
from apps.ingestion.tests.test_rest_pull import _SyncClient
from apps.ingestion.tests.test_source_revisions import prepare
from apps.releases import source_publication as service
from apps.releases.compiler import promote_release
from apps.releases.models import ScenarioPublication, ScenarioRelease
from apps.releases.publication import PublicationError
from apps.retrieval.providers import PgvectorRetrievalProvider
from apps.workflows.models import Run

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.parametrize("completed_source", ["rest", "mcp", "confluence"], indirect=True),
]


@pytest.mark.parametrize("fail_evaluation", [False, True, "audit"])
def test_revision_publication_preserves_plan_and_switches_atomically(
    scheduled, monkeypatch, wire, fail_evaluation
):
    from apps.ingestion.connector_jobs import create_connector_job
    from apps.ingestion.resource_revisions import create_resource_revision
    from apps.ingestion.rest_services import RestServiceError
    from apps.ingestion.source_revisions import (
        configuration_token,
        create_rest_revision,
        current_source,
        revision_for,
        schedule_for_edit,
        select_source_revision,
    )

    original_job, baseline, old, _ = scheduled
    source = original_job.source
    actor_id = ConnectorSyncSchedule.objects.get(source=source).promotion_approved_by
    from django.contrib.auth import get_user_model

    actor = get_user_model().objects.get(pk=actor_id)
    policy = source.document_set.preparation_profile
    config = schedule_for_edit(source)
    assert config["publication_targets"] == [baseline.scenario_id]
    common = {
        "actor": actor,
        "expected": configuration_token(source),
        "intent": uuid4(),
        "name": "Publication revision",
        "schedule": config,
    }
    if source.connector_type == "generic_rest":
        candidate = create_rest_revision(
            document_set=source.document_set,
            base_source_id=source.pk,
            profile_id=source.rest_profile.public_id,
            definition=deepcopy(source.rest_contract.definition),
            inputs={"dataset": "revised"},
            **common,
        )
    else:
        candidate = create_resource_revision(
            source=source,
            profile_id=source.connection.mcp_resource_profile.public_id
            if source.connector_type == "mcp_resource"
            else source.confluence_profile.public_id,
            config=deepcopy(source.connector_config),
            **common,
        )
    assert revision_for(candidate).schedule_config == config
    job, _ = create_connector_job(actor=actor, source=candidate)
    transport = {}
    if source.connector_type == "confluence_dc":
        page = _sync_page("100", 3, "Revision")
        transport["confluence_client"] = ConfluenceClient(
            [page], {"100": (page, b"<p>Revision</p>")}
        )
    assert (
        execute_connector_job(
            public_id=str(job.public_id),
            organization_id=source.organization_id,
            rest_client=_SyncClient(
                [RestPullItem("a", "r3", "Revision", False, "")], {"a": b"revision candidate"}
            ),
            **transport,
        )
        == "succeeded"
    )
    job.refresh_from_db()
    index = prepare(actor, candidate, job, policy)
    expected = configuration_token(candidate)
    from apps.ingestion.source_revisions import assert_serving_revision
    from apps.ingestion.staged_build import StagedBuildError

    with pytest.raises(StagedBuildError, match="SOURCE_REVISION_NOT_CURRENT"):
        assert_serving_revision(index.document_set_version)
    if fail_evaluation == "audit":
        original_audit = service.record_event

        def fail_audit(**kwargs):
            if kwargs["action"] == "scenario.publication.completed":
                raise RuntimeError("synthetic final audit failure")
            return original_audit(**kwargs)

        monkeypatch.setattr(service, "record_event", fail_audit)
        with pytest.raises(RuntimeError, match="final audit failure"):
            select_source_revision(
                actor=actor, source=candidate, expected=expected, index_id=index.pk
            )
        old.refresh_from_db()
        baseline.refresh_from_db()
        assert current_source(candidate).pk == source.pk
        assert old.status == baseline.status == "active"
        assert not ConnectorSyncSchedule.objects.filter(source=candidate, enabled=True).exists()
        count = Run.objects.count()
        monkeypatch.setattr(service, "record_event", original_audit)
        select_source_revision(actor=actor, source=candidate, expected=expected, index_id=index.pk)
        assert current_source(candidate).pk == candidate.pk
        assert Run.objects.count() == count
    elif fail_evaluation:

        class FailedReader:
            def retrieve_prepared(self, **kwargs):
                raise RuntimeError("synthetic provider failure")

        monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", FailedReader)
        with pytest.raises(RestServiceError, match="EVALUATION_NOT_PASSED"):
            select_source_revision(
                actor=actor, source=candidate, expected=expected, index_id=index.pk
            )
        assert current_source(candidate).pk == source.pk
        old.refresh_from_db()
        baseline.refresh_from_db()
        assert old.status == baseline.status == "active"
        assert not ConnectorSyncSchedule.objects.filter(source=candidate, enabled=True).exists()
    else:
        select_source_revision(actor=actor, source=candidate, expected=expected, index_id=index.pk)
        assert current_source(candidate).pk == candidate.pk
        saved = ConnectorSyncSchedule.objects.get(source=candidate, enabled=True)
        assert saved.automation_mode == "promote_if_safe"
        assert (
            list(saved.promotion_targets.values_list("scenario_id", flat=True))
            == config["publication_targets"]
        )
        assert not ConnectorSyncSchedule.objects.get(source=source).enabled
        receipt = ScenarioPublication.objects.get(source_job=job)
        assert receipt.completed_at and receipt.release.status == "active"
        count = Run.objects.count()
        select_source_revision(actor=actor, source=candidate, expected=expected, index_id=index.pk)
        assert Run.objects.count() == count


@pytest.fixture
def scheduled(prepared, monkeypatch, wire):
    actor, source, _, policy, baseline, old, _ = prepared
    promote_staged_index(old, actor=str(actor.pk))
    promote_release(baseline)
    ScenarioAlias.objects.create(
        organization=source.organization, scenario=baseline.scenario, alias="prepared-source"
    )
    type(baseline.scenario).objects.filter(pk=baseline.scenario_id).update(status="active")
    schedule = configure_sync_schedule(
        actor=actor,
        source=source,
        interval_seconds=3600,
        enabled=True,
        next_run_at=timezone.now() + timedelta(hours=1),
        automation_mode="promote_if_safe",
        embedding_profile=policy.embedding_profile,
        ocr_profile=None,
        scenarios=[baseline.scenario],
    )
    if source.connector_type == "mcp_resource":
        schedule = configure_mcp_schedule(
            actor=actor,
            source=source,
            interval_seconds=3600,
            enabled=True,
            automation_mode="promote_if_safe",
            expected_policy=preparation_fingerprint(policy),
            scenarios=[baseline.scenario],
        )
        wire.contents["file:///kb/a"][0]["text"] = "new approved source content"
    job, _ = create_scheduled_connector_job(schedule=schedule, slot=timezone.now())
    transport = {}
    if source.connector_type == "confluence_dc":
        page = _sync_page("100", 2, "Updated")
        transport["confluence_client"] = ConfluenceClient(
            [page], {"100": (page, b"<p>Updated</p>")}
        )
    assert (
        execute_connector_job(
            public_id=str(job.public_id),
            organization_id=source.organization_id,
            rest_client=_SyncClient(
                [RestPullItem("a", "r2", "Updated", False, "")],
                {"a": b"new approved source content"},
            ),
            **transport,
        )
        == "succeeded"
    )
    job.refresh_from_db()
    # The completion receipt remains pending while the durable preparation job runs.
    assert (
        dispatch_connector_completion(
            organization_id=source.organization_id, public_id=str(job.public_id)
        )
        == 0
    )
    assert StagedIndexBuildOutbox.objects.get(job=job).completion_published_at is None
    job.refresh_from_db()
    assert job.preparation_job_id is not None
    index = prepare(actor, source, job, policy)
    job.refresh_from_db()
    monkeypatch.setattr(
        "apps.orchestration.rag_steps.get_retrieval_provider", PgvectorRetrievalProvider
    )
    return job, baseline, old, index


def test_completion_selects_index_and_release_once(scheduled):
    job, baseline, old, index = scheduled
    StagedIndexBuildOutbox.objects.filter(job=job).update(completion_available_at=None)
    assert (
        dispatch_connector_completion(
            organization_id=job.organization_id, public_id=str(job.public_id)
        )
        == 1
    ), StagedIndexBuildOutbox.objects.get(job=job).completion_error_code
    receipt = ScenarioPublication.objects.get(source_job=job)
    assert receipt.completed_at is not None and receipt.draft_id is None
    assert receipt.evaluation.status == "passed"
    assert receipt.release.manifest["artifacts"] == baseline.manifest["artifacts"]
    old.refresh_from_db()
    index.refresh_from_db()
    baseline.refresh_from_db()
    assert old.status == baseline.status == "superseded" and index.status == "active"
    assert receipt.release.status == "active"
    counts = (Run.objects.count(), ScenarioRelease.objects.count())
    assert (
        service.continue_source_publication(job_id=job.pk, organization_id=job.organization_id)
        == "promoted"
    )
    assert counts == (Run.objects.count(), ScenarioRelease.objects.count())
    for changes in ({"source_job": None}, {"baseline_release": None}):
        with pytest.raises(DatabaseError), transaction.atomic():
            ScenarioPublication.objects.filter(pk=receipt.pk).update(**changes)


def test_failed_evaluation_preserves_live_generation_and_is_not_paid_again(scheduled, monkeypatch):
    job, baseline, old, index = scheduled
    calls = []

    class FailedReader:
        def retrieve_prepared(self, **kwargs):
            calls.append(True)
            raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", FailedReader)
    for _ in range(2):
        with pytest.raises(PublicationError, match="EVALUATION_NOT_PASSED"):
            service.continue_source_publication(job_id=job.pk, organization_id=job.organization_id)
    assert calls == [True]
    old.refresh_from_db()
    baseline.refresh_from_db()
    index.refresh_from_db()
    assert old.status == baseline.status == "active" and index.status == "promotable"
    assert ScenarioPublication.objects.get(source_job=job).completed_at is None


def test_final_audit_failure_rolls_back_both_pointers_and_resume_reuses_eval(
    scheduled, monkeypatch
):
    job, baseline, old, index = scheduled
    original = service.record_event

    def fail(**kwargs):
        if kwargs["action"] == "scenario.publication.completed":
            raise RuntimeError("audit unavailable")
        return original(**kwargs)

    monkeypatch.setattr(service, "record_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.continue_source_publication(job_id=job.pk, organization_id=job.organization_id)
    old.refresh_from_db()
    index.refresh_from_db()
    baseline.refresh_from_db()
    assert old.status == baseline.status == "active" and index.status == "promotable"
    receipt = ScenarioPublication.objects.get(source_job=job)
    assert receipt.evaluation.status == "passed" and receipt.completed_at is None
    count = Run.objects.count()
    monkeypatch.setattr(service, "record_event", original)
    assert (
        service.continue_source_publication(job_id=job.pk, organization_id=job.organization_id)
        == "promoted"
    )
    assert Run.objects.count() == count


def test_revoked_approval_after_evaluation_preserves_both_live_pointers(scheduled, monkeypatch):
    job, baseline, old, index = scheduled
    original = service.resume_eval

    def revoke(**kwargs):
        evaluation = original(**kwargs)
        ConnectorSyncSchedule.objects.filter(source_id=job.source_id).update(enabled=False)
        return evaluation

    monkeypatch.setattr(service, "resume_eval", revoke)
    with pytest.raises(PublicationError, match="APPROVAL_CHANGED"):
        service.continue_source_publication(job_id=job.pk, organization_id=job.organization_id)
    old.refresh_from_db()
    index.refresh_from_db()
    baseline.refresh_from_db()
    assert old.status == baseline.status == "active" and index.status == "promotable"
    assert ScenarioPublication.objects.get(source_job=job).completed_at is None
    assert AuditEvent.objects.filter(
        action="scenario.publication.blocked",
        reason="SOURCE_PUBLICATION_APPROVAL_CHANGED",
        outcome="deny",
        organization_id=job.organization_id,
    ).exists()


def test_source_status_never_claims_publication_from_preparation_completion_alone(scheduled):
    job, _, _, _ = scheduled
    StagedIndexBuildOutbox.objects.filter(job=job).update(completion_published_at=timezone.now())
    job.refresh_from_db()
    assert "otomatik yayın kaydı yok" in source_preparation(job)["publication"]
    StagedIndexBuildOutbox.objects.filter(job=job).update(
        completion_published_at=None, completion_error_code="PUBLICATION_EVALUATION_NOT_PASSED"
    )
    job.refresh_from_db()
    assert "Testler geçmedi" in source_preparation(job)["publication"]
