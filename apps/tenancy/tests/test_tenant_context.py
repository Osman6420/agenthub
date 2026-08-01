from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.http import HttpResponse
from django.test import RequestFactory

from apps.catalog.models import AIProject
from apps.tenancy.context import (
    MAX_TENANT_SCOPE_IDS,
    TenantContextError,
    normalize_tenant_scope,
    set_tenant_scope,
)
from apps.tenancy.middleware import TenantContextMiddleware
from apps.tenancy.models import Organization, OrganizationMembership


def test_scope_is_sorted_unique_and_bounded() -> None:
    assert normalize_tenant_scope([3, 1, 3, 2]) == (1, 2, 3)
    with pytest.raises(TenantContextError, match="TENANT_SCOPE_INVALID"):
        normalize_tenant_scope([True])
    with pytest.raises(TenantContextError, match="TENANT_SCOPE_INVALID"):
        normalize_tenant_scope([0])
    with pytest.raises(TenantContextError, match="TENANT_SCOPE_TOO_LARGE"):
        normalize_tenant_scope(range(1, MAX_TENANT_SCOPE_IDS + 2))


def test_sqlite_scope_is_validation_only() -> None:
    if connection.vendor == "postgresql":
        pytest.skip("SQLite-only no-op behavior")
    assert set_tenant_scope([2, 1]) == (1, 2)


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_forced_rls_scope_is_cross_tenant_safe_and_transaction_local() -> None:
    organization_a = Organization.objects.create(slug="scope-a", name="A")
    organization_b = Organization.objects.create(slug="scope-b", name="B")
    AIProject.objects.create(organization=organization_a, slug="a", name="A")
    AIProject.objects.create(organization=organization_b, slug="b", name="B")
    role = f"tenant_scope_{uuid.uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(f'GRANT SELECT, UPDATE ON catalog_aiproject TO "{role}"')  # noqa: S608
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
    try:
        with transaction.atomic():
            set_tenant_scope(())
            with connection.cursor() as cursor:
                cursor.execute(f'SET LOCAL ROLE "{role}"')  # noqa: S608
                cursor.execute("SELECT count(*) FROM catalog_aiproject")
                assert cursor.fetchone()[0] == 0

        with transaction.atomic():
            set_tenant_scope((organization_a.id,))
            with connection.cursor() as cursor:
                cursor.execute(f'SET LOCAL ROLE "{role}"')  # noqa: S608
                cursor.execute("SELECT slug FROM catalog_aiproject ORDER BY slug")
                assert cursor.fetchall() == [("a",)]
                cursor.execute(
                    "UPDATE catalog_aiproject SET name = 'blocked' WHERE organization_id = %s",
                    [organization_b.id],
                )
                assert cursor.rowcount == 0

        with transaction.atomic():
            set_tenant_scope((organization_a.id, organization_b.id))
            with connection.cursor() as cursor:
                cursor.execute(f'SET LOCAL ROLE "{role}"')  # noqa: S608
                cursor.execute("SELECT slug FROM catalog_aiproject ORDER BY slug")
                assert cursor.fetchall() == [("a",), ("b",)]

        # The previous transaction-local scope cannot leak into the next checkout/transaction.
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f'SET LOCAL ROLE "{role}"')  # noqa: S608
            cursor.execute("SELECT count(*) FROM catalog_aiproject")
            assert cursor.fetchone()[0] == 0
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'REVOKE ALL PRIVILEGES ON catalog_aiproject FROM "{role}"')  # noqa: S608
            cursor.execute(  # noqa: S608
                f'REVOKE EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) FROM "{role}"'
            )
            cursor.execute(f'DROP ROLE "{role}"')  # noqa: S608


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_operator_middleware_derives_membership_scope_under_non_owner_role() -> None:
    organization_a = Organization.objects.create(slug="web-a", name="A")
    organization_b = Organization.objects.create(slug="web-b", name="B")
    AIProject.objects.create(organization=organization_a, slug="a", name="A")
    AIProject.objects.create(organization=organization_b, slug="b", name="B")
    user = get_user_model().objects.create_user("scope-user", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=organization_a, user=user)
    role = f"web_scope_{uuid.uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(  # noqa: S608
            f"GRANT SELECT ON tenancy_organizationmembership, tenancy_organization, "
            f"catalog_aiproject, identity_platformresponsibilityassignment, auth_user "
            f'TO "{role}"'
        )
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
    request = RequestFactory().get("/console/projects/")
    request.user = user

    def response_for_scope(_request):
        slugs = ",".join(AIProject.objects.order_by("slug").values_list("slug", flat=True))
        return HttpResponse(slugs)

    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SET ROLE "{role}"')  # noqa: S608
        response = TenantContextMiddleware(response_for_scope)(request)
        assert response.content == b"a"
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            cursor.execute(  # noqa: S608
                f"REVOKE ALL PRIVILEGES ON tenancy_organizationmembership, "
                f"tenancy_organization, catalog_aiproject, "
                f'identity_platformresponsibilityassignment, auth_user FROM "{role}"'
            )
            cursor.execute(  # noqa: S608
                f'REVOKE EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) FROM "{role}"'
            )
            cursor.execute(f'DROP ROLE "{role}"')  # noqa: S608


@pytest.mark.parametrize(
    "path",
    (
        "/v1/responses",
        "/v1/chat/completions",
        f"/v1/runs/{uuid.uuid4()}",
        f"/v1/runs/{uuid.uuid4()}/cancel",
    ),
)
def test_durable_api_routes_are_not_wrapped_in_request_transaction(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    request = RequestFactory().get(path)
    observed: list[bool] = []

    def response_for_scope(_request):
        observed.append(connection.in_atomic_block)
        return HttpResponse("ok")

    monkeypatch.setattr(connection, "vendor", "postgresql")
    response = TenantContextMiddleware(response_for_scope)(request)

    assert response.status_code == 200
    assert observed == [False]
