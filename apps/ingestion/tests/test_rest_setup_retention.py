"""Expiry cleanup is scoped, bounded, auditable and cannot revive private checkpoints."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.documents.models import DocumentSet
from apps.ingestion.models import RestSetupDraft, Source
from apps.ingestion.rest_services import RestServiceError
from apps.ingestion.rest_setup import create_rest_setup
from apps.ingestion.rest_setup_drafts import load_setup_draft, save_setup_draft
from apps.ingestion.rest_setup_retention import RestSetupRetentionError, purge_expired_setup_drafts
from apps.ingestion.tests.test_rest_pull import _definition
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def require_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL owner authority and expiry integrity")


def make_draft(setup, *, future=False, document_set=None, public_id=None, completed_source=None):
    document_set = document_set or setup[3]
    name = "Private setup label"
    return RestSetupDraft.objects.create(
        public_id=public_id or uuid4(),
        organization=document_set.organization,
        document_set=document_set,
        owner=setup[1],
        name=name,
        payload={} if completed_source else {"name": name, "step": 1, "mode": "visual"},
        completed_source=completed_source,
        expires_at=timezone.now() + timedelta(days=1 if future else -1),
    )


def test_preview_apply_scope_bounds_retry_and_safe_output(governed_rest):
    require_postgres()
    org = governed_rest[2]
    expired = [make_draft(governed_rest) for _ in range(3)]
    active = make_draft(governed_rest, future=True)
    foreign_org = Organization.objects.create(slug="retention-foreign", name="Foreign")
    foreign_set = DocumentSet.objects.create(
        organization=foreign_org, logical_id="foreign", name="Foreign"
    )
    foreign = make_draft(governed_rest, document_set=foreign_set)
    intent = uuid4()
    source = create_rest_setup(
        actor=governed_rest[1],
        document_set=governed_rest[3],
        profile_id=governed_rest[4].rest_profile.public_id,
        intent=intent,
        name="Completed source",
        definition=_definition(),
        inputs={"dataset": "fixture"},
    )
    completed = make_draft(governed_rest, public_id=intent, completed_source=source)
    original_source_count = Source.objects.count()
    output = StringIO()
    call_command(
        "purge_expired_rest_setups",
        organization_id=org.pk,
        actor="test-maintenance",
        batch_size=2,
        stdout=output,
    )
    assert json.loads(output.getvalue()) == {"candidates": 2, "purged": 0, "has_more": True}
    assert not RestSetupDraft.objects.filter(payload_purged_at__isnull=False).exists()
    assert not AuditEvent.objects.filter(action="rest_setup_draft.payload_purged").exists()
    first = purge_expired_setup_drafts(
        organization_id=org.pk, actor="test-maintenance", batch_size=2, apply=True
    )
    assert first.purged == 2 and first.has_more
    second = purge_expired_setup_drafts(
        organization_id=org.pk, actor="test-maintenance", apply=True
    )
    assert second.purged == 1 and not second.has_more
    assert (
        purge_expired_setup_drafts(
            organization_id=org.pk, actor="test-maintenance", apply=True
        ).purged
        == 0
    )
    for draft in expired:
        draft.refresh_from_db()
        assert draft.payload == {} and draft.name == "" and draft.revision == 2
        assert draft.payload_purged_at >= draft.expires_at
        assert (
            draft.owner_id == governed_rest[1].pk and draft.document_set_id == governed_rest[3].pk
        )
    for draft in (active, foreign, completed):
        draft.refresh_from_db()
        assert draft.payload_purged_at is None and draft.revision == 1 and draft.name
    assert Source.objects.count() == original_source_count
    events = AuditEvent.objects.filter(action="rest_setup_draft.payload_purged")
    assert events.count() == 3
    assert all(e.organization_id == org.pk and e.request_id for e in events)
    assert all(e.after == {"revision": 2} and e.before == {"revision": 1} for e in events)
    assert "Private setup label" not in str(list(events.values()))


def test_audit_failure_rolls_back_entire_batch(governed_rest, monkeypatch):
    require_postgres()
    drafts = [make_draft(governed_rest) for _ in range(2)]
    from apps.ingestion import rest_setup_retention

    original = rest_setup_retention.record_event
    calls = 0

    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("audit unavailable")
        return original(**kwargs)

    monkeypatch.setattr(rest_setup_retention, "record_event", fail_second)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        purge_expired_setup_drafts(organization_id=governed_rest[2].pk, actor="test", apply=True)
    for draft in drafts:
        draft.refresh_from_db()
        assert draft.payload and draft.name and draft.payload_purged_at is None
        assert draft.revision == 1
    assert not AuditEvent.objects.filter(action="rest_setup_draft.payload_purged").exists()


def test_sql_forbids_early_purge_refill_and_forged_purge_insert(governed_rest):
    require_postgres()
    active = make_draft(governed_rest, future=True)
    with pytest.raises(DatabaseError, match="PURGE_INVALID"), transaction.atomic():
        RestSetupDraft.objects.filter(pk=active.pk).update(
            payload={}, name="", payload_purged_at=timezone.now(), revision=2
        )
    expired = make_draft(governed_rest)
    purge_expired_setup_drafts(organization_id=governed_rest[2].pk, actor="test", apply=True)
    expired.refresh_from_db()
    for values in ({"payload": {"name": "resurrected"}}, {"payload_purged_at": None}):
        with pytest.raises(DatabaseError, match="BINDING_IMMUTABLE"), transaction.atomic():
            RestSetupDraft.objects.filter(pk=expired.pk).update(revision=3, **values)
    with pytest.raises(ValueError, match="BINDING_IMMUTABLE"):
        expired.save(update_fields=["payload"])
    with pytest.raises(DatabaseError, match="PURGE_INVALID"), transaction.atomic():
        RestSetupDraft.objects.bulk_create(
            [
                RestSetupDraft(
                    organization=governed_rest[2],
                    document_set=governed_rest[3],
                    owner=governed_rest[1],
                    name="",
                    payload={},
                    expires_at=timezone.now() - timedelta(days=1),
                    payload_purged_at=timezone.now(),
                )
            ]
        )


def test_app_role_cannot_impersonate_owner_or_directly_purge(governed_rest):
    require_postgres()
    draft = make_draft(governed_rest)
    role = f"retention_app_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, UPDATE ON ingestion_restsetupdraft TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        for apply in (False, True):
            with pytest.raises(RestSetupRetentionError, match="OWNER_REQUIRED"):
                purge_expired_setup_drafts(
                    organization_id=governed_rest[2].pk, actor="table-owner", apply=apply
                )
        set_tenant_context(governed_rest[2].pk)
        with pytest.raises(DatabaseError, match="OWNER_REQUIRED"), transaction.atomic():
            RestSetupDraft.objects.filter(pk=draft.pk).update(
                payload={}, name="", payload_purged_at=timezone.now(), revision=F("revision") + 1
            )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
    draft.refresh_from_db()
    assert draft.payload and draft.payload_purged_at is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"batch_size": 0},
        {"batch_size": 501},
        {"batch_size": True},
        {"organization_id": True},
        {"organization_id": 0},
        {"actor": ""},
        {"actor": "private\ntext"},
        {"apply": "yes"},
    ],
)
def test_invalid_input_never_admits_a_batch(overrides):
    with pytest.raises(RestSetupRetentionError, match="INPUT_INVALID"):
        purge_expired_setup_drafts(**({"organization_id": 1, "actor": "test"} | overrides))


def test_sqlite_cannot_claim_owner_authority():
    if connection.vendor == "postgresql":
        pytest.skip("SQLite boundary")
    with pytest.raises(RestSetupRetentionError, match="REQUIRES_POSTGRESQL"):
        purge_expired_setup_drafts(organization_id=1, actor="test")


def test_purged_checkpoint_remains_unavailable_in_console(governed_rest, client, settings):
    require_postgres()
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    draft = make_draft(governed_rest)
    purge_expired_setup_drafts(organization_id=governed_rest[2].pk, actor="test", apply=True)
    client.force_login(governed_rest[1])
    url = reverse("console:rest_setup_resume", args=[governed_rest[3].public_id, draft.public_id])
    assert client.post(url).status_code == 404
    with pytest.raises(RestServiceError, match="UNAVAILABLE"):
        load_setup_draft(
            actor=governed_rest[1], document_set=governed_rest[3], intent=draft.public_id
        )
    with pytest.raises(RestServiceError, match="EXPIRED"):
        save_setup_draft(
            actor=governed_rest[1],
            document_set=governed_rest[3],
            intent=draft.public_id,
            expected_revision=2,
            payload={"name": "New private data", "step": 1, "mode": "visual"},
        )


@pytest.mark.django_db(transaction=True)
def test_concurrent_cleanup_cannot_double_purge(governed_rest):
    require_postgres()
    draft = make_draft(governed_rest)
    barrier = Barrier(2)

    def purge(_):
        close_old_connections()
        try:
            barrier.wait(timeout=15)
            return purge_expired_setup_drafts(
                organization_id=governed_rest[2].pk, actor="test", apply=True
            ).purged
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(purge, [1, 2])) == [0, 1]
    draft.refresh_from_db()
    assert draft.revision == 2
    assert AuditEvent.objects.filter(action="rest_setup_draft.payload_purged").count() == 1


@pytest.mark.django_db(transaction=True)
def test_retention_migration_preserves_old_payload_and_purge_evidence(governed_rest):
    require_postgres()
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    previous = [("ingestion", "0035_tenant_tool_connections")]
    try:
        executor.migrate(previous)
        history = executor.loader.project_state(previous).apps.get_model(
            "ingestion", "RestSetupDraft"
        )
        draft = history.objects.create(
            organization_id=governed_rest[2].pk,
            document_set_id=governed_rest[3].pk,
            owner_id=governed_rest[1].pk,
            name="Historical private label",
            payload={"name": "Historical private label", "step": 1, "mode": "visual"},
            expires_at=timezone.now() - timedelta(days=1),
        )
        MigrationExecutor(connection).migrate(latest)
        current = RestSetupDraft.objects.get(pk=draft.pk)
        assert current.payload == draft.payload and current.payload_purged_at is None
        purge_expired_setup_drafts(organization_id=governed_rest[2].pk, actor="test", apply=True)
        with pytest.raises(RuntimeError, match="ROLLBACK_REQUIRES_EMPTY_HISTORY"):
            MigrationExecutor(connection).migrate(previous)
        current.refresh_from_db()
        assert current.payload_purged_at and current.payload == {}
    finally:
        MigrationExecutor(connection).migrate(latest)
