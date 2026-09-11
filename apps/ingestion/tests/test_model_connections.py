"""Model identities preserve catalogue provenance and grant separation."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.audit.models import AuditEvent
from apps.ingestion.connections import ConnectionError, materialize_connection, verify_connection
from apps.ingestion.embedding_services import register_embedding_profile
from apps.ingestion.models import (
    Connection,
    EmbeddingProfile,
    OcrProfile,
    TenantEmbeddingProfileGrant,
    TenantOcrProfileGrant,
)
from apps.ingestion.ocr_services import register_ocr_profile
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.orchestration.models import ModelProfile
from apps.orchestration.services import register_model_profile

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["model", "embedding", "ocr"])
def specification(request):
    kind = request.param
    model, register = {
        "model": (ModelProfile, register_model_profile),
        "embedding": (EmbeddingProfile, register_embedding_profile),
        "ocr": (OcrProfile, register_ocr_profile),
    }[kind]
    values = {
        "logical_id": f"typed-{kind}",
        "revision": 1,
        "host": f"{kind}.example.com",
        "secret_ref": "secret:fixture",
    }
    if kind != "ocr":
        values["model"] = "test-model"
    if kind == "embedding":
        values["dimensions"] = 64
    unsaved = model(**values)
    fields = {
        field.name: getattr(unsaved, field.name)
        for field in model._meta.concrete_fields
        if field.name not in {"id", "public_id", "created_at", "created_by", "status"}
    }
    return kind, model, register, fields


@pytest.fixture
def admin():
    return get_user_model().objects.create_superuser(username="catalog-admin", password=None)


def test_registration_maps_exact_identity_without_grant_or_secret_copy(specification, admin):
    kind, _, register, fields = specification
    profile = register(actor=admin, **fields)
    item = Connection.objects.get(**{f"{kind}_profile": profile})
    assert item.kind == kind and item.revision == profile.revision
    assert verify_connection(item) == profile
    assert materialize_connection(profile=profile, actor="reader").pk == item.pk
    assert not TenantEmbeddingProfileGrant.objects.exists()
    assert not TenantOcrProfileGrant.objects.exists()
    event = AuditEvent.objects.get(action="connection.identity.materialized")
    assert fields["host"] not in str(event.after) and fields["secret_ref"] not in str(event.after)
    assert not {"config", "host", "secret_ref", "status"} & {f.name for f in item._meta.fields}
    next_profile = register(actor=admin, **(fields | {"revision": 2}))
    assert materialize_connection(profile=next_profile, actor="reader").pk != item.pk
    assert verify_connection(item) == profile
    profile.status = "disabled"
    profile.save(update_fields=["status"])
    assert verify_connection(item).status == "disabled"
    with pytest.raises(ConnectionError, match="PROFILE_DISABLED"):
        materialize_connection(profile=profile, actor="reader", require_active=True)


def test_registration_authority_and_audit_failure_are_atomic(specification, admin, monkeypatch):
    _, model, register, fields = specification
    user = get_user_model().objects.create_user(username="tenant-member")
    with pytest.raises(PermissionError, match="PLATFORM_ADMIN_REQUIRED"):
        register(actor=user, **fields)
    assert not model.objects.exists() and not Connection.objects.exists()

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.connections.record_event", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        register(actor=admin, **fields)
    assert not model.objects.exists() and not Connection.objects.exists()


def test_wrong_type_checksum_and_profile_mutation_are_rejected(specification, admin):
    kind, model, register, fields = specification
    profile = register(actor=admin, **fields)
    item = materialize_connection(profile=profile, actor="reader")
    item.profile_checksum = "0" * 64
    with pytest.raises(ConnectionError, match="PROFILE_MISMATCH"):
        verify_connection(item)
    item.refresh_from_db()
    item.kind = "rest_pull"
    with pytest.raises(ConnectionError, match="PROFILE_UNRESOLVED"):
        verify_connection(item)
    if connection.vendor == "postgresql":
        with pytest.raises(DatabaseError, match="PROFILE_IMMUTABLE"), transaction.atomic():
            model.objects.filter(pk=profile.pk).update(host="changed.example.com")
        with pytest.raises(DatabaseError, match="CONNECTION_IMMUTABLE"), transaction.atomic():
            Connection.objects.filter(pk=item.pk).update(kind="rest_pull")
        # SQL insertion cannot forge a matching type with another profile's identity.
        with pytest.raises(DatabaseError, match="PROFILE_MISMATCH"), transaction.atomic():
            Connection.objects.bulk_create(
                [
                    Connection(
                        kind=kind,
                        logical_id="forged",
                        revision=1,
                        profile_checksum="a" * 64,
                        created_by="test",
                        **{f"{kind}_profile": profile},
                    )
                ]
            )


@pytest.mark.django_db(transaction=True)
def test_historical_mapping_is_frozen_idempotent_and_reverse_preserves_it(specification):
    kind, model, _, fields = specification
    profile = model.objects.create(created_by="legacy", **fields)
    history = (
        MigrationExecutor(connection)
        .loader.project_state([("ingestion", "0034_typed_model_connections")])
        .apps
    )
    migration = import_module("apps.ingestion.migrations.0034_typed_model_connections")
    with connection.schema_editor() as editor:
        migration.map_existing_profiles(history, editor)
        migration.map_existing_profiles(history, editor)
        with pytest.raises(RuntimeError, match="ROLLBACK_REQUIRES_EMPTY_HISTORY"):
            migration.reverse(history, editor)
    item = Connection.objects.get(kind=kind)
    assert verify_connection(item) == profile
    assert item.created_by == "typed-model-connection-migration"
    assert Connection.objects.count() == 1 and model.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_mapping_creates_one_identity(specification):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL profile row locks")
    _, model, _, fields = specification
    profile = model.objects.create(created_by="legacy", **fields)
    barrier = Barrier(2)

    def resolve(_):
        close_old_connections()
        try:
            barrier.wait()
            return materialize_connection(profile=profile, actor="migration").pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(resolve, [1, 2]))
    assert ids[0] == ids[1]
    assert Connection.objects.count() == 1
    assert AuditEvent.objects.filter(action="connection.identity.materialized").count() == 1


def test_normal_role_reads_mapped_catalog_without_global_writes(specification, admin):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL least privilege role")
    _, _, register, fields = specification
    profile = register(actor=admin, **fields)
    role = f"model_connection_reader_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(
            "GRANT SELECT ON ingestion_connection, orchestration_modelprofile, "
            f'ingestion_embeddingprofile, ingestion_ocrprofile TO "{role}"'
        )
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        item = materialize_connection(profile=profile, actor="reader", require_active=True)
        assert verify_connection(item) == profile
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


def test_model_identity_is_not_an_ingestion_source(specification, admin, governed_rest):
    from apps.ingestion.connections import verify_source_connection
    from apps.ingestion.models import Source

    _, _, register, fields = specification
    profile = register(actor=admin, **fields)
    item = materialize_connection(profile=profile, actor="reader")
    source = Source(connector_type="generic_rest", connection=item)
    with pytest.raises(ConnectionError, match="SOURCE_CONNECTION_MISMATCH"):
        verify_source_connection(source)
    if connection.vendor == "postgresql":
        with pytest.raises(DatabaseError, match="SOURCE_CONNECTION_MISMATCH"), transaction.atomic():
            Source.objects.filter(pk=governed_rest[-1].pk).update(connection=item)


@pytest.mark.django_db(transaction=True)
def test_empty_migration_roundtrip_and_existing_profile_mapping():
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("ingestion", "0033_source_configuration_revision")])
        before = executor.loader.project_state(
            [
                ("ingestion", "0033_source_configuration_revision"),
                ("orchestration", "0001_modelprofile"),
            ]
        ).apps
        fixture_reference = "secret:fixture"
        profile = before.get_model("orchestration", "ModelProfile").objects.create(
            logical_id="historical-chat",
            revision=1,
            host="model.example.com",
            model="chat",
            secret_ref=fixture_reference,
            created_by="historical",
        )
        MigrationExecutor(connection).migrate(current)
        item = Connection.objects.get(model_profile_id=profile.pk)
        assert item.logical_id == "historical-chat"
        assert verify_connection(item).pk == profile.pk
        with pytest.raises(RuntimeError, match="ROLLBACK_REQUIRES_EMPTY_HISTORY"):
            MigrationExecutor(connection).migrate(
                [("ingestion", "0033_source_configuration_revision")]
            )
        assert Connection.objects.filter(pk=item.pk, model_profile_id=profile.pk).exists()
    finally:
        MigrationExecutor(connection).migrate(current)
