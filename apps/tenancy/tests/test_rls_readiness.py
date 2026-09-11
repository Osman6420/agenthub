from __future__ import annotations

import uuid
from io import StringIO
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.tenancy.rls import (
    ApplicationRoleState,
    RlsReadinessReport,
    TenantTable,
    TenantTableClass,
    inspect_rls_readiness,
    protected_tenant_tables,
    tenant_table_inventory,
)


def test_inventory_classifies_direct_tenant_tables() -> None:
    inventory = {table.model_label: table for table in tenant_table_inventory()}

    assert inventory["documents.document"].classification == TenantTableClass.PROTECTED
    assert inventory["documents.document"].tenant_column == "organization_id"
    assert inventory["tenancy.organizationmembership"].classification == TenantTableClass.BOOTSTRAP
    assert inventory["audit.auditevent"].classification == TenantTableClass.TELEMETRY
    assert inventory["catalog.scenario"].classification == TenantTableClass.PROTECTED
    assert inventory["catalog.scenario"].tenant_column == "organization_id"
    assert inventory["workflows.run"].tenant_column == "organization_id"
    assert inventory["workflows.runevent"].tenant_column == "organization_id"
    assert inventory["workflows.runwait"].tenant_column == "organization_id"
    assert inventory["identity.consumertoken"].classification == TenantTableClass.BOOTSTRAP
    assert inventory["workflows.runbranch"].classification == TenantTableClass.PROTECTED
    assert inventory["workflows.runjoin"].classification == TenantTableClass.PROTECTED
    assert inventory["workflows.runchildlink"].classification == TenantTableClass.PROTECTED
    assert inventory["workflows.runcompensationentry"].classification == TenantTableClass.PROTECTED
    assert "tenancy.organization" not in inventory


def test_protected_inventory_is_sorted_and_excludes_special_access_tables() -> None:
    protected = protected_tenant_tables()

    assert protected == tuple(sorted(protected))
    assert protected
    assert all(table.classification == TenantTableClass.PROTECTED for table in protected)
    labels = {table.model_label for table in protected}
    assert not any(
        table.classification == TenantTableClass.INDIRECT for table in tenant_table_inventory()
    )
    assert "identity.consumer" not in labels
    assert "identity.consumertoken" not in labels
    assert "tenancy.organizationmembership" not in labels
    assert "observability.usageevent" not in labels


def test_provisioning_sql_names_every_protected_table() -> None:
    sql = (settings.BASE_DIR / "deploy" / "postgres" / "provision-app-role.sql").read_text(
        encoding="utf-8"
    )
    missing = [
        table.table_name for table in protected_tenant_tables() if table.table_name not in sql
    ]
    assert missing == []
    assert "UPDATE(last_login) ON auth_user" in sql
    assert "UPDATE ON auth_user" not in sql


# The owner-approved inventory for the authorization-bearing access/assignment tables. Revocation
# is a status change, never a row delete, so who held which authority stays reconstructable
# from the table itself and the role never needs DELETE.
ACCESS_AUTHORITY_GRANTS = {
    "documents_scenariodocumentsetaccessrequest": ("SELECT", "INSERT", "UPDATE"),
    "documents_scenariodocumentsetgrant": ("SELECT", "INSERT", "UPDATE"),
    "identity_organizationresponsibilityassignment": ("SELECT", "INSERT", "UPDATE"),
    "identity_projectresponsibilityassignment": ("SELECT", "INSERT", "UPDATE"),
    "identity_scenarioresponsibilityassignment": ("SELECT", "INSERT", "UPDATE"),
    "identity_documentsetresponsibilityassignment": ("SELECT", "INSERT", "UPDATE"),
}


def test_access_authority_tables_are_provisioned_without_delete() -> None:
    inventory = {table.table_name: table for table in protected_tenant_tables()}
    sql = (settings.BASE_DIR / "deploy" / "postgres" / "provision-app-role.sql").read_text(
        encoding="utf-8"
    )
    # Comments are stripped first: a rationale mentioning DELETE must not read as a grant of it.
    statements = [
        "\n".join(line for line in statement.splitlines() if not line.lstrip().startswith("--"))
        for statement in sql.split(";")
    ]
    delete_grants = [
        statement for statement in statements if "GRANT" in statement and "DELETE" in statement
    ]

    for table_name in ACCESS_AUTHORITY_GRANTS:
        assert inventory[table_name].tenant_column == "organization_id"
        assert table_name in sql
        assert not any(table_name in statement for statement in delete_grants)


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="role grants require PostgreSQL")
def test_access_authority_grants_make_a_non_owner_role_rls_ready_without_delete() -> None:
    role = f"access_grant_{uuid.uuid4().hex[:12]}"
    tables = tuple(
        table for table in protected_tenant_tables() if table.table_name in ACCESS_AUTHORITY_GRANTS
    )
    assert len(tables) == len(ACCESS_AUTHORITY_GRANTS)

    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        for table_name, privileges in ACCESS_AUTHORITY_GRANTS.items():
            cursor.execute(  # noqa: S608
                f'GRANT {", ".join(privileges)} ON "{table_name}" TO "{role}"'
            )
    try:
        report = inspect_rls_readiness(app_role=role, tables=tables)
        assert report.ready is True
        assert report.issues == ()

        with connection.cursor() as cursor:
            for table_name in ACCESS_AUTHORITY_GRANTS:
                cursor.execute("SELECT has_table_privilege(%s, %s, 'DELETE')", [role, table_name])
                assert cursor.fetchone()[0] is False
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP OWNED BY "{role}"')  # noqa: S608
            cursor.execute(f'DROP ROLE "{role}"')  # noqa: S608


