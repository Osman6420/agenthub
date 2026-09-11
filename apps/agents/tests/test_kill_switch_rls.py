"""FORCE RLS on the agent runtime kill-switch control table (P2.6.6).

Superusers bypass RLS, so this proves enforcement under a NOSUPERUSER role via ``SET ROLE``
(the production app role is likewise a non-owner). A per-organization control row is visible
only in its own tenant scope, while the platform-global (``NULL``-organization) row is
deliberately visible in every scope so the runtime can enforce the global switch from a
tenant-scoped session. PostgreSQL-only.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import connection

from apps.agents.models import AgentRuntimeControl
from apps.tenancy.models import Organization

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL"),
]

_TABLE = "agents_agentruntimecontrol"


def test_control_table_has_forced_tenant_policy() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
            [_TABLE],
        )
        rowsecurity, forced = cursor.fetchone()
        assert rowsecurity is True and forced is True
        cursor.execute(
            "SELECT policyname FROM pg_policies WHERE tablename = %s ORDER BY policyname",
            [_TABLE],
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "runtime_control_insert",
            "runtime_control_select",
            "runtime_control_update",
        ]


def test_kill_switch_rls_scopes_org_rows_and_exposes_global() -> None:
    org = Organization.objects.create(slug="rls-a", name="A")
    other_tenant = org.id + 99_999
    AgentRuntimeControl.objects.create(organization=org, suspended=True, updated_by="admin")
    AgentRuntimeControl.objects.create(organization=None, suspended=True, updated_by="admin")
    role = f"rls_probe_{uuid.uuid4().hex[:12]}"

    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(f'GRANT SELECT, UPDATE ON "{_TABLE}" TO "{role}"')  # noqa: S608
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'  # noqa: S608
        )

        # Own tenant scope: sees its org row AND the global row.
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(org.id)])
        cursor.execute(f'SET ROLE "{role}"')
        cursor.execute(f'SELECT count(*) FROM "{_TABLE}"')  # noqa: S608
        assert cursor.fetchone()[0] == 2
        # Tenant-scoped writes may change their own row but never the global control row.
        cursor.execute(
            f'UPDATE "{_TABLE}" SET updated_by = %s WHERE organization_id = %s',  # noqa: S608
            ["tenant-operator", org.id],
        )
        assert cursor.rowcount == 1
        cursor.execute(
            f'UPDATE "{_TABLE}" SET updated_by = %s WHERE organization_id IS NULL',  # noqa: S608
            ["tenant-operator"],
        )
        assert cursor.rowcount == 0
        cursor.execute("RESET ROLE")
        assert AgentRuntimeControl.objects.get(organization=org).updated_by == "tenant-operator"
        assert AgentRuntimeControl.objects.get(organization__isnull=True).updated_by == "admin"

        # A foreign tenant scope: the org row is hidden, only the global row remains visible.
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(other_tenant)])
        cursor.execute(f'SET ROLE "{role}"')
        cursor.execute(f'SELECT count(*) FROM "{_TABLE}" WHERE organization_id IS NOT NULL')  # noqa: S608
        assert cursor.fetchone()[0] == 0
        cursor.execute(f'SELECT count(*) FROM "{_TABLE}" WHERE organization_id IS NULL')  # noqa: S608
        assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")
