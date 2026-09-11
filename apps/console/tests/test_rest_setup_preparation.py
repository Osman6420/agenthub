"""Wizard staging reuses exact set policy, with no hidden work or authority expansion."""

from typing import Any
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.console.rest_setup_forms import InputStep, visual_initial
from apps.console.tests.test_rest_setup import advance
from apps.console.tests.test_rest_setup import wizard as wizard
from apps.documents.models import DocumentSet
from apps.documents.tests.test_phase_2_8_part_5 import _profiles
from apps.ingestion.connector_jobs import (
    create_scheduled_connector_job,
    dispatch_connector_completion,
    execute_connector_job,
)
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    DocumentSetPreparationProfile,
    OcrProfile,
    RestPullContract,
    RestSetupDraft,
    Source,
    StagedIndexBuildJob,
    TenantEmbeddingProfileGrant,
    TenantOcrProfileGrant,
)
from apps.ingestion.preparation import configure_preparation
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    configure_sync_schedule,
)
from apps.ingestion.rest_setup import create_rest_setup
from apps.ingestion.rest_setup_drafts import load_setup_draft, save_setup_draft
from apps.ingestion.rest_setup_schedule import preparation_fingerprint, validate_setup_schedule
from apps.ingestion.tests.test_connector_jobs import _rest_client
from apps.ingestion.tests.test_connector_jobs import isolated_delivery as isolated_delivery
from apps.ingestion.tests.test_rest_pull import _definition
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def policy(governed_rest, settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    embedding, chunking, retrieval = _profiles(governed_rest[2])
    ocr = OcrProfile.objects.create(
        logical_id="setup-ocr",
        revision=1,
        host="ocr.example.com",
        secret_ref="secret://ocr-fixture",  # noqa: S106
        created_by="platform",
    )
    TenantOcrProfileGrant.objects.create(
        organization=governed_rest[2], ocr_profile=ocr, created_by="platform"
    )
    return configure_preparation(
        document_set=governed_rest[3],
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=ocr,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=False,
        actor=str(governed_rest[1].pk),
    )


def selection(policy) -> dict[str, Any]:
    return {"interval_seconds": 3600, "preparation": preparation_fingerprint(policy)}


def create(setup, *, schedule, **kwargs):
    return create_rest_setup(
        actor=kwargs.pop("actor", setup[1]),
        document_set=setup[3],
        profile_id=setup[4].rest_profile.public_id,
        intent=kwargs.pop("intent", uuid4()),
        name="Hazırlanan REST belgeleri",
        definition=_definition(),
        inputs={"dataset": "docs"},
        schedule=schedule,
        **kwargs,
    )


def to_stage_review(client, url, setup):
    assert (
        advance(
            client,
            url,
            {"name": "Hazırlanan REST belgeleri", "profile": str(setup[4].rest_profile.public_id)},
        ).status_code
        == 302
    )
    assert advance(client, url, visual_initial(_definition())).status_code == 302
    assert (
        advance(
            client,
            url,
            {
                "input_dataset": "docs",
                "sync_mode": "periodic",
                "interval_seconds": "3600",
                "preparation_mode": "stage_only",
            },
        ).status_code
        == 302
    )
    return client.get(url)


def test_stage_source_schedule_and_saved_completion_are_atomic_and_idempotent(
    governed_rest, policy
):
    intent = uuid4()
    selected = selection(policy)
    checkpoint = save_setup_draft(
        actor=governed_rest[1],
        document_set=governed_rest[3],
        intent=intent,
        payload={
            "name": "Hazırlanan REST belgeleri",
            "step": 4,
            "mode": "visual",
            "profile": str(governed_rest[4].rest_profile.public_id),
            "definition": _definition(),
            "inputs": {"dataset": "docs"},
            "schedule": selected,
        },
    )
    first = create(
        governed_rest, intent=intent, schedule=selected, draft_revision=checkpoint.revision
    )
    # Completed checkpoints are locators; a stale submission cannot consume them again.
    with pytest.raises(RestServiceError, match="DRAFT_CONFLICT"):
        create(governed_rest, intent=intent, schedule=selected, draft_revision=checkpoint.revision)
    assert (
        load_setup_draft(
            actor=governed_rest[1], document_set=governed_rest[3], intent=intent
        ).completed_source_id
        == first.pk
    )
    plan = first.sync_schedule
    assert plan.automation_mode == "stage_only" and plan.enabled
    assert plan.embedding_profile_id == policy.embedding_profile_id
    assert plan.ocr_profile_id == policy.ocr_profile_id
    assert not plan.promotion_targets.exists() and plan.promotion_approved_by == ""
    checkpoint.refresh_from_db()
    policy.refresh_from_db()
    assert checkpoint.payload == {} and checkpoint.completed_source_id == first.pk
    assert not policy.auto_prepare and DocumentSetPreparationProfile.objects.count() == 1
    assert not StagedIndexBuildJob.objects.exists()
    assert Source.objects.count() == 2 and RestPullContract.objects.count() == 2
    assert ConnectorSyncSchedule.objects.count() == 1


def test_stage_setup_replay_without_checkpoint_reuses_exact_intent(governed_rest, policy):
    intent = uuid4()
    selected = selection(policy)
    first = create(governed_rest, intent=intent, schedule=selected)
    assert create(governed_rest, intent=intent, schedule=selected).pk == first.pk
    with pytest.raises(RestServiceError, match="INTENT_CONFLICT"):
        create(governed_rest, intent=intent, schedule={"interval_seconds": 3600})
    assert Source.objects.count() == 2 and ConnectorSyncSchedule.objects.count() == 1


def test_wizard_schedule_snapshot_handoff_uses_all_existing_policy_pins(governed_rest, policy):
    source = create(governed_rest, schedule=selection(policy))
    schedule = source.sync_schedule
    job, _ = create_scheduled_connector_job(schedule=schedule, slot=schedule.next_run_at)
    assert (
        execute_connector_job(
            public_id=str(job.public_id),
            organization_id=job.organization_id,
            rest_client=_rest_client(),
        )
        == "succeeded"
    )
    assert dispatch_connector_completion(organization_id=job.organization_id) == 1
    job.refresh_from_db()
    build = job.preparation_job
    assert build is not None and build.status == "dispatch_pending"
    assert build.embedding_profile_id == policy.embedding_profile_id
    assert build.ocr_profile_id == policy.ocr_profile_id
    assert build.chunking_profile_id == policy.chunking_profile_id
    assert build.retrieval_profile_id == policy.retrieval_profile_id
    assert build.result_index_version_id is None
    assert (
        build.document_set_version is not None and build.document_set_version.status == "promotable"
    )
    assert StagedIndexBuildJob.objects.filter(kind="index_build").count() == 1


@pytest.mark.parametrize(
    "blocked", ["embedding_grant", "ocr_grant", "ocr_disabled", "policy_changed", "policy_scope"]
)
def test_reviewed_policy_or_live_grant_change_rejects_whole_setup(governed_rest, policy, blocked):
    selected = selection(policy)
    if blocked == "embedding_grant":
        TenantEmbeddingProfileGrant.objects.filter(organization=governed_rest[2]).delete()
    elif blocked == "ocr_grant":
        TenantOcrProfileGrant.objects.filter(organization=governed_rest[2]).delete()
    elif blocked == "ocr_disabled":
        OcrProfile.objects.filter(pk=policy.ocr_profile_id).update(status="disabled")
    elif blocked == "policy_changed":
        DocumentSetPreparationProfile.objects.filter(pk=policy.pk).update(retrieval_profile=None)
    else:
        other = Organization.objects.create(slug="other-policy-org", name="Other")
        docset = DocumentSet.objects.create(organization=other, logical_id="other", name="Other")
        DocumentSetPreparationProfile.objects.filter(pk=policy.pk).update(document_set=docset)
    with pytest.raises(RestServiceError, match="REST_SETUP_PREPARATION_"):
        create(governed_rest, schedule=selected)
    assert Source.objects.count() == 1 and RestPullContract.objects.count() == 1
    assert not ConnectorSyncSchedule.objects.exists() and not StagedIndexBuildJob.objects.exists()
    assert AuditEvent.objects.filter(action="rest_source.setup", outcome="deny").exists()


def test_preparation_selection_does_not_grant_set_management(governed_rest, policy):
    from django.contrib.auth import get_user_model

    outsider = get_user_model().objects.create_user(username="setup-outsider")
    with pytest.raises(RestAuthorizationError):
        create(governed_rest, schedule=selection(policy), actor=outsider)
    assert Source.objects.count() == 1


def test_schedule_audit_failure_rolls_back_setup_and_preserves_checkpoint(
    governed_rest, policy, monkeypatch
):
    selected = selection(policy)
    intent = uuid4()
    checkpoint = save_setup_draft(
        actor=governed_rest[1],
        document_set=governed_rest[3],
        intent=intent,
        payload={"name": "Hazırlanan REST belgeleri", "step": 1, "mode": "visual"},
    )
    from apps.ingestion import rest_services

    original = rest_services._audit

    def fail_schedule(action, *args, **kwargs):
        if action == "connector_schedule.configure":
            raise RuntimeError("audit unavailable")
        return original(action, *args, **kwargs)

    monkeypatch.setattr(rest_services, "_audit", fail_schedule)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create(governed_rest, schedule=selected, intent=intent, draft_revision=checkpoint.revision)
    checkpoint.refresh_from_db()
    assert checkpoint.completed_source_id is None and checkpoint.payload["step"] == 1
    assert Source.objects.count() == 1 and RestPullContract.objects.count() == 1
    assert not ConnectorSyncSchedule.objects.exists()


@pytest.mark.parametrize(
    "value",
    [
        {"interval_seconds": True},
        {"interval_seconds": 1},
        {"interval_seconds": 3600, "preparation": {}},
        {"interval_seconds": 3600, "preparation": "f" * 63},
        {"interval_seconds": 3600, "automation_mode": "promote_if_safe"},
        {"interval_seconds": 3600, "embedding_profile": 1},
    ],
)
def test_schedule_rejects_unsupported_authority_and_shape(value):
    with pytest.raises(RestServiceError, match="SCHEDULE_INVALID"):
        validate_setup_schedule(value)


def test_old_saved_interval_and_existing_ocr_are_preserved(governed_rest, policy):
    source = create(governed_rest, schedule={"interval_seconds": 3600})
    plan = source.sync_schedule
    assert plan.automation_mode == "draft_only" and plan.embedding_profile_id is None
    plan.ocr_profile = policy.ocr_profile
    plan.save(update_fields=["ocr_profile"])
    # An older caller omitting the new option must not silently clear it.
    configure_sync_schedule(
        actor=governed_rest[1],
        source=source,
        interval_seconds=900,
        enabled=True,
        next_run_at=plan.next_run_at,
    )
    plan.refresh_from_db()
    assert plan.ocr_profile_id == policy.ocr_profile_id
    configure_sync_schedule(
        actor=governed_rest[1],
        source=source,
        interval_seconds=900,
        enabled=True,
        next_run_at=plan.next_run_at,
        ocr_profile=None,
    )
    plan.refresh_from_db()
    assert plan.ocr_profile_id is None


def test_form_requires_periodic_and_current_policy(governed_rest, policy):
    values = {"input_dataset": "docs", "preparation_mode": "stage_only", "interval_seconds": "3600"}
    assert not InputStep(
        values | {"sync_mode": "manual"}, definition=_definition(), preparation_policy=policy
    ).is_valid()
    assert not InputStep(values | {"sync_mode": "periodic"}, definition=_definition()).is_valid()
    valid = InputStep(
        values | {"sync_mode": "periodic"}, definition=_definition(), preparation_policy=policy
    )
    assert valid.is_valid(), valid.errors
    assert valid.schedule == selection(policy)


def test_review_detects_changed_policy_and_can_save_then_resume(
    client, wizard, governed_rest, policy
):
    page = to_stage_review(client, wizard, governed_rest)
    html = page.content.decode()
    assert "Aramaya hazırlanır" in html and "setup-ocr" in html
    assert "secret://" not in html and "ocr.example.com" not in html
    DocumentSetPreparationProfile.objects.filter(pk=policy.pk).update(retrieval_profile=None)
    failed = client.post(wizard, {"action": "save", "submission": page.context["submission"]})
    assert failed.status_code == 400 and "yeniden kontrol edin" in failed.content.decode()
    assert not ConnectorSyncSchedule.objects.exists()
    assert advance(client, wizard, {}, action="save_draft").status_code == 302
    checkpoint = RestSetupDraft.objects.get()
    loaded = load_setup_draft(
        actor=governed_rest[1], document_set=governed_rest[3], intent=checkpoint.public_id
    )
    assert loaded.payload["schedule"]["preparation"] == preparation_fingerprint(policy)
    fresh = Client()
    fresh.force_login(governed_rest[1])
    response = fresh.post(
        reverse(
            "console:rest_setup_resume", args=[governed_rest[3].public_id, checkpoint.public_id]
        )
    )
    url = response["Location"]
    assert advance(fresh, url, {}, action="back").status_code == 302
    assert (
        advance(
            fresh,
            url,
            {
                "input_dataset": "docs",
                "sync_mode": "periodic",
                "interval_seconds": "3600",
                "preparation_mode": "stage_only",
            },
        ).status_code
        == 302
    )
    assert advance(fresh, url, {}, action="save").status_code == 302
    assert ConnectorSyncSchedule.objects.get().automation_mode == "stage_only"
    source = Source.objects.get(slug=f"rest-{checkpoint.public_id.hex}")
    detail = fresh.get(reverse("console:connector_source_detail", args=[source.pk]))
    assert "Aramaya hazırlanır; kullanıma alma ayrıca yönetilir." in detail.content.decode()


def test_stage_service_cannot_enable_unavailable_worker_contract(governed_rest, policy, settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = False
    with pytest.raises(RestServiceError, match="PREPARATION_UNAVAILABLE"):
        create(governed_rest, schedule=selection(policy))
    assert not ConnectorSyncSchedule.objects.exists()
