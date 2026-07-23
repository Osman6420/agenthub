"""PostgreSQL FORCE RLS coverage for delegated operator assignments."""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.catalog.models import AIProject
from apps.identity.models import ProjectAdministratorAssignment
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL"),
]

_TABLES = (
    "identity_projectadministratorassignment",
    "identity_scenarioeditorassignment",
    "identity_documentsetmanagerassignment",
)


def test_assignment_tables_have_canonical_forced_rls() -> None:
    with connection.cursor() as cursor:
        for table in _TABLES:
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                [table],
            )
            rowsecurity, forced = cursor.fetchone()
            assert rowsecurity is True and forced is True
            cursor.execute(
                "SELECT policyname FROM pg_policies WHERE tablename = %s",
                [table],
            )
            assert cursor.fetchall() == [("tenant_isolation",)]


def test_project_assignment_is_hidden_outside_tenant_scope() -> None:
    organization = Organization.objects.create(slug="assignment-rls", name="Assignment RLS")
    actor = get_user_model().objects.create_user(username="rls-actor", password=None)
    target = get_user_model().objects.create_user(username="rls-target", password=None)
    OrganizationMembership.objects.create(
        organization=organization,
        user=actor,
        role=Role.ORGANIZATION_ADMIN,
    )
    OrganizationMembership.objects.create(
        organization=organization,
        user=target,
        role=Role.AUDITOR,
    )
    project = AIProject.objects.create(
        organization=organization,
        slug="rls-project",
        name="RLS Project",
    )
    ProjectAdministratorAssignment.objects.create(
        organization=organization,
        project=project,
        user=target,
        assigned_by=actor,
    )
    role = f"assignment_rls_{uuid.uuid4().hex[:12]}"
    table = _TABLES[0]

    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(f'GRANT SELECT ON "{table}" TO "{role}"')  # noqa: S608
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'  # noqa: S608
        )
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(organization.pk)])
        cursor.execute(f'SET ROLE "{role}"')
        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
        assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")

        cursor.execute(
            "SELECT set_config('app.tenant_scope', %s, true)",
            [str(organization.pk + 99_999)],
        )
        cursor.execute(f'SET ROLE "{role}"')
        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
        assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")
