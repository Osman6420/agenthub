"""Bounded owner maintenance preserves data needed by runtime and release history."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.ingestion import shared_retention as service
from apps.ingestion.models import IndexVersion, SharedVectorChunk
from apps.ingestion.tests.test_shared_vector_storage import _generation, _row
from apps.ingestion.vector_store import VectorStoreError
from apps.tenancy.context import set_tenant_context


def _child(index):
    return IndexVersion.objects.create(
        organization_id=index.organization_id,
        version=2,
        parent_index_version=index,
        status="building",
        storage_layout="shared_v1",
        storage_state="open",
    )


def _wait_for_blocked(pid):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", [pid])
            if cursor.fetchone()[0]:
                return
        sleep(0.02)
    pytest.fail("Concurrent operation did not reach the database lock")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("retention_first", [True, False])
def test_parent_admission_and_retention_serialize_both_orders(old_generation, retention_first):
    index = old_generation
    backend = Queue()

    def contender():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend.put(cursor.fetchone()[0])
            with transaction.atomic():
                set_tenant_context(index.organization_id)
                return _child(index) if retention_first else reclaim(index, apply=True)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            set_tenant_context(index.organization_id)
            if retention_first:
                assert reclaim(index, apply=True).deleted == 3
            else:
                _child(index)
            pending = pool.submit(contender)
            _wait_for_blocked(backend.get(timeout=10))
        if retention_first:
            with pytest.raises(DatabaseError, match="GENERATION_PARENT_UNAVAILABLE"):
                pending.result(timeout=10)
            assert not IndexVersion.objects.filter(parent_index_version=index).exists()
            assert not SharedVectorChunk.objects.filter(index_version=index).exists()
        else:
            assert pending.result(timeout=10).reason == "SHARED_RETENTION_REFERENCED"
            assert SharedVectorChunk.objects.filter(index_version=index).count() == 3


def test_parent_scope_cannot_cross_organization(old_generation):
    from apps.tenancy.models import Organization

    foreign = Organization.objects.create(slug="foreign-retention", name="Foreign")
    with pytest.raises(DatabaseError, match="GENERATION_PARENT_UNAVAILABLE"), transaction.atomic():
        IndexVersion.objects.create(
            organization=foreign, version=2, parent_index_version=old_generation
        )


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL retention guard"),
]


@pytest.fixture
def old_generation():
    index, doc = _generation("retention")
    for ordinal in range(3):
        _row(index, doc, ordinal=ordinal)
    IndexVersion.objects.filter(pk=index.pk).update(
        status="promotable",
        storage_state="sealed",
        store_ready=True,
        updated_at=timezone.now() - timedelta(days=91),
    )
    index.refresh_from_db()
    return index


def reclaim(index, **kwargs):
    return service.reclaim_shared_generation(
        organization_id=index.organization_id,
        index_version_id=index.pk,
        actor="test-owner",
        **kwargs,
    )


def test_preview_bounded_resume_and_no_metadata_deletion(old_generation):
    index = old_generation
    assert reclaim(index).eligible and SharedVectorChunk.objects.count() == 3
    first = reclaim(index, apply=True, batch_size=2)
    assert first.deleted == 2 and first.remaining == 1
    index.refresh_from_db()
    assert index.storage_state == "retired" and not index.store_ready
    second = reclaim(index, apply=True, batch_size=2)
    assert second.deleted == 1 and second.remaining == 0
    assert reclaim(index, apply=True).deleted == 0
    assert IndexVersion.objects.filter(pk=index.pk).exists()
    assert AuditEvent.objects.filter(action="ingestion.shared_generation.reclaimed").count() == 2
    migration = import_module("apps.ingestion.migrations.0039_shared_vector_retention")
    with pytest.raises(RuntimeError, match="EMPTY_HISTORY"):
        migration.reverse(apps, connection.schema_editor(atomic=False))


def test_recent_active_and_derived_data_are_retained(old_generation):
    index = old_generation
    IndexVersion.objects.filter(pk=index.pk).update(updated_at=timezone.now())
    assert reclaim(index, apply=True).reason == "SHARED_RETENTION_TOO_RECENT"
    IndexVersion.objects.filter(pk=index.pk).update(
        status="active", updated_at=timezone.now() - timedelta(days=91)
    )
    assert reclaim(index, apply=True).reason == "SHARED_RETENTION_REFERENCED"
    IndexVersion.objects.filter(pk=index.pk).update(status="superseded")
    IndexVersion.objects.create(
        organization_id=index.organization_id,
        version=2,
        parent_index_version=index,
        status="building",
        storage_layout="shared_v1",
        storage_state="open",
    )
    assert reclaim(index, apply=True).reason == "SHARED_RETENTION_REFERENCED"
    assert SharedVectorChunk.objects.filter(index_version=index).count() == 3


def test_audit_failure_rolls_back_retirement_and_batch(old_generation, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "record_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        reclaim(old_generation, apply=True)
    old_generation.refresh_from_db()
    assert old_generation.storage_state == "sealed" and old_generation.store_ready
    assert SharedVectorChunk.objects.count() == 3


def test_runtime_role_cannot_retire_even_with_owner_flag(old_generation):
    role = f"retention_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT UPDATE ON ingestion_indexversion TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
    try:
        with pytest.raises(VectorStoreError, match="OWNER_REQUIRED"), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'SET LOCAL ROLE "{role}"')
            reclaim(old_generation, apply=True)
        with pytest.raises(DatabaseError), transaction.atomic():
            set_tenant_context(old_generation.organization_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.shared_vector_retention', 'on', true)")
                cursor.execute(f'SET LOCAL ROLE "{role}"')
                cursor.execute(
                    "UPDATE ingestion_indexversion SET storage_state='retired', "
                    "store_ready=false WHERE id=%s",
                    [old_generation.pk],
                )
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP OWNED BY "{role}"')
            cursor.execute(f'DROP ROLE "{role}"')
    assert SharedVectorChunk.objects.count() == 3
