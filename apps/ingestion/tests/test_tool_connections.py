"""Tenant tool identities must not become global grants or mutable configuration."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier, Event, Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.apps import apps
from django.conf import settings
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.ingestion.connections import (
    ConnectionError,
    materialize_connection,
    verify_connection,
    verify_source_connection,
)
from apps.ingestion.models import Connection, Source
from apps.orchestration.models import ModelProfile
from apps.tenancy.context import set_tenant_context, set_tenant_scope
from apps.tenancy.models import Organization
from apps.tenancy.rls import inspect_rls_readiness, protected_tenant_tables
from apps.tools.models import ToolBinding, ToolDefinition, ToolInvocation
from apps.tools.services import register_tool_definition
from apps.tools.tests.test_tool_registry import _definition_body

pytestmark = pytest.mark.django_db


def artifact_for(org, protocol="http"):
    body = _definition_body(risk="high", side_effecting=True)
    body["spec"]["allowed_organizations"] = [org.slug]
    fixture_reference = "secret:tool-identity-fixture"
    body["spec"]["secret_ref"] = fixture_reference
    body["spec"]["protocol"] = protocol
    if protocol == "mcp":
        body["spec"].pop("method")
    return create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_DEFINITION,
        logical_id="search",
        body=body,
        created_by="platform-fixture",
    )


def historical_definition(artifact, **overrides):
    return ToolDefinition.objects.create(
        **{
            "organization_id": artifact.organization_id,
            "logical_id": artifact.logical_id,
            "version": artifact.version,
            "manifest": artifact.body,
            "checksum": artifact.checksum,
            "protocol": artifact.body["spec"]["protocol"],
            "risk": artifact.body["spec"]["risk"],
            "side_effecting": artifact.body["spec"]["side_effecting"],
            **overrides,
        }
    )


@pytest.mark.parametrize("protocol", ["http", "mcp"])
def test_registration_is_exact_scoped_idempotent_and_grants_no_execution(protocol):
    org = Organization.objects.create(slug="tool-one", name="One")
    artifact = artifact_for(org, protocol)
    definition = register_tool_definition(artifact=artifact)
    item = Connection.objects.get(tool_definition=definition)
    assert item.kind == "tool" and item.organization_id == org.pk
    assert item.revision == definition.version and verify_connection(item) == definition
    assert register_tool_definition(artifact=artifact).pk == definition.pk
    assert Connection.objects.count() == 1
    assert not ToolBinding.objects.exists() and not ToolInvocation.objects.exists()
    assert definition.requires_approval
    event = AuditEvent.objects.get(action="connection.identity.materialized")
    assert event.organization_id == org.pk
    assert event.actor_id == artifact.created_by
    assert event.after == {"kind": "tool", "profile_id": str(definition.pk)}
    assert "example.com" not in str(event.after) and "secret:" not in str(event.after)
    definition.status = "disabled"
    definition.save(update_fields=["status", "updated_at"])
    assert verify_connection(item).status == "disabled"
    assert register_tool_definition(artifact=artifact).status == "disabled"
    with pytest.raises(ConnectionError, match="PROFILE_DISABLED"):
        materialize_connection(profile=definition, actor="reader", require_active=True)
    with pytest.raises(ConnectionError, match="SOURCE_CONNECTION_MISMATCH"):
        verify_source_connection(Source(connector_type="generic_rest", connection=item))


def test_same_name_and_version_in_two_tenants_have_distinct_identity():
    first = Organization.objects.create(slug="first", name="First")
    second = Organization.objects.create(slug="second", name="Second")
    definitions = [register_tool_definition(artifact=artifact_for(org)) for org in (first, second)]
    items = [Connection.objects.get(tool_definition=definition) for definition in definitions]
    assert items[0].pk != items[1].pk
    assert items[0].logical_id == items[1].logical_id == "search"
    assert items[0].revision == items[1].revision == 1
    assert items[0].profile_checksum != items[1].profile_checksum
    items[0].organization_id = second.pk
    with pytest.raises(ConnectionError, match="PROFILE_MISMATCH"):
        verify_connection(items[0])


def test_registration_and_identity_roll_back_on_audit_failure(monkeypatch):
    org = Organization.objects.create(slug="atomic", name="Atomic")
    artifact = artifact_for(org)

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.connections.record_event", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        register_tool_definition(artifact=artifact)
    assert not ToolDefinition.objects.exists() and not Connection.objects.exists()


@pytest.mark.parametrize("change", [{"checksum": "0" * 64}, {"risk": "low"}])
def test_invalid_historical_definition_is_never_mapped(change):
    org = Organization.objects.create(slug="invalid", name="Invalid")
    definition = historical_definition(artifact_for(org), **change)
    with pytest.raises(ConnectionError, match="PROFILE_INVALID"):
        materialize_connection(profile=definition, actor="migration")
    migration = import_module("apps.ingestion.migrations.0035_tenant_tool_connections")
    with pytest.raises(RuntimeError, match="HISTORICAL_PROFILE_INVALID"):
        migration.map_existing_tools(apps, SimpleNamespace(connection=connection))
    assert not Connection.objects.exists()


def test_sql_lineage_and_configuration_seals():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL integrity triggers")
    org = Organization.objects.create(slug="seals", name="Seals")
    foreign = Organization.objects.create(slug="foreign", name="Foreign")
    definition = register_tool_definition(artifact=artifact_for(org))
    item = Connection.objects.get(tool_definition=definition)
    for change in ({"risk": "low"}, {"organization_id": foreign.pk}, {"checksum": "0" * 64}):
        with pytest.raises(DatabaseError, match="PROFILE_IMMUTABLE"), transaction.atomic():
            ToolDefinition.objects.filter(pk=definition.pk).update(**change)
    with pytest.raises(DatabaseError, match="PROFILE_IMMUTABLE"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tools_tooldefinition WHERE id = %s", [definition.pk])
    with pytest.raises(DatabaseError, match="CONNECTION_IMMUTABLE"), transaction.atomic():
        Connection.objects.filter(pk=item.pk).update(profile_checksum="0" * 64)
    with pytest.raises(DatabaseError, match="PROFILE_MISMATCH"), transaction.atomic():
        Connection.objects.bulk_create(
            [
                Connection(
                    kind="tool",
                    organization=foreign,
                    tool_definition=definition,
                    logical_id=definition.logical_id,
                    revision=definition.version,
                    profile_checksum=item.profile_checksum,
                    created_by="forged",
                )
            ]
        )


def test_real_app_role_reads_globals_but_only_maps_tools_in_current_scope():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL FORCE RLS and least privilege")
    org = Organization.objects.create(slug="own", name="Own")
    foreign = Organization.objects.create(slug="other", name="Other")
    own_artifact = artifact_for(org)
    foreign_artifact = artifact_for(foreign)
    foreign_definition = register_tool_definition(artifact=foreign_artifact)
    foreign_item = Connection.objects.get(tool_definition=foreign_definition)
    fixture_reference = "secret:fixture"
    global_profile = ModelProfile.objects.create(
        logical_id="global",
        revision=1,
        host="model.example.com",
        model="fixture",
        secret_ref=fixture_reference,
        created_by="platform",
    )
    global_item = materialize_connection(profile=global_profile, actor="platform")
    # An unmapped global profile proves the INSERT policy itself, even if a caller
    # accidentally had a profile row-lock privilege.
    spare_global = ModelProfile.objects.create(
        logical_id="spare",
        revision=1,
        host="model.example.com",
        model="fixture",
        secret_ref=fixture_reference,
        created_by="platform",
    )
    role = f"tool_identity_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        cursor.execute(
            "GRANT SELECT ON ingestion_connection, tools_tooldefinition, "
            "tenancy_organization, orchestration_modelprofile, artifacts_artifactversion, "
            "audit_auditevent "
            f'TO "{role}"'
        )
        cursor.execute(
            "GRANT INSERT ON ingestion_connection, tools_tooldefinition, "
            f'audit_auditevent TO "{role}"'
        )
        cursor.execute(f'GRANT UPDATE ON orchestration_modelprofile TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        set_tenant_scope(())
        assert list(Connection.objects.values_list("pk", flat=True)) == [global_item.pk]
        assert verify_connection(global_item) == global_profile
        with pytest.raises(ConnectionError, match="PROFILE_UNRESOLVED"):
            materialize_connection(profile=foreign_definition, actor="reader")
        set_tenant_context(org.pk)
        definition = register_tool_definition(artifact=own_artifact)
        item = materialize_connection(profile=definition, actor="reader")
        assert item.organization_id == org.pk
        assert set(Connection.objects.values_list("pk", flat=True)) == {global_item.pk, item.pk}
        with pytest.raises(ConnectionError, match="PROFILE_UNRESOLVED"):
            verify_connection(foreign_item)
        with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
            register_tool_definition(artifact=foreign_artifact)
        with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
            materialize_connection(profile=spare_global, actor="not-platform")
        with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
            Connection.objects.filter(pk=item.pk).update(created_by="changed")
        set_tenant_scope(())
        assert list(Connection.objects.values_list("pk", flat=True)) == [global_item.pk]
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
    assert Connection.objects.count() == 3


@pytest.mark.django_db(transaction=True)
def test_concurrent_registration_creates_one_definition_and_audited_identity():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL concurrent row admission")
    org = Organization.objects.create(slug="race", name="Race")
    artifact = artifact_for(org)
    barrier = Barrier(2)

    def register(_):
        close_old_connections()
        try:
            barrier.wait()
            definition = register_tool_definition(artifact=artifact)
            return Connection.objects.get(tool_definition=definition).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(register, [1, 2]))
    assert result[0] == result[1]
    assert ToolDefinition.objects.count() == Connection.objects.count() == 1
    assert AuditEvent.objects.filter(action="connection.identity.materialized").count() == 1


@pytest.mark.django_db(transaction=True)
def test_legacy_mapping_reuses_winner_visible_during_full_clean(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL concurrent commit visibility")
    org = Organization.objects.create(slug="legacy-race", name="Legacy race")
    definition = historical_definition(artifact_for(org))
    validation_barrier, committed, mutex = Barrier(2), Event(), Lock()
    validation_count = 0
    validate = Connection.full_clean

    def interleaved_validation(self, *args, **kwargs):
        nonlocal validation_count
        with mutex:
            first = validation_count == 0
            validation_count += 1
        validation_barrier.wait(timeout=15)
        if not first:
            assert committed.wait(timeout=15)
        return validate(self, *args, **kwargs)

    monkeypatch.setattr(Connection, "full_clean", interleaved_validation)

    def resolve(_):
        close_old_connections()
        try:
            item = materialize_connection(profile=definition, actor="migration")
            committed.set()
            return item.pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(resolve, [1, 2]))
    assert result[0] == result[1]
    assert Connection.objects.count() == 1
    assert AuditEvent.objects.filter(action="connection.identity.materialized").count() == 1


@pytest.mark.django_db(transaction=True)
def test_migration_roundtrip_maps_history_and_refuses_loss():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    target = [("ingestion", "0034_typed_model_connections")]
    try:
        executor.migrate(target)
        org = Organization.objects.create(slug="history", name="History")
        definition = historical_definition(artifact_for(org))
        MigrationExecutor(connection).migrate(latest)
        item = Connection.objects.get(tool_definition=definition)
        assert item.created_by == "tool-connection-migration"
        assert verify_connection(item) == definition
        migration = import_module("apps.ingestion.migrations.0035_tenant_tool_connections")
        migration.map_existing_tools(apps, SimpleNamespace(connection=connection))
        assert Connection.objects.count() == 1
        with pytest.raises(RuntimeError, match="ROLLBACK_REQUIRES_EMPTY_HISTORY"):
            MigrationExecutor(connection).migrate(target)
        assert Connection.objects.filter(pk=item.pk).exists()
    finally:
        MigrationExecutor(connection).migrate(latest)


def test_empty_reverse_requires_revoking_new_insert_privilege():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL rollback grants")
    role = f"tool_rollback_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT INSERT ON ingestion_connection TO "{role}"')
    migration = import_module("apps.ingestion.migrations.0035_tenant_tool_connections")
    with connection.schema_editor() as editor:
        with pytest.raises(RuntimeError, match="ROLLBACK_REQUIRES_INSERT_REVOCATION"):
            migration.reverse(apps, editor)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = 'ingestion_connection'"
        )
        assert cursor.fetchone() == (True, True)


def test_deployment_gate_rejects_missing_or_permissive_connection_policy():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL provisioning and policy inspection")
    role = f"tool_deployment_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT ON ingestion_connection TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
    tables = tuple(t for t in protected_tenant_tables() if t.model_label == "ingestion.connection")
    assert len(tables) == 1 and tables[0].nullable
    sql = (settings.BASE_DIR / "deploy/postgres/provision-app-role.sql").read_text(encoding="utf-8")
    guard = (
        "DO $connection_scope$"
        + sql.split("DO $connection_scope$", 1)[1].split("$connection_scope$;", 1)[0]
        + "$connection_scope$;"
    )
    with connection.cursor() as cursor:
        cursor.execute(guard)
    assert inspect_rls_readiness(app_role=role, tables=tables).ready
    for mutation in (
        "DROP POLICY connection_tool_insert_scope ON ingestion_connection",
        "ALTER POLICY connection_tool_insert_scope ON ingestion_connection WITH CHECK (true)",
        "CREATE POLICY extra_read ON ingestion_connection FOR SELECT USING (true)",
        "ALTER TABLE ingestion_connection NO FORCE ROW LEVEL SECURITY",
    ):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(mutation)
            assert not inspect_rls_readiness(app_role=role, tables=tables).ready
            with pytest.raises(DatabaseError, match="CONNECTION_TENANT_SCHEMA_REQUIRED"):
                with connection.cursor() as cursor:
                    cursor.execute(guard)
            transaction.set_rollback(True)
