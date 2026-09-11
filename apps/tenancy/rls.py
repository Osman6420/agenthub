"""Read-only PostgreSQL RLS deployment-readiness inspection.

This module never changes roles, grants, policies, tables, or tenant context.  It inventories
direct tenant columns from Django's installed model metadata and verifies the invariants selected
by ADR-0004 for a separately provisioned application role.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from django.apps import apps
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper


class TenantTableClass(StrEnum):
    PROTECTED = "protected"
    INDIRECT = "indirect"
    BOOTSTRAP = "bootstrap"
    TELEMETRY = "telemetry"


_BOOTSTRAP_MODELS = frozenset(
    {
        "identity.consumer",
        "identity.consumertoken",
        "tenancy.organizationmembership",
    }
)
_TELEMETRY_MODELS = frozenset({"audit.auditevent", "observability.usageevent"})
_INDIRECT_TENANT_MODELS = frozenset(
    {
        "agents.agentrunevent",
        "catalog.scenario",
        "evaluations.evalcaseresult",
        "gateway.idempotencyrecord",
        "identity.consumerbinding",
        "identity.consumertoken",
        "releases.releasecanary",
        "releases.scenariorelease",
        "workflows.workflowrunevent",
    }
)
_POSTGRES_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


@dataclass(frozen=True, order=True)
class TenantTable:
    model_label: str
    table_name: str
    tenant_column: str
    nullable: bool
    classification: TenantTableClass


@dataclass(frozen=True)
class ApplicationRoleState:
    name: str
    exists: bool
    superuser: bool = False
    bypass_rls: bool = False


@dataclass(frozen=True)
class TableRlsState:
    table_name: str
    exists: bool
    rls_enabled: bool = False
    rls_forced: bool = False
    canonical_policy: bool = False
    owned_by_app_role: bool = False
    has_select: bool = False


@dataclass(frozen=True)
class RlsReadinessReport:
    role: ApplicationRoleState
    tables: tuple[TableRlsState, ...]
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.issues


def tenant_table_inventory() -> tuple[TenantTable, ...]:
    """Return every concrete model with a direct organization tenant column.

    Relationship-only properties are deliberately ignored: a table must carry its own tenant
    discriminator before a simple row policy can protect it.  Bootstrap and nullable telemetry
    tables stay visible in the inventory, but are classified separately because they require a
    different access design from one-tenant application transactions.
    """

    inventory: list[TenantTable] = []
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed:
            continue
        fields = {field.name: field for field in model._meta.local_fields}
        field = fields.get("organization")
        if field is None:
            field = fields.get("organization_id")
        if field is None and model._meta.label_lower in _INDIRECT_TENANT_MODELS:
            inventory.append(
                TenantTable(
                    model_label=model._meta.label_lower,
                    table_name=model._meta.db_table,
                    tenant_column="",
                    nullable=False,
                    classification=TenantTableClass.INDIRECT,
                )
            )
            continue
        if field is None:
            continue
        label = model._meta.label_lower
        if label in _BOOTSTRAP_MODELS:
            classification = TenantTableClass.BOOTSTRAP
        elif label == "ingestion.connection":
            # Six global profile kinds plus explicitly tenant-owned tool rows.
            classification = TenantTableClass.PROTECTED
        elif label in _TELEMETRY_MODELS or field.null:
            classification = TenantTableClass.TELEMETRY
        else:
            classification = TenantTableClass.PROTECTED
        if field.column is None:  # pragma: no cover - concrete local fields always have columns
            continue
        inventory.append(
            TenantTable(
                model_label=label,
                table_name=model._meta.db_table,
                tenant_column=field.column,
                nullable=field.null,
                classification=classification,
            )
        )
    return tuple(sorted(inventory))


def protected_tenant_tables() -> tuple[TenantTable, ...]:
    return tuple(
        table
        for table in tenant_table_inventory()
        if table.classification == TenantTableClass.PROTECTED
    )


def _inspect_role(connection: BaseDatabaseWrapper, app_role: str) -> ApplicationRoleState:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s",
            [app_role],
        )
        row = cursor.fetchone()
    if row is None:
        return ApplicationRoleState(name=app_role, exists=False)
    return ApplicationRoleState(
        name=str(row[0]), exists=True, superuser=bool(row[1]), bypass_rls=bool(row[2])
    )


def _inspect_table(
    connection: BaseDatabaseWrapper,
    *,
    schema: str,
    app_role: str,
    role_exists: bool,
    table: TenantTable,
) -> TableRlsState:
    canonical_expression = f"agenthub_tenant_scope_contains({table.tenant_column})"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                c.relrowsecurity,
                c.relforcerowsecurity,
                owner.rolname = %s,
                EXISTS (
                    SELECT 1
                    FROM pg_policies policy
                    WHERE policy.schemaname = namespace.nspname
                      AND policy.tablename = c.relname
                      AND policy.policyname = 'tenant_isolation'
                      AND policy.cmd = 'ALL'
                      AND policy.qual = %s
                      AND policy.with_check = %s
                )
            FROM pg_class c
            JOIN pg_namespace namespace ON namespace.oid = c.relnamespace
            JOIN pg_roles owner ON owner.oid = c.relowner
            WHERE namespace.nspname = %s AND c.relname = %s AND c.relkind = 'r'
            """,
            [
                app_role,
                canonical_expression,
                canonical_expression,
                schema,
                table.table_name,
            ],
        )
        row = cursor.fetchone()
    if row is None:
        return TableRlsState(table_name=table.table_name, exists=False)
    canonical_policy = bool(row[3])
    if table.model_label == "ingestion.connection":
        canonical_policy = _inspect_connection_policies(connection, schema=schema)
    has_select = False
    if role_exists:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT has_table_privilege(%s, c.oid, 'SELECT')
                FROM pg_class c
                JOIN pg_namespace namespace ON namespace.oid = c.relnamespace
                WHERE namespace.nspname = %s AND c.relname = %s AND c.relkind = 'r'
                """,
                [app_role, schema, table.table_name],
            )
            privilege_row = cursor.fetchone()
        if privilege_row is not None:
            has_select = bool(privilege_row[0])
    return TableRlsState(
        table_name=table.table_name,
        exists=True,
        rls_enabled=bool(row[0]),
        rls_forced=bool(row[1]),
        owned_by_app_role=bool(row[2]),
        has_select=has_select,
        canonical_policy=canonical_policy,
    )


def _inspect_connection_policies(connection: BaseDatabaseWrapper, *, schema: str) -> bool:
    """The mixed catalogue requires public reads and tenant-only tool inserts."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT policyname, cmd, qual, with_check, roles::text[], permissive "
            "FROM pg_policies WHERE schemaname = %s AND tablename = 'ingestion_connection' "
            "ORDER BY policyname",
            [schema],
        )
        policies = cursor.fetchall()
    return policies == [
        (
            "connection_read_scope",
            "SELECT",
            "((organization_id IS NULL) OR agenthub_tenant_scope_contains(organization_id))",
            None,
            ["public"],
            "PERMISSIVE",
        ),
        (
            "connection_tool_insert_scope",
            "INSERT",
            None,
            "(((kind)::text = 'tool'::text) AND (organization_id IS NOT NULL) "
            "AND agenthub_tenant_scope_contains(organization_id))",
            ["public"],
            "PERMISSIVE",
        ),
    ]


