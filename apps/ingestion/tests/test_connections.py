"""Exact connection identity, unchanged grants and protected profile provenance."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connection,
    transaction,
)

from apps.audit.models import AuditEvent
from apps.ingestion.connections import (
    ConnectionError,
    attach_source_connection,
    materialize_connection,
    verify_connection,
    verify_source_connection,
)
from apps.ingestion.models import Connection, RestPullProfile, Source, TenantRestPullProfileGrant
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile():
    return RestPullProfile.objects.create(
        logical_id="identity-profile", revision=1, host="api.example.com", created_by="test"
    )


def test_identity_is_idempotent_and_does_not_duplicate_transport_or_secret(profile):
    item = materialize_connection(profile=profile, actor="test")
    assert materialize_connection(profile=profile, actor="test").pk == item.pk
    assert verify_connection(item).pk == profile.pk
    assert not ({"host", "secret_ref", "config", "status"} & {f.name for f in item._meta.fields})
    event = AuditEvent.objects.get(action="connection.identity.materialized")
    assert "api.example.com" not in str(event.after)
    with pytest.raises(ValueError, match="immutable"):
        item.save()
    with pytest.raises(ValueError, match="immutable"):
        item.delete()
    item.profile_checksum = "0" * 64
    with pytest.raises(ConnectionError, match="MISMATCH"):
        verify_connection(item)


def test_legacy_source_mapping_is_explicit_authorized_idempotent_and_atomic(
    governed_rest, monkeypatch
):
    from django.contrib.auth import get_user_model

    from apps.tenancy.models import OrganizationMembership

    _, author, organization, document_set, original = governed_rest
    legacy = Source.objects.create(
        organization=organization,
        document_set=document_set,
        slug="legacy",
        name="Legacy",
        connector_type=original.connector_type,
        connector_config=original.connector_config,
        rest_profile=original.rest_profile,
        rest_contract=original.rest_contract,
    )
    outsider = get_user_model().objects.create_user("unassigned", password=None)
    OrganizationMembership.objects.create(organization=organization, user=outsider)
    with pytest.raises(ConnectionError, match="FORBIDDEN"):
        attach_source_connection(source=legacy, actor=outsider)

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("apps.ingestion.connections.record_event", unavailable)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            attach_source_connection(source=legacy, actor=author)
    legacy.refresh_from_db()
    assert legacy.connection_id is None
    mapped = attach_source_connection(source=legacy, actor=author)
    replay = attach_source_connection(source=legacy, actor=author)
    assert mapped.pk == replay.pk == legacy.pk
    assert mapped.connection_id == original.connection_id
    assert mapped.connector_config == original.connector_config
    assert mapped.rest_profile_id == original.rest_profile_id
    assert mapped.rest_contract_id == original.rest_contract_id
    assert (
        AuditEvent.objects.filter(action="source.connection.attached", outcome="success").count()
        == 1
    )
    assert (
        AuditEvent.objects.filter(action="source.connection.attached", outcome="deny").count() == 1
    )


def test_invalid_profile_and_audit_failure_cannot_leave_identity(profile, monkeypatch):
    profile.host = "localhost"
    # Direct legacy registry corruption is rejected before a new identity can be captured.
    RestPullProfile.objects.filter(pk=profile.pk).update(host="localhost")
    with pytest.raises(ConnectionError, match="INVALID"):
        materialize_connection(profile=profile, actor="test")
    assert not Connection.objects.exists()
    RestPullProfile.objects.filter(pk=profile.pk).update(host="api.example.com")

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.connections.record_event", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        materialize_connection(profile=profile, actor="test")
    assert not Connection.objects.exists()


def test_source_binding_preserves_live_grant_and_profile_checks(governed_rest):
    from apps.ingestion.rest import RestPullError
    from apps.ingestion.rest_services import create_rest_sync_run
    from apps.ingestion.rest_sync import _validate_runtime_grant

    _, author, _, _, source = governed_rest
    assert source.connection_id is not None
    profile = verify_source_connection(source)
    assert profile is not None and profile.pk == source.rest_profile_id
    run = create_rest_sync_run(actor=author, source=source)
    _validate_runtime_grant(run)
    TenantRestPullProfileGrant.objects.filter(rest_profile_id=source.rest_profile_id).delete()
    with pytest.raises(RestPullError, match="NOT_GRANTED"):
        _validate_runtime_grant(run)
    assert Connection.objects.filter(pk=source.connection_id).exists()
    RestPullProfile.objects.filter(pk=source.rest_profile_id).update(status="disabled")
    # The already loaded run/profile must not hide a subsequent profile disable.
    with pytest.raises(RestPullError, match="PROFILE_DISABLED"):
        _validate_runtime_grant(run)


def test_wrong_source_pointer_is_rejected_by_model_and_postgres(governed_rest, profile):
    *_, source = governed_rest
    foreign = materialize_connection(profile=profile, actor="test")
    source.connection = foreign
    with pytest.raises(ValidationError, match="MISMATCH"):
        source.full_clean(validate_unique=False, validate_constraints=False)
    if connection.vendor == "postgresql":
        with pytest.raises(IntegrityError, match="MISMATCH"), transaction.atomic():
            Source.objects.filter(pk=source.pk).update(connection=foreign)
        with pytest.raises(OperationalError, match="DOWNGRADE"), transaction.atomic():
            Source.objects.filter(pk=source.pk).update(connection=None)


def test_postgres_identity_and_referenced_profile_are_immutable(profile):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL write guards")
    item = materialize_connection(profile=profile, actor="test")
    with pytest.raises(OperationalError, match="IMMUTABLE"), transaction.atomic():
        Connection.objects.filter(pk=item.pk).update(profile_checksum="0" * 64)
    with pytest.raises(OperationalError, match="PROFILE_IMMUTABLE"), transaction.atomic():
        RestPullProfile.objects.filter(pk=profile.pk).update(host="changed.example.com")
    # Disable is live status, not an immutable transport revision edit.
    RestPullProfile.objects.filter(pk=profile.pk).update(status="disabled")
    assert verify_connection(item).status == "disabled"


@pytest.mark.django_db(transaction=True)
def test_concurrent_materialization_has_one_identity_and_audit(profile):
    if connection.vendor != "postgresql":
        pytest.skip("Real profile locking")
    barrier = Barrier(2)

    def capture(_):
        close_old_connections()
        try:
            barrier.wait()
            return materialize_connection(profile=profile, actor="test").pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(capture, range(2)))
    assert results[0] == results[1]
    assert Connection.objects.count() == 1
    assert AuditEvent.objects.filter(action="connection.identity.materialized").count() == 1


@pytest.mark.django_db(transaction=True)
def test_migration_maps_existing_profile_without_changing_legacy_source_contract(profile):
    if connection.vendor != "postgresql":
        pytest.skip("Historical migration model and PostgreSQL guards")
    from importlib import import_module

    from django.db.migrations.executor import MigrationExecutor

    historical = (
        MigrationExecutor(connection)
        .loader.project_state([("ingestion", "0021_connection_identity")])
        .apps
    )
    migration = import_module("apps.ingestion.migrations.0021_connection_identity")
    with connection.schema_editor() as editor:
        migration.map_existing_profiles(historical, editor)
        migration.map_existing_profiles(historical, editor)
    item = Connection.objects.get(rest_profile=profile)
    assert verify_connection(item).pk == profile.pk
    assert item.created_by == "connection-identity-migration"
    assert Connection.objects.count() == 1


def test_non_owner_source_creation_does_not_need_global_profile_write(governed_rest):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL readonly catalog privileges")
    from apps.ingestion.rest_services import create_rest_source
    from apps.tenancy.context import set_tenant_context

    _, author, organization, document_set, original = governed_rest
    role = f"connection_reader_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_restpullprofile, ingestion_confluenceprofile, "
            f'ingestion_connection FROM "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        set_tenant_context(organization.pk)
        source = create_rest_source(
            actor=author,
            organization=organization,
            document_set=document_set,
            rest_profile=original.rest_profile,
            rest_contract=original.rest_contract,
            slug="second",
            name="Second",
            inputs={"dataset": "legal"},
        )
        assert source.connection_id == original.connection_id
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
