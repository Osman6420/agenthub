"""FORCE RLS on the MCP catalog tables is a fail-closed tenant backstop (P2.6.7).

Superusers bypass RLS, so this proves enforcement under a NOSUPERUSER role via ``SET ROLE`` (the
production app role is likewise a non-owner, non-superuser role). It asserts that with a missing,
empty or wrong ``app.tenant_scope`` the quarantined catalog rows return nothing, and only the
correct tenant context reveals them. PostgreSQL-only.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import connection

from apps.tenancy.models import Organization
from apps.tools.models import McpCatalogCandidate, McpCatalogSource

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL"),
]

CATALOG_TABLES = ("tools_mcpcatalogsource", "tools_mcpcatalogcandidate")


def _seed_catalog_rows() -> Organization:
    org = Organization.objects.create(slug="a", name="A")
    source = McpCatalogSource.objects.create(
        organization=org,
        name="approved",
        destination={"scheme": "https", "host": "mcp.example.com", "path_prefix": "/mcp"},
    )
    McpCatalogCandidate.objects.create(
        organization=org,
        source=source,
        remote_name="search",
        input_schema={"type": "object"},
        metadata_checksum="0" * 64,
        source_destination_checksum="1" * 64,
        generation=1,
    )
    return org


def test_catalog_tables_have_forced_tenant_policy() -> None:
    with connection.cursor() as cursor:
        for table in CATALOG_TABLES:
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                [table],
            )
            rowsecurity, forced = cursor.fetchone()
            assert rowsecurity is True and forced is True
            cursor.execute(
                "SELECT count(*) FROM pg_policies"
                " WHERE tablename = %s AND policyname = 'tenant_isolation'",
                [table],
            )
            assert cursor.fetchone()[0] == 1


def test_catalog_rls_is_fail_closed_under_non_owner_role() -> None:
    org = _seed_catalog_rows()
    other_tenant = org.id + 99_999
    role = f"rls_probe_{uuid.uuid4().hex[:12]}"

    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        for table in CATALOG_TABLES:
            cursor.execute(f'GRANT SELECT ON "{table}" TO "{role}"')  # noqa: S608
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )

        for table in CATALOG_TABLES:
            # No/empty tenant context: RLS returns no rows even without an app predicate.
            cursor.execute("SELECT set_config('app.tenant_scope', '', true)")
            cursor.execute(f'SET ROLE "{role}"')
            cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608 - fixed table name
            assert cursor.fetchone()[0] == 0
            cursor.execute("RESET ROLE")

            # Correct tenant context: rows are visible.
            cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(org.id)])
            cursor.execute(f'SET ROLE "{role}"')
            cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
            assert cursor.fetchone()[0] == 1
            cursor.execute("RESET ROLE")

            # Wrong tenant context: cross-tenant read blocked at the RLS layer.
            cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(other_tenant)])
            cursor.execute(f'SET ROLE "{role}"')
            cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
            assert cursor.fetchone()[0] == 0
            cursor.execute("RESET ROLE")