def test_readiness_fails_closed_off_postgresql() -> None:
    if connection.vendor == "postgresql":
        pytest.skip("non-PostgreSQL behavior is covered by the SQLite suite")

    with pytest.raises(RuntimeError, match="RLS_READINESS_REQUIRES_POSTGRESQL"):
        inspect_rls_readiness(app_role="agenthub_app")


def test_command_fails_closed_off_postgresql() -> None:
    if connection.vendor == "postgresql":
        pytest.skip("non-PostgreSQL behavior is covered by the SQLite suite")

    with pytest.raises(CommandError, match="RLS_READINESS_REQUIRES_POSTGRESQL"):
        call_command("check_tenant_rls", app_role="agenthub_app")


def test_readiness_rejects_unbounded_or_quoted_identifiers_before_database_access() -> None:
    with pytest.raises(ValueError, match="INVALID_APP_ROLE"):
        inspect_rls_readiness(app_role='agenthub_app";DROP ROLE owner;--')
    with pytest.raises(ValueError, match="INVALID_SCHEMA"):
        inspect_rls_readiness(app_role="agenthub_app", schema="Public")


def test_command_reports_success_without_mutation() -> None:
    stdout = StringIO()
    report = RlsReadinessReport(
        role=ApplicationRoleState(name="agenthub_app", exists=True),
        tables=(),
        issues=(),
    )
    with patch(
        "apps.tenancy.management.commands.check_tenant_rls.inspect_rls_readiness",
        return_value=report,
    ):
        call_command("check_tenant_rls", app_role="agenthub_app", stdout=stdout)

    assert "RLS_READY role=agenthub_app" in stdout.getvalue()


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_readiness_accepts_non_owner_role_and_canonical_policy() -> None:
    role = f"rls_ready_{uuid.uuid4().hex[:12]}"
    table = TenantTable(
        model_label="ingestion.restsyncrun",
        table_name="ingestion_restsyncrun",
        tenant_column="organization_id",
        nullable=False,
        classification=TenantTableClass.PROTECTED,
    )
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(f'GRANT SELECT ON "{table.table_name}" TO "{role}"')  # noqa: S608
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
    try:
        report = inspect_rls_readiness(app_role=role, tables=(table,))
        assert report.ready is True
        assert report.issues == ()
    finally:
        with connection.cursor() as cursor:
            cursor.execute(  # noqa: S608 - identifiers are fixed/UUID-derived
                f'REVOKE ALL PRIVILEGES ON "{table.table_name}" FROM "{role}"'
            )
            cursor.execute(  # noqa: S608
                f'REVOKE EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) FROM "{role}"'
            )
            cursor.execute(f'DROP ROLE "{role}"')  # noqa: S608


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_readiness_rejects_missing_role() -> None:
    missing_role = f"rls_missing_{uuid.uuid4().hex[:12]}"
    table = next(
        item for item in protected_tenant_tables() if item.table_name == "documents_document"
    )

    report = inspect_rls_readiness(app_role=missing_role, tables=(table,))

    assert report.ready is False
    assert "APP_ROLE_MISSING" in report.issues
    assert "documents_document:SELECT_MISSING" in report.issues


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="Role privileges require PostgreSQL")
def test_shared_cutover_rejects_direct_and_set_role_ddl_privileges():
    role = f"shared_ready_{uuid.uuid4().hex[:12]}"
    parent = f"shared_parent_{uuid.uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN NOINHERIT')
        cursor.execute(f'CREATE ROLE "{parent}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
    try:

        def issues():
            return inspect_rls_readiness(app_role=role, tables=(), shared_vectors_only=True).issues

        assert issues() == ()
        with connection.cursor() as cursor:
            cursor.execute(
                f'GRANT EXECUTE ON FUNCTION agenthub_provision_index_store(bigint) TO "{role}"'
            )
        assert "LEGACY_VECTOR_DDL_ENABLED" in issues()
        with connection.cursor() as cursor:
            cursor.execute(
                f'REVOKE EXECUTE ON FUNCTION agenthub_provision_index_store(bigint) FROM "{role}"'
            )
            cursor.execute(f'GRANT "{parent}" TO "{role}"')
            cursor.execute(
                f'GRANT EXECUTE ON FUNCTION agenthub_drop_index_store(bigint) TO "{parent}"'
            )
        assert "LEGACY_VECTOR_DDL_ENABLED" in issues()
        with connection.cursor() as cursor:
            cursor.execute(
                f'REVOKE EXECUTE ON FUNCTION agenthub_drop_index_store(bigint) FROM "{parent}"'
            )
            cursor.execute(f'GRANT CREATE ON SCHEMA public TO "{parent}"')
        assert "SCHEMA_CREATE_ENABLED" in issues()
        with connection.cursor() as cursor:
            cursor.execute(f'REVOKE CREATE ON SCHEMA public FROM "{parent}"')
        assert issues() == ()
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP OWNED BY "{role}", "{parent}"')
            cursor.execute(f'DROP ROLE "{role}", "{parent}"')
