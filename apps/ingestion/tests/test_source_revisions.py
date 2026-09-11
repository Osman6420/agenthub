"""Source edits preserve the live writer, immutable history and snapshot isolation."""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.documents.models import DocumentSetVersion
from apps.ingestion.connector_jobs import (
    ConnectorJobError,
    _load_run,
    create_connector_job,
    execute_connector_job,
)
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    Source,
    SourceConfigurationRevision,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    configure_sync_schedule,
)
from apps.ingestion.snapshot import latest_trusted_candidate
from apps.ingestion.source_revisions import (
    assert_serving_revision,
    configuration_token,
    create_rest_revision,
    current_source,
    family_source_ids,
    revision_for,
    visible_sources,
)
from apps.ingestion.staged_build import StagedBuildError
from apps.ingestion.tests.test_connector_jobs import _rest_client
from apps.ingestion.tests.test_connector_jobs import isolated_delivery as isolated_delivery
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def enabled(settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True


def create(fixture, **overrides):
    _, actor, _, docset, source = fixture
    return create_rest_revision(
        **(
            {
                "actor": actor,
                "document_set": docset,
                "base_source_id": source.pk,
                "expected": configuration_token(source),
                "profile_id": source.rest_profile.public_id,
                "intent": uuid4(),
                "name": "Edited source",
                "definition": deepcopy(source.rest_contract.definition),
                "inputs": {"dataset": "edited"},
            }
            | overrides
        )
    )


def run(actor, source):
    job, _ = create_connector_job(actor=actor, source=source)
    assert (
        execute_connector_job(
            public_id=str(job.public_id),
            organization_id=source.organization_id,
            rest_client=_rest_client(),
        )
        == "succeeded"
    )
    job.refresh_from_db()
    return job


def test_clone_preserves_writer_and_idempotent_config(governed_rest):
    _, actor, _, _, old = governed_rest
    intent, token = uuid4(), configuration_token(old)
    candidate = create(governed_rest, intent=intent, expected=token)
    assert current_source(candidate).pk == old.pk
    revision = revision_for(candidate)
    assert revision is not None and revision.number == 2
    assert candidate.rest_contract.revision == 2
    assert candidate.rest_contract_id != old.rest_contract_id
    old.refresh_from_db()
    assert old.connector_config != candidate.connector_config
    assert not ConnectorSyncSchedule.objects.filter(source=candidate).exists()
    assert list(visible_sources(Source.objects.all())) == [old]
    assert set(family_source_ids(candidate)) == {candidate.pk, old.pk}
    assert create(governed_rest, intent=intent, expected=token).pk == candidate.pk
    with pytest.raises(RestServiceError, match="INTENT_CONFLICT"):
        create(governed_rest, intent=intent, expected=token, name="Conflicting name")
    assert SourceConfigurationRevision.objects.count() == 2
    assert (
        AuditEvent.objects.filter(
            action="ingestion.source_revision.created", outcome="success"
        ).count()
        == 1
    )


def test_stale_edit_and_audit_failure_do_not_change_history(governed_rest, monkeypatch):
    old = governed_rest[-1]
    token = configuration_token(old)
    create(governed_rest)
    with pytest.raises(RestServiceError, match="SOURCE_REVISION_CHANGED"):
        create(governed_rest, expected=token)

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.source_revisions.record_event", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create(governed_rest)
    assert SourceConfigurationRevision.objects.count() == 2
    assert Source.objects.count() == 2


def test_unselected_snapshot_is_isolated_and_cannot_serve(governed_rest):
    _, actor, _, docset, old = governed_rest
    old_job = run(actor, old)
    old_candidate = _load_run(old_job).candidate_set_version
    candidate = create(governed_rest)
    new_job = run(actor, candidate)
    new_candidate = _load_run(new_job).candidate_set_version
    assert old_candidate is not None and new_candidate is not None
    assert new_candidate.pk != old_candidate.pk
    assert set(
        new_candidate.memberships.values_list("document_version__document__source_id", flat=True)
    ) == {candidate.pk}
    assert latest_trusted_candidate(docset).pk == old_candidate.pk
    assert latest_trusted_candidate(docset, allow_source_id=candidate.pk).pk == new_candidate.pk
    with pytest.raises(StagedBuildError, match="SOURCE_REVISION_NOT_CURRENT"):
        assert_serving_revision(new_candidate)
    count_before = DocumentSetVersion.objects.count()
    unchanged = run(actor, old)
    assert _load_run(unchanged).candidate_set_version_id is None
    assert latest_trusted_candidate(docset).pk == old_candidate.pk
    assert DocumentSetVersion.objects.count() == count_before


def test_family_has_only_one_sync_and_current_schedule(governed_rest):
    _, actor, _, _, old = governed_rest
    candidate = create(governed_rest)
    create_connector_job(actor=actor, source=old)
    with pytest.raises(ConnectorJobError, match="SOURCE_BUSY"):
        create_connector_job(actor=actor, source=candidate)
    with pytest.raises(RestServiceError, match="SOURCE_REVISION_NOT_CURRENT"):
        configure_sync_schedule(
            actor=actor,
            source=candidate,
            interval_seconds=3600,
            enabled=True,
            next_run_at=timezone.now() + timedelta(hours=1),
        )
    assert not ConnectorSyncSchedule.objects.exists()


def test_revoked_grant_rejects_whole_revision(governed_rest):
    source = governed_rest[-1]
    TenantRestPullProfileGrant.objects.filter(rest_profile=source.rest_profile).delete()
    with pytest.raises(RestAuthorizationError, match="REST_PROFILE_NOT_GRANTED"):
        create(governed_rest)
    assert not SourceConfigurationRevision.objects.exists()
    assert Source.objects.count() == 1


def test_revision_cannot_be_attached_to_another_collection(governed_rest):
    from apps.documents.models import DocumentSet

    other = DocumentSet.objects.create(
        organization=governed_rest[2], logical_id="other", name="Other"
    )
    with pytest.raises(RestServiceError, match="SOURCE_REVISION_NOT_FOUND"):
        create(governed_rest, document_set=other)
    assert not SourceConfigurationRevision.objects.exists()


def test_checkpoint_completion_replay_keeps_one_revision(governed_rest):
    from apps.ingestion.rest_setup_drafts import save_setup_draft

    _, actor, _, docset, source = governed_rest
    intent = uuid4()
    token = configuration_token(source)
    saved = save_setup_draft(
        actor=actor,
        document_set=docset,
        intent=intent,
        payload={
            "name": "Edited source",
            "step": 4,
            "mode": "visual",
            "profile": str(source.rest_profile.public_id),
            "definition": source.rest_contract.definition,
            "inputs": {"dataset": "edited"},
            "base_source": source.pk,
            "base_token": token,
        },
    )
    candidate = create(governed_rest, expected=token, intent=intent, draft_revision=saved.revision)
    assert (
        create(governed_rest, expected=token, intent=intent, draft_revision=saved.revision).pk
        == candidate.pk
    )
    saved.refresh_from_db()
    assert saved.payload == {} and saved.completed_source_id == candidate.pk
    assert SourceConfigurationRevision.objects.count() == 2


def test_orm_and_sql_cannot_rewrite_sealed_source(governed_rest):
    candidate = create(governed_rest)
    source = governed_rest[-1]
    source.name = "rewrite"
    with pytest.raises(ValueError, match="SOURCE_REVISION_CONFIG_IMMUTABLE"):
        source.save()
    if connection.vendor != "postgresql":
        return
    with (
        pytest.raises(DatabaseError, match="SOURCE_REVISION_CONFIG_IMMUTABLE"),
        transaction.atomic(),
    ):
        Source.objects.filter(pk=source.pk).update(
            connector_config={"inputs": {"dataset": "rewrite"}}
        )
    with pytest.raises(DatabaseError, match="SOURCE_REVISION_IMMUTABLE"), transaction.atomic():
        SourceConfigurationRevision.objects.filter(source=source).update(number=9)
    with pytest.raises(DatabaseError, match="SOURCE_REVISION_FAMILY_INVALID"), transaction.atomic():
        SourceConfigurationRevision.objects.filter(source=source).update(is_current=False)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS source_revision_family_guard IMMEDIATE")
    with pytest.raises(DatabaseError, match="SOURCE_REVISION_BUILD_REQUIRED"), transaction.atomic():
        SourceConfigurationRevision.objects.filter(source=source).update(is_current=False)
        SourceConfigurationRevision.objects.filter(source=candidate).update(is_current=True)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS source_revision_family_guard IMMEDIATE")
    assert current_source(candidate).pk == source.pk


def test_nonowner_rls_and_guarded_migration_reversal(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL FORCE RLS and migration reversal")
    from importlib import import_module

    from django.apps import apps

    from apps.tenancy.context import set_tenant_scope

    migration = import_module("apps.ingestion.migrations.0033_source_configuration_revision")
    role = f"source_revision_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_connection, ingestion_restpullprofile, "
            f'ingestion_tenantrestpullprofilegrant FROM "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        candidate = create(governed_rest)
        assert SourceConfigurationRevision.objects.count() == 2
        set_tenant_scope(())
        assert not SourceConfigurationRevision.objects.exists()
        assert not Source.objects.filter(pk=candidate.pk).exists()
        with (
            connection.schema_editor() as editor,
            pytest.raises(RuntimeError, match="PRIVILEGED_ROLE"),
        ):
            migration.reverse(apps, editor)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
    with connection.schema_editor() as editor, pytest.raises(RuntimeError, match="EMPTY_HISTORY"):
        migration.reverse(apps, editor)
    assert SourceConfigurationRevision.objects.count() == 2


def test_wizard_edit_prefill_diff_save_and_hidden_candidate(client, governed_rest):
    from django.urls import reverse

    from apps.console.rest_setup_forms import visual_initial
    from apps.console.tests.test_rest_setup import advance

    _, actor, _, docset, old = governed_rest
    client.force_login(actor)
    detail = client.get(reverse("console:connector_source_detail", args=[old.pk]))
    assert detail.status_code == 200 and "Kaynak ayarlarını düzenle" in detail.content.decode()
    opened = client.get(reverse("console:connector_source_edit", args=[old.pk]))
    assert opened.status_code == 302
    url = opened.url
    page = client.get(url)
    assert page.context["form"].initial["name"] == old.name
    assert (
        advance(
            client, url, {"name": "Edited in wizard", "profile": str(old.rest_profile.public_id)}
        ).status_code
        == 302
    )
    page = client.get(url)
    assert page.context["form"].initial["path"] == old.rest_contract.definition["request"]["path"]
    assert advance(client, url, visual_initial(old.rest_contract.definition)).status_code == 302
    page = client.get(url)
    assert page.context["form"].initial["input_dataset"] == "legal"
    assert (
        advance(client, url, {"input_dataset": "wizard", "sync_mode": "manual"}).status_code == 302
    )
    review = client.get(url)
    assert {item["field"] for item in review.context["configuration_diff"]} == {
        "Kaynak adı",
        "Değişkenler",
    }
    saved = advance(client, url, {}, action="save")
    assert saved.status_code == 302
    candidate = Source.objects.get(name="Edited in wizard")
    assert current_source(candidate).pk == old.pk
    detail = client.get(saved.url)
    assert detail.status_code == 200 and "Geçmiş veya deneme ayarları" in detail.content.decode()
    assert client.get(url).url == saved.url
    listing = client.get(reverse("console:document_set_connectors_public", args=[docset.public_id]))
    assert "Edited in wizard" not in listing.content.decode()
    history = client.get(reverse("console:connector_source_detail", args=[old.pk]))
    assert "Edited in wizard" in history.content.decode()


def test_edit_role_scope_and_select_csrf(governed_rest):
    from django.contrib.auth import get_user_model
    from django.test import Client
    from django.urls import reverse

    from apps.identity.models import DocumentSetResponsibility, DocumentSetResponsibilityAssignment

    _, actor, org, _, source = governed_rest
    client = Client(enforce_csrf_checks=True)
    url = reverse("console:connector_source_edit", args=[source.pk])
    assert client.get(url).status_code == 302
    client.force_login(actor)
    assert (
        client.post(reverse("console:connector_source_select", args=[source.pk]), {}).status_code
        == 403
    )
    DocumentSetResponsibilityAssignment.objects.filter(membership__user=actor).update(
        responsibility=DocumentSetResponsibility.METADATA_VIEWER
    )
    assert client.get(url).status_code == 403
    assert (
        b"Kaynak ayarlar"
        not in client.get(reverse("console:connector_source_detail", args=[source.pk])).content
    )
    stranger = get_user_model().objects.create_user(username="stranger")
    client.force_login(stranger)
    assert client.get(url).status_code == 404
    with pytest.raises(RestAuthorizationError):
        create(governed_rest, actor=actor)
    assert not SourceConfigurationRevision.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_two_editors_do_not_lose_changes(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    barrier = Barrier(2)
    token = configuration_token(governed_rest[-1])

    def save(number):
        close_old_connections()
        try:
            barrier.wait()
            try:
                create(governed_rest, expected=token, name=f"Editor {number}")
                return "saved"
            except RestServiceError as exc:
                return exc.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [1, 2]))
    assert sorted(results) == ["SOURCE_REVISION_CHANGED", "saved"]
    assert SourceConfigurationRevision.objects.count() == 2


def prepare(actor, source, job, policy):
    from apps.ingestion.job_lifecycle import claim_build_job, complete_build_job
    from apps.ingestion.manual_preparation import prepare_source_snapshot
    from apps.ingestion.rest_setup_schedule import preparation_fingerprint
    from apps.ingestion.staged_build import build_staged_index

    build = prepare_source_snapshot(
        actor=actor,
        source=source,
        job_public_id=job.public_id,
        expected_policy=preparation_fingerprint(policy),
    )
    claimed = claim_build_job(
        public_id=str(build.public_id), organization_id=source.organization_id
    )
    assert claimed is not None
    assert claimed.document_set_version is not None and claimed.embedding_profile is not None
    index = build_staged_index(
        document_set_version=claimed.document_set_version,
        embedding_profile=claimed.embedding_profile,
        ocr_profile=claimed.ocr_profile,
        chunking_profile=claimed.chunking_profile,
        retrieval_profile=claimed.retrieval_profile,
        summary_model_profile=claimed.summary_model_profile,
        summary_prompt_contract=claimed.summary_prompt_contract,
        actor=str(actor.pk),
        build_job=claimed,
    )
    complete_build_job(
        job_id=claimed.pk,
        organization_id=source.organization_id,
        expected_attempt=claimed.attempt,
        index=index,
    )
    return index


@pytest.mark.django_db(transaction=True)
def test_real_snapshot_build_switch_and_restore(governed_rest, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Real pgvector preparation and serving transaction")
    from apps.documents.tests.test_phase_2_8_part_5 import _profiles
    from apps.ingestion.preparation import configure_preparation
    from apps.ingestion.rest_setup_schedule import preparation_fingerprint
    from apps.ingestion.source_revisions import select_source_revision
    from apps.ingestion.staged_build import promote_staged_index

    _, actor, org, docset, old = governed_rest
    embedding, chunking, retrieval = _profiles(org)
    policy = configure_preparation(
        document_set=docset,
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=False,
        actor=str(actor.pk),
    )
    old_job = run(actor, old)
    old_index = prepare(actor, old, old_job, policy)
    promote_staged_index(old_index, actor=str(actor.pk))
    configure_sync_schedule(
        actor=actor,
        source=old,
        enabled=True,
        interval_seconds=3600,
        next_run_at=timezone.now() + timedelta(hours=1),
    )
    candidate = create(
        governed_rest,
        schedule={"interval_seconds": 900, "preparation": preparation_fingerprint(policy)},
    )
    candidate_job = run(actor, candidate)
    new_index = prepare(actor, candidate, candidate_job, policy)
    with pytest.raises(StagedBuildError, match="SOURCE_REVISION_NOT_CURRENT"):
        promote_staged_index(new_index, actor=str(actor.pk))
    old_index.refresh_from_db()
    assert old_index.status == "active"
    token = configuration_token(candidate)
    with pytest.raises(RestServiceError, match="SOURCE_REVISION_BUILD_REQUIRED"):
        select_source_revision(actor=actor, source=candidate, expected=token, index_id=old_index.pk)
    from apps.ingestion.rest import RestPullError
    from apps.ingestion.rest_services import grant_rest_profile

    TenantRestPullProfileGrant.objects.filter(
        organization=org, document_set=docset, rest_profile=candidate.rest_profile
    ).delete()
    with pytest.raises(RestPullError, match="REST_PROFILE_NOT_GRANTED"):
        select_source_revision(actor=actor, source=candidate, expected=token, index_id=new_index.pk)
    grant_rest_profile(
        actor=governed_rest[0],
        organization=org,
        document_set=docset,
        rest_profile=candidate.rest_profile,
    )
    with pytest.raises(RestServiceError, match="SOURCE_REVISION_CHANGED"):
        select_source_revision(
            actor=actor, source=candidate, expected="0" * 64, index_id=new_index.pk
        )
    from apps.ingestion import source_revisions

    record = source_revisions.record_event

    def audit_failure(**kwargs):
        if kwargs["action"] == "ingestion.source_revision.selected":
            raise RuntimeError("audit unavailable")
        return record(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(source_revisions, "record_event", audit_failure)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            select_source_revision(
                actor=actor, source=candidate, expected=token, index_id=new_index.pk
            )
    assert current_source(candidate).pk == old.pk
    old_index.refresh_from_db()
    new_index.refresh_from_db()
    assert old_index.status == "active" and new_index.status == "promotable"
    assert ConnectorSyncSchedule.objects.get(source=old).enabled
    assert not ConnectorSyncSchedule.objects.filter(source=candidate).exists()
    assert (
        select_source_revision(
            actor=actor, source=candidate, expected=token, index_id=new_index.pk
        ).pk
        == candidate.pk
    )
    old_index.refresh_from_db()
    new_index.refresh_from_db()
    assert old_index.status == "superseded" and new_index.status == "active"
    assert current_source(old).pk == candidate.pk
    assert not ConnectorSyncSchedule.objects.get(source=old).enabled
    plan = ConnectorSyncSchedule.objects.get(source=candidate)
    assert plan.enabled and plan.interval_seconds == 900 and plan.automation_mode == "stage_only"
    assert (
        select_source_revision(
            actor=actor, source=candidate, expected=token, index_id=new_index.pk
        ).pk
        == candidate.pk
    )
    select_source_revision(
        actor=actor, source=old, expected=configuration_token(old), index_id=old_index.pk
    )
    old_index.refresh_from_db()
    new_index.refresh_from_db()
    assert old_index.status == "active" and new_index.status == "superseded"
    assert current_source(candidate).pk == old.pk
    assert ConnectorSyncSchedule.objects.get(source=old).enabled
    assert not ConnectorSyncSchedule.objects.get(source=candidate).enabled
    assert SourceConfigurationRevision.objects.count() == 2

    # Later unchanged fetches keep the exact preparation visible in both surfaces.
    from django.test import Client
    from django.urls import reverse

    unchanged = run(actor, old)
    assert _load_run(unchanged).candidate_set_version_id is None
    client = Client()
    client.force_login(actor)
    detail = client.get(reverse("console:connector_source_detail", args=[old.pk]))
    assert detail.context["source_preparation"]["job"].result_index_version_id == old_index.pk
    listing = client.get(reverse("console:document_set_connectors_public", args=[docset.public_id]))
    assert (
        listing.context["sources"][0]["preparation"]["job"].result_index_version_id == old_index.pk
    )

    # A prepared candidate must not erase newer documents from an unrelated source.
    from apps.ingestion.rest_services import create_rest_source

    other = create_rest_source(
        actor=actor,
        organization=org,
        document_set=docset,
        rest_profile=old.rest_profile,
        rest_contract=old.rest_contract,
        slug="another-source",
        name="Other source",
        inputs={"dataset": "other"},
    )
    other_job = run(actor, other)
    assert _load_run(other_job).candidate_set_version_id is not None
    with pytest.raises(RestServiceError, match="SOURCE_REVISION_BASELINE_CHANGED"):
        select_source_revision(
            actor=actor,
            source=candidate,
            expected=configuration_token(candidate),
            index_id=new_index.pk,
        )
    assert current_source(candidate).pk == old.pk
    old_index.refresh_from_db()
    assert old_index.status == "active"
    refreshed = run(actor, candidate)
    refreshed_version = _load_run(refreshed).candidate_set_version
    assert refreshed_version is not None
    assert set(
        refreshed_version.memberships.values_list(
            "document_version__document__source_id", flat=True
        )
    ) == {candidate.pk, other.pk}
