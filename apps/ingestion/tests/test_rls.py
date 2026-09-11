"""FORCE RLS on a per-IndexVersion store is a fail-closed tenant backstop (ADR-0004, P4.3).

Superusers bypass RLS, so this proves enforcement under a NOSUPERUSER role via ``SET ROLE`` (the
production app role is likewise a non-owner, non-superuser role). It asserts that with the app
predicate **omitted**, a missing/empty or wrong ``app.tenant_scope`` returns no rows, and only the
correct tenant context reveals them. PostgreSQL-only.
"""

from __future__ import annotations

import pytest
from django.db import connection

from apps.ingestion import vector_store
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.ingestion.pipeline import embed_deterministic
from apps.ingestion.vector_store import VectorRow
from apps.tenancy.models import Organization

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL"),
]


def test_rls_is_fail_closed_under_non_superuser() -> None:
    org = Organization.objects.create(slug="a", name="A")
    other_tenant = org.id + 99_999
    index = IndexVersion.objects.create(
        organization=org,
        dimensions=64,
        index_type="vector",
        version=1,
        status=IndexStatus.BUILDING,
        store_ready=False,
    )
    vector_store.provision_store(index)
    vector_store.write_chunks(
        index, [VectorRow(org.id, 1, 0, "secret", embed_deterministic("secret"))]
    )
    name = vector_store.store_name(index)

    with connection.cursor() as cursor:
        cursor.execute("CREATE ROLE rls_probe NOSUPERUSER NOLOGIN")
        cursor.execute(f'GRANT SELECT ON "{name}" TO rls_probe')
        cursor.execute(
            "GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO rls_probe"
        )

        # No/empty tenant context: RLS returns no rows even with the app predicate omitted.
        cursor.execute("SELECT set_config('app.tenant_scope', '', true)")
        cursor.execute("SET ROLE rls_probe")
        cursor.execute(f'SELECT count(*) FROM "{name}"')  # noqa: S608 - int-derived name
        assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")

        # Correct tenant context: rows are visible.
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(org.id)])
        cursor.execute("SET ROLE rls_probe")
        cursor.execute(f'SELECT count(*) FROM "{name}"')  # noqa: S608
        assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")

        # Wrong tenant context: cross-tenant read blocked at the RLS layer.
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(other_tenant)])
        cursor.execute("SET ROLE rls_probe")
        cursor.execute(f'SELECT count(*) FROM "{name}"')  # noqa: S608
        assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")


def test_store_has_forced_rls_policy() -> None:
    org = Organization.objects.create(slug="a", name="A")
    index = IndexVersion.objects.create(
        organization=org, dimensions=64, index_type="vector", version=1
    )
    vector_store.provision_store(index)
    name = vector_store.store_name(index)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", [name]
        )
        rowsecurity, forced = cursor.fetchone()
        assert rowsecurity is True and forced is True
        cursor.execute("SELECT count(*) FROM pg_policies WHERE tablename = %s", [name])
        assert cursor.fetchone()[0] == 1