def inspect_rls_readiness(
    *,
    app_role: str,
    schema: str = "public",
    using: str = "default",
    tables: tuple[TenantTable, ...] | None = None,
    shared_vectors_only: bool = False,
) -> RlsReadinessReport:
    """Inspect ADR-0004 invariants without mutating database state."""

    if not _POSTGRES_IDENTIFIER.fullmatch(app_role):
        raise ValueError("INVALID_APP_ROLE")
    if not _POSTGRES_IDENTIFIER.fullmatch(schema):
        raise ValueError("INVALID_SCHEMA")
    connection = connections[using]
    if connection.vendor != "postgresql":
        raise RuntimeError("RLS_READINESS_REQUIRES_POSTGRESQL")
    role = _inspect_role(connection, app_role)
    selected = protected_tenant_tables() if tables is None else tables
    table_states = tuple(
        _inspect_table(
            connection,
            schema=schema,
            app_role=app_role,
            role_exists=role.exists,
            table=table,
        )
        for table in selected
    )
    issues: list[str] = []
    if tables is None:
        issues.extend(
            f"{table.model_label}:DIRECT_TENANT_COLUMN_MISSING"
            for table in tenant_table_inventory()
            if table.classification == TenantTableClass.INDIRECT
        )
    if not role.exists:
        issues.append("APP_ROLE_MISSING")
    else:
        if role.superuser:
            issues.append("APP_ROLE_SUPERUSER")
        if role.bypass_rls:
            issues.append("APP_ROLE_BYPASSES_RLS")
        if shared_vectors_only:
            # Include roles reachable via SET ROLE, even when inheritance is disabled.
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COALESCE(bool_or("
                    "has_function_privilege(r.oid, "
                    "'public.agenthub_provision_index_store(bigint)', 'EXECUTE') "
                    "OR has_function_privilege(r.oid, "
                    "'public.agenthub_drop_index_store(bigint)', 'EXECUTE')"
                    "), false), COALESCE(bool_or("
                    "has_schema_privilege(r.oid, %s, 'CREATE')), false) "
                    "FROM pg_roles r WHERE pg_has_role(%s, r.oid, 'MEMBER')",
                    [schema, app_role],
                )
                legacy_ddl, schema_create = cursor.fetchone()
            if legacy_ddl:
                issues.append("LEGACY_VECTOR_DDL_ENABLED")
            if schema_create:
                issues.append("SCHEMA_CREATE_ENABLED")
    for state in table_states:
        prefix = state.table_name
        if not state.exists:
            issues.append(f"{prefix}:TABLE_MISSING")
            continue
        if not state.rls_enabled:
            issues.append(f"{prefix}:RLS_DISABLED")
        if not state.rls_forced:
            issues.append(f"{prefix}:RLS_NOT_FORCED")
        if not state.canonical_policy:
            issues.append(f"{prefix}:POLICY_MISSING_OR_NONCANONICAL")
        if state.owned_by_app_role:
            issues.append(f"{prefix}:APP_ROLE_IS_OWNER")
        if not state.has_select:
            issues.append(f"{prefix}:SELECT_MISSING")
    return RlsReadinessReport(role=role, tables=table_states, issues=tuple(issues))
