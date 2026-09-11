"""Private durable setup, grant wait, stale writes and real PostgreSQL boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest
from django.apps import apps
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
from apps.console.rest_setup_views import SESSION_KEY
from apps.console.tests.test_rest_setup import advance, to_review
from apps.console.tests.test_rest_setup import wizard as wizard
from apps.documents.models import DocumentSet
from apps.identity.models import DocumentSetResponsibilityAssignment
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    RestPullContract,
    RestSetupDraft,
    Source,
    StagedIndexBuildJob,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    grant_rest_profile,
)
from apps.ingestion.rest_setup import create_rest_setup
from apps.ingestion.rest_setup_drafts import (
    load_setup_draft,
    save_setup_draft,
    validate_draft_payload,
)
from apps.ingestion.tests.test_rest_pull import _definition
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.context import set_tenant_scope
from apps.tenancy.models import Organization


def payload(setup, *, step=4):
    if step == 1:
        return {"name": "İzin bekleyen kurulum", "step": 1, "mode": "visual"}
    return {
        "name": "İzin bekleyen kurulum",
        "step": step,
        "mode": "visual",
        "profile": str(setup[4].rest_profile.public_id),
        "definition": _definition(),
        "inputs": {"dataset": "private-dataset-value"},
        "schedule": {"interval_seconds": 3600},
    }


def save(setup, **kwargs):
    return save_setup_draft(
        actor=setup[1],
        document_set=setup[3],
        intent=kwargs.pop("intent", uuid4()),
        payload=kwargs.pop("payload", payload(setup)),
        **kwargs,
    )


def resume_url(setup, draft):
    return reverse("console:rest_setup_resume", args=[setup[3].public_id, draft.public_id])


@pytest.mark.django_db
def test_no_grant_name_only_survives_new_session_then_resumes(client, wizard, governed_rest):
    TenantRestPullProfileGrant.objects.all().delete()
    result = advance(client, wizard, {"name": "Yeni bağlantı"}, action="save_draft")
    assert result.status_code == 302
    draft = RestSetupDraft.objects.get()
    assert draft.payload == {"name": "Yeni bağlantı", "step": 1, "mode": "visual"}
    assert not StagedIndexBuildJob.objects.exists() and not ConnectorSyncSchedule.objects.exists()
    assert Source.objects.count() == 1 and RestPullContract.objects.count() == 1
    # A different authenticated session starts with no in-progress form at all.
    fresh = Client()
    fresh.force_login(governed_rest[1])
    assert SESSION_KEY not in fresh.session
    listing = fresh.get(result["Location"])
    assert "Yeni bağlantı" in listing.content.decode()
    assert fresh.get(resume_url(governed_rest, draft)).status_code == 405
    response = fresh.post(resume_url(governed_rest, draft))
    assert response.status_code == 302
    assert fresh.get(response["Location"]).context["form"]["name"].value() == "Yeni bağlantı"
    grant_rest_profile(
        actor=governed_rest[0],
        organization=governed_rest[2],
        document_set=governed_rest[3],
        rest_profile=governed_rest[4].rest_profile,
    )
    assert (
        advance(
            fresh,
            response["Location"],
            {
                "name": "Yeni bağlantı",
                "profile": str(governed_rest[4].rest_profile.public_id),
            },
        ).status_code
        == 302
    )
    assert fresh.get(response["Location"]).context["step"] == 2


@pytest.mark.django_db
def test_revoked_grant_preserves_exact_review_and_regrant_finishes_once(
    client, wizard, governed_rest
):
    to_review(client, wizard, governed_rest)
    TenantRestPullProfileGrant.objects.all().delete()
    assert advance(client, wizard, {}, action="save_draft").status_code == 302
    draft = RestSetupDraft.objects.get()
    assert draft.payload["step"] == 4 and draft.payload["inputs"] == {
        "dataset": "private-dataset-value"
    }
    fresh = Client()
    fresh.force_login(governed_rest[1])
    url = fresh.post(resume_url(governed_rest, draft))["Location"]
    waiting = fresh.get(url)
    assert "Bağlantı izni bekleniyor" in waiting.content.decode()
    assert "private-dataset-value" not in waiting.content.decode()
    assert advance(fresh, url, {}, action="save").status_code == 200
    assert Source.objects.count() == 1
    grant_rest_profile(
        actor=governed_rest[0],
        organization=governed_rest[2],
        document_set=governed_rest[3],
        rest_profile=governed_rest[4].rest_profile,
    )
    review = fresh.get(url)
    assert review.context["step"] == 4
    submitted = {"submission": review.context["submission"], "action": "save"}
    response = fresh.post(url, submitted)
    assert response.status_code == 302
    assert fresh.post(url, submitted)["Location"] == response["Location"]
    draft.refresh_from_db()
    assert draft.payload == {} and draft.completed_source_id
    assert Source.objects.count() == 2 and RestPullContract.objects.count() == 2
    assert not StagedIndexBuildJob.objects.exists()
    assert fresh.post(resume_url(governed_rest, draft))["Location"] == response["Location"]
    events = list(AuditEvent.objects.filter(action__startswith="rest_setup_draft.").values())
    assert events and "private-dataset-value" not in json.dumps(events, default=str)


@pytest.mark.django_db
@pytest.mark.parametrize("step", [1, 2, 3, 4])
def test_checkpoint_roundtrip_all_steps(governed_rest, step):
    value = payload(governed_rest, step=step)
    draft = save(governed_rest, payload=value)
    loaded = load_setup_draft(
        actor=governed_rest[1], document_set=governed_rest[3], intent=draft.public_id
    )
    assert loaded.payload == value
    assert loaded.owner_id == governed_rest[1].pk and loaded.organization_id == governed_rest[2].pk


@pytest.mark.django_db
def test_two_sessions_cannot_overwrite_newer_checkpoint_or_complete_it(
    client, wizard, governed_rest
):
    to_review(client, wizard, governed_rest)
    advance(client, wizard, {}, action="save_draft")
    draft = RestSetupDraft.objects.get()
    fresh = Client()
    fresh.force_login(governed_rest[1])
    other_url = fresh.post(resume_url(governed_rest, draft))["Location"]
    assert advance(fresh, other_url, {}, action="save_draft").status_code == 302
    assert advance(client, wizard, {}, action="save_draft").status_code == 400
    assert advance(client, wizard, {}, action="save").status_code == 400
    draft.refresh_from_db()
    assert draft.revision == 2 and draft.completed_source_id is None
    assert Source.objects.count() == 1


@pytest.mark.django_db
def test_private_owner_scope_csrf_flag_and_revoked_authority(
    client, wizard, governed_rest, settings
):
    draft = save(governed_rest)
    admin = Client()
    admin.force_login(
        governed_rest[0]
    )  # even another manager/platform admin cannot read this draft
    assert admin.post(resume_url(governed_rest, draft)).status_code == 404
    assert (
        draft.name
        not in admin.get(
            reverse("console:document_set_connectors_public", args=[governed_rest[3].public_id])
        ).content.decode()
    )
    other = DocumentSet.objects.create(
        organization=governed_rest[2], logical_id="other", name="Other"
    )
    assert (
        admin.post(
            reverse("console:rest_setup_resume", args=[other.public_id, draft.public_id])
        ).status_code
        == 404
    )
    foreign_org = Organization.objects.create(slug="foreign", name="Foreign")
    foreign = DocumentSet.objects.create(
        organization=foreign_org, logical_id="foreign", name="Foreign"
    )
    assert (
        admin.post(
            reverse("console:rest_setup_resume", args=[foreign.public_id, draft.public_id])
        ).status_code
        == 404
    )
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(governed_rest[1])
    assert csrf.post(resume_url(governed_rest, draft)).status_code == 403
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = False
    assert client.post(resume_url(governed_rest, draft)).status_code == 404
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
    assert client.post(resume_url(governed_rest, draft)).status_code == 404
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    DocumentSetResponsibilityAssignment.objects.filter(membership__user=governed_rest[1]).update(
        status="revoked", revoked_at=timezone.now(), revoked_by=governed_rest[0]
    )
    assert client.post(resume_url(governed_rest, draft)).status_code in {403, 404}
    with pytest.raises(RestAuthorizationError):
        save(governed_rest)


@pytest.mark.django_db
def test_limit_expiry_and_stale_revision(governed_rest, monkeypatch):
    drafts = [save(governed_rest) for _ in range(5)]
    with pytest.raises(RestServiceError, match="DRAFT_LIMIT"):
        save(governed_rest)
    saved = save(governed_rest, intent=drafts[0].public_id, expected_revision=1)
    assert saved.revision == 2
    with pytest.raises(RestServiceError, match="DRAFT_CONFLICT"):
        save(governed_rest, intent=saved.public_id, expected_revision=1)
    after_expiry = timezone.now() + timedelta(days=31)
    monkeypatch.setattr("apps.ingestion.rest_setup_drafts.timezone.now", lambda: after_expiry)
    with pytest.raises(RestServiceError, match="UNAVAILABLE"):
        load_setup_draft(
            actor=governed_rest[1], document_set=governed_rest[3], intent=saved.public_id
        )
    with pytest.raises(RestServiceError, match="EXPIRED"):
        save(governed_rest, intent=saved.public_id, expected_revision=2)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "extra",
    [{"actor": 1}, {"sample": {}}, {"step": True}, {"profile": "invalid"}, {"name": "x" * 201}],
)
def test_closed_payload_and_size_boundaries(governed_rest, extra):
    with pytest.raises((RestServiceError, ValueError)):
        save(governed_rest, payload=payload(governed_rest) | extra)
    assert not RestSetupDraft.objects.exists()


def test_payload_recursion_and_nonfinite_values_rejected():
    base = {"name": "Draft", "step": 1, "mode": "visual"}
    values: list[Any] = [float("nan"), "x" * 160000, [[[[]]]]]
    for value in values:
        with pytest.raises(RestServiceError):
            validate_draft_payload(base | {"schedule": value})
    cyclic: dict = {}
    cyclic["schedule"] = cyclic
    with pytest.raises(RestServiceError):
        validate_draft_payload(base | cyclic)


@pytest.mark.django_db
def test_audit_failure_rolls_back_checkpoint_and_final_source(governed_rest, monkeypatch):
    original = import_module("apps.ingestion.rest_setup_drafts")._audit

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.rest_setup_drafts._audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        save(governed_rest)
    assert not RestSetupDraft.objects.exists()
    monkeypatch.setattr("apps.ingestion.rest_setup_drafts._audit", original)
    draft = save(governed_rest)
    monkeypatch.setattr("apps.ingestion.rest_setup_drafts._audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create_rest_setup(
            actor=governed_rest[1],
            document_set=governed_rest[3],
            intent=draft.public_id,
            profile_id=governed_rest[4].rest_profile.public_id,
            name=draft.name,
            definition=_definition(),
            inputs=draft.payload["inputs"],
            schedule={"interval_seconds": 3600},
            draft_revision=1,
        )
    draft.refresh_from_db()
    assert draft.revision == 1 and draft.completed_source_id is None and draft.payload
    assert Source.objects.count() == 1 and RestPullContract.objects.count() == 1
    assert not ConnectorSyncSchedule.objects.exists()


@pytest.mark.django_db
def test_postgres_binding_revision_source_guards_and_force_rls(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RLS and database lineage guards")
    draft = save(governed_rest)
    for changes in ({"owner": governed_rest[0]}, {"organization_id": 999}, {"public_id": uuid4()}):
        with pytest.raises(OperationalError, match="BINDING_IMMUTABLE"), transaction.atomic():
            RestSetupDraft.objects.filter(pk=draft.pk).update(**changes)
    with pytest.raises(IntegrityError, match="REVISION_INVALID"), transaction.atomic():
        RestSetupDraft.objects.filter(pk=draft.pk).update(name="Lost update")
    with pytest.raises(IntegrityError, match="SOURCE_INVALID"), transaction.atomic():
        RestSetupDraft.objects.filter(pk=draft.pk).update(
            completed_source=governed_rest[4], payload={}, revision=2
        )
    role = f"rest_draft_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        set_tenant_context(governed_rest[2].pk)
        assert RestSetupDraft.objects.filter(pk=draft.pk).exists()
        saved = save(governed_rest, intent=draft.public_id, expected_revision=1)
        assert saved.revision == 2
        set_tenant_context(999999)
        assert not RestSetupDraft.objects.exists()
        migration = import_module("apps.ingestion.migrations.0030_rest_setup_draft")
        with pytest.raises(RuntimeError, match="REQUIRES_PRIVILEGED_ROLE"):
            migration.reverse(apps, connection.schema_editor(atomic=False))
        set_tenant_scope(())
        assert not RestSetupDraft.objects.exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


@pytest.mark.django_db
def test_nonempty_migration_rollback_refused(governed_rest):
    save(governed_rest)
    migration = import_module("apps.ingestion.migrations.0030_rest_setup_draft")
    # The guard fails before the editor executes any DDL (including on SQLite).
    with pytest.raises(RuntimeError, match="REQUIRES_EMPTY_TABLE"):
        migration.reverse(apps, connection.schema_editor(atomic=False))


@pytest.mark.django_db(transaction=True)
def test_concurrent_checkpoint_writes_have_one_winner(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL organization row lock")
    draft = save(governed_rest)

    def write(name):
        close_old_connections()
        try:
            result = save(
                governed_rest,
                intent=draft.public_id,
                expected_revision=1,
                payload=payload(governed_rest) | {"name": name},
            )
            return result.name
        except RestServiceError as exc:
            assert exc.code == "REST_SETUP_DRAFT_CONFLICT"
            return None
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(write, name) for name in ("First", "Second")]
        results = [attempt.result() for attempt in attempts]
    assert results.count(None) == 1
    draft.refresh_from_db()
    assert draft.revision == 2 and draft.name in results
    assert RestSetupDraft.objects.count() == 1
