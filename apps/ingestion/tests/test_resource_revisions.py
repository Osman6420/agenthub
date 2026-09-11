"""Typed configuration changes preserve source, grant, snapshot and serving authority."""

from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import IntegrityError, OperationalError, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.documents.tests.test_phase_2_8_part_5 import _profiles
from apps.identity.models import DocumentSetResponsibilityAssignment
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
    TenantConfluenceProfileGrant,
    TenantMcpResourceGrant,
)
from apps.ingestion.preparation import configure_preparation
from apps.ingestion.resource_revisions import RESOURCE_REVISION_ERRORS, create_resource_revision
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    configure_sync_schedule,
)
from apps.ingestion.rest_setup_schedule import preparation_fingerprint
from apps.ingestion.snapshot import latest_trusted_candidate
from apps.ingestion.source_revisions import (
    configuration_token,
    current_source,
    select_source_revision,
)
from apps.ingestion.staged_build import StagedBuildError, promote_staged_index
from apps.ingestion.tests.test_confluence import _sync_page, _SyncClient
from apps.ingestion.tests.test_confluence import governed_source as governed_source
from apps.ingestion.tests.test_connector_jobs import isolated_delivery as isolated_delivery
from apps.ingestion.tests.test_mcp_services import create as create_mcp
from apps.ingestion.tests.test_mcp_services import setup as setup
from apps.ingestion.tests.test_mcp_sync import wire as wire
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.ingestion.tests.test_source_revisions import prepare

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["confluence", "mcp"])
def typed_source(request, settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    if request.param == "confluence":
        _, _, _, actor, source = request.getfixturevalue("governed_source")
    else:
        fixture = request.getfixturevalue("setup")
        actor, source = fixture[1], create_mcp(fixture, resource_prefixes=["file:///kb/"])
    return actor, source


def create(fixture, **overrides):
    actor, source = fixture
    profile = (
        source.connection.mcp_resource_profile
        if source.connector_type == "mcp_resource"
        else source.confluence_profile
    )
    return create_resource_revision(
        **(
            {
                "actor": actor,
                "source": source,
                "expected": configuration_token(source),
                "profile_id": profile.public_id,
                "intent": uuid4(),
                "name": "Edited resource",
                "config": source.connector_config.copy(),
            }
            | overrides
        )
    )


def run(actor, source):
    kwargs = {}
    if source.connector_type == "confluence_dc":
        page = _sync_page("100", 1, "Synthetic page")
        kwargs["confluence_client"] = _SyncClient([page], {"100": (page, b"<p>Body</p>")})
    job, _ = create_connector_job(actor=actor, source=source)
    assert (
        execute_connector_job(
            public_id=str(job.public_id), organization_id=source.organization_id, **kwargs
        )
        == "succeeded"
    )
    job.refresh_from_db()
    return job


def test_replay_cas_preserves_writer_and_saved_plan(typed_source):
    actor, old = typed_source
    configure_sync_schedule(
        actor=actor,
        source=old,
        interval_seconds=3600,
        enabled=True,
        next_run_at=timezone.now() + timedelta(hours=1),
    )
    expected, intent = configuration_token(old), uuid4()
    candidate = create(
        typed_source, expected=expected, intent=intent, schedule={"interval_seconds": 900}
    )
    assert current_source(candidate).pk == old.pk
    assert (
        candidate.connector_type == old.connector_type
        and candidate.document_set_id == old.document_set_id
    )
    assert ConnectorSyncSchedule.objects.get(source=old).enabled
    assert not ConnectorSyncSchedule.objects.filter(source=candidate).exists()
    assert (
        create(
            typed_source, expected=expected, intent=intent, schedule={"interval_seconds": 900}
        ).pk
        == candidate.pk
    )
    with pytest.raises(RestServiceError, match="INTENT_CONFLICT"):
        create(typed_source, expected=expected, intent=intent, name="Changed")
    with pytest.raises(RestServiceError, match="SOURCE_REVISION_CHANGED"):
        create(typed_source, expected=expected)
    assert SourceConfigurationRevision.objects.count() == 2
    assert (
        AuditEvent.objects.filter(
            action="ingestion.source_revision.created", outcome="success"
        ).count()
        == 1
    )


@pytest.mark.parametrize("blocker", ["grant", "role", "profile", "config", "disabled", "gate"])
def test_invalid_or_unapproved_change_is_atomic(typed_source, blocker, settings):
    actor, source = typed_source
    overrides = {}
    if blocker == "grant":
        TenantMcpResourceGrant.objects.filter(document_set=source.document_set).update(
            enabled=False
        )
        TenantConfluenceProfileGrant.objects.filter(document_set=source.document_set).delete()
    elif blocker == "role":
        DocumentSetResponsibilityAssignment.objects.filter(membership__user=actor).update(
            responsibility="metadata_viewer"
        )
    elif blocker == "profile":
        overrides["profile_id"] = uuid4()
    elif blocker == "config":
        overrides["config"] = source.connector_config | {
            "destination": "https://unreviewed.invalid"
        }
    elif blocker == "disabled":
        source.document_set.status = "quarantined"
        source.document_set.save(update_fields=["status", "updated_at"])
    else:
        settings.INGESTION_DURABLE_CONNECTOR_JOBS = False
    count = Source.objects.count()
    with pytest.raises(RESOURCE_REVISION_ERRORS):
        create(typed_source, **overrides)
    assert Source.objects.count() == count
    assert not SourceConfigurationRevision.objects.exists()


def test_required_audit_failure_rolls_back_family(typed_source, monkeypatch):
    import apps.ingestion.source_revisions as services

    original = services.record_event

    def unavailable(**kwargs):
        if kwargs["action"] == "ingestion.source_revision.created":
            raise RuntimeError("audit unavailable")
        return original(**kwargs)

    monkeypatch.setattr(services, "record_event", unavailable)
    count = Source.objects.count()
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create(typed_source)
    assert Source.objects.count() == count and not SourceConfigurationRevision.objects.exists()


def test_review_save_csrf_and_replay(typed_source):
    actor, old = typed_source
    client = Client(enforce_csrf_checks=True)
    url = reverse("console:connector_source_edit", args=[old.pk])
    assert client.get(url).status_code == 302
    client.force_login(actor)
    page = client.get(url)
    assert page.status_code == 200
    form = page.context["form"]
    payload = {key: value for key, value in form.initial.items() if value is not False}
    payload |= {"action": "review", "name": "Browser revision"}
    assert client.post(url, payload).status_code == 403
    payload["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
    assert client.post(url, payload | {"owner": actor.pk}).status_code == 400
    assert client.post(url, payload | {"action": "save"}).status_code == 400
    reviewed = client.post(url, payload)
    assert reviewed.status_code == 200, reviewed.content.decode()
    assert reviewed.context["review"]["name"] == "Browser revision"
    payload |= {"review": reviewed.context["form"].data["review"], "action": "save"}
    assert client.post(url, payload | {"name": "Tampered"}).status_code == 400
    saved = client.post(url, payload)
    assert saved.status_code == 302
    assert client.post(url, payload).url == saved.url
    candidate = Source.objects.get(name="Browser revision")
    assert current_source(candidate).pk == old.pk
    detail = client.get(saved.url)
    assert detail.status_code == 200
    assert "Yenileme planını düzenle" not in detail.content.decode()
    DocumentSetResponsibilityAssignment.objects.filter(membership__user=actor).update(
        responsibility="metadata_viewer"
    )
    assert client.get(url).status_code == 403 and client.post(url, payload).status_code == 403
    assert SourceConfigurationRevision.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_postgres_snapshot_build_selection_restore(typed_source, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Real pgvector build and deferred serving constraints")
    actor, old = typed_source
    embedding, chunking, retrieval = _profiles(old.organization)
    policy = configure_preparation(
        document_set=old.document_set,
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
        interval_seconds=3600,
        enabled=True,
        next_run_at=timezone.now() + timedelta(hours=1),
    )
    candidate = create(
        typed_source,
        schedule={"interval_seconds": 900, "preparation": preparation_fingerprint(policy)},
    )
    new_job = run(actor, candidate)
    new_version = _load_run(new_job).candidate_set_version
    assert set(
        new_version.memberships.values_list("document_version__document__source_id", flat=True)
    ) == {candidate.pk}
    assert latest_trusted_candidate(old.document_set).pk == old_index.document_set_version_id
    new_index = prepare(actor, candidate, new_job, policy)
    with pytest.raises(StagedBuildError, match="SOURCE_REVISION_NOT_CURRENT"):
        promote_staged_index(new_index, actor=str(actor.pk))
    token = configuration_token(candidate)
    with pytest.raises(RestServiceError, match="BUILD_REQUIRED"):
        select_source_revision(actor=actor, source=candidate, expected=token, index_id=old_index.pk)
    with pytest.raises((IntegrityError, OperationalError)), transaction.atomic():
        SourceConfigurationRevision.objects.filter(source=old).update(is_current=False)
        SourceConfigurationRevision.objects.filter(source=candidate).update(is_current=True)
    assert current_source(old).pk == old.pk
    if candidate.connector_type == "mcp_resource":
        grant = TenantMcpResourceGrant.objects.get(document_set=old.document_set)
        grant.enabled = False
        grant.save(update_fields=["enabled"])
    else:
        grant = TenantConfluenceProfileGrant.objects.get(document_set=old.document_set)
        grant.delete()
    with pytest.raises(RESOURCE_REVISION_ERRORS):
        select_source_revision(actor=actor, source=candidate, expected=token, index_id=new_index.pk)
    if candidate.connector_type == "mcp_resource":
        grant.enabled = True
        grant.save(update_fields=["enabled"])
    else:
        grant.pk = None
        grant.save(force_insert=True)
    assert current_source(old).pk == old.pk
    import apps.ingestion.source_revisions as services

    original = services.record_event

    def unavailable(**kwargs):
        if kwargs["action"] == "ingestion.source_revision.selected":
            raise RuntimeError("audit unavailable")
        return original(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(services, "record_event", unavailable)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            select_source_revision(
                actor=actor, source=candidate, expected=token, index_id=new_index.pk
            )
    assert current_source(old).pk == old.pk
    assert ConnectorSyncSchedule.objects.get(source=old).enabled
    select_source_revision(actor=actor, source=candidate, expected=token, index_id=new_index.pk)
    assert current_source(old).pk == candidate.pk
    assert not ConnectorSyncSchedule.objects.get(source=old).enabled
    new_plan = ConnectorSyncSchedule.objects.get(source=candidate)
    assert (
        new_plan.enabled
        and new_plan.interval_seconds == 900
        and new_plan.automation_mode == "stage_only"
    )
    assert (
        select_source_revision(
            actor=actor, source=candidate, expected=token, index_id=new_index.pk
        ).pk
        == candidate.pk
    )
    select_source_revision(
        actor=actor, source=old, expected=configuration_token(old), index_id=old_index.pk
    )
    assert current_source(candidate).pk == old.pk
    assert ConnectorSyncSchedule.objects.get(source=old).enabled
    assert not ConnectorSyncSchedule.objects.get(source=candidate).enabled


@pytest.mark.django_db(transaction=True)
def test_concurrent_editors_and_replay_have_one_revision(typed_source):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL transaction locks")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    expected, intent = configuration_token(typed_source[1]), uuid4()
    barrier = Barrier(2)

    def save(_):
        close_old_connections()
        try:
            barrier.wait()
            return create(typed_source, expected=expected, intent=intent).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert results[0] == results[1]
    assert SourceConfigurationRevision.objects.count() == 2


def test_legacy_family_writer_cannot_race_common_job(typed_source):
    if connection.vendor != "postgresql" or typed_source[1].connector_type != "confluence_dc":
        pytest.skip("PostgreSQL Confluence legacy writer")
    from apps.ingestion.models import ConfluenceSyncRun

    actor, old = typed_source
    candidate = create(typed_source)
    create_connector_job(actor=actor, source=old)
    with (
        pytest.raises((IntegrityError, OperationalError), match="SOURCE_BUSY"),
        transaction.atomic(),
    ):
        ConfluenceSyncRun.objects.create(
            organization=old.organization,
            source=candidate,
            confluence_profile=candidate.confluence_profile,
        )


def test_other_user_and_other_scope_cannot_open_or_replay(typed_source):
    from django.contrib.auth import get_user_model

    actor, source = typed_source
    client = Client()
    client.force_login(actor)
    url = reverse("console:connector_source_edit", args=[source.pk])
    page = client.get(url)
    values = page.context["form"].initial | {"action": "review"}
    outsider = get_user_model().objects.create_user(username="revision-outsider")
    client.force_login(outsider)
    assert client.get(url).status_code == 404
    assert client.post(url, values).status_code == 404
    with pytest.raises(RestAuthorizationError):
        create(typed_source, actor=outsider)
    assert not SourceConfigurationRevision.objects.exists()


def test_non_owner_revision_scope_and_catalog_read_only(typed_source):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RLS application role")
    from apps.tenancy.context import set_tenant_scope

    role = f"resource_revision_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_connection, ingestion_mcpresourceprofile, "
            "ingestion_confluenceprofile, ingestion_tenantmcpresourcegrant, "
            f'ingestion_tenantconfluenceprofilegrant FROM "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        candidate = create(typed_source)
        assert SourceConfigurationRevision.objects.filter(source=candidate).exists()
        set_tenant_scope(())
        assert not SourceConfigurationRevision.objects.exists()
        assert not Source.objects.filter(pk=candidate.pk).exists()
        migration = import_module("apps.ingestion.migrations.0037_resource_source_revisions")
        with (
            connection.schema_editor() as editor,
            pytest.raises(RuntimeError, match="PRIVILEGED_ROLE"),
        ):
            migration.reverse(apps, editor)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


def test_family_busy_and_candidate_schedule_denied(typed_source):
    actor, old = typed_source
    candidate = create(typed_source)
    create_connector_job(actor=actor, source=old)
    with pytest.raises(ConnectorJobError, match="SOURCE_BUSY"):
        create_connector_job(actor=actor, source=candidate)
    with pytest.raises(RestServiceError, match="SOURCE_REVISION_NOT_CURRENT"):
        configure_sync_schedule(
            actor=actor,
            source=candidate,
            interval_seconds=3600,
            enabled=True,
            next_run_at=timezone.now(),
        )


def test_sql_immutability_scope_and_reverse(typed_source):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL immutable scope")
    _, old = typed_source
    candidate = create(typed_source)
    for model, pk, change in [
        (Source, candidate.pk, {"name": "overwrite"}),
        (SourceConfigurationRevision, candidate.configuration_revision.pk, {"checksum": "0" * 64}),
    ]:
        with pytest.raises((IntegrityError, OperationalError)), transaction.atomic():
            model.objects.filter(pk=pk).update(**change)
    migration = import_module("apps.ingestion.migrations.0037_resource_source_revisions")
    with (
        connection.schema_editor() as editor,
        pytest.raises(RuntimeError, match="EMPTY_RESOURCE_HISTORY"),
    ):
        migration.reverse(apps, editor)
    assert current_source(candidate).pk == old.pk
