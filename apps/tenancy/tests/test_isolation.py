"""Tenant isolation is enforced at the service/queryset layer, not just the UI."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from apps.tenancy.models import Organization, OrganizationMembership
from apps.tenancy.services import (
    allowed_organization_ids,
    scope_organizations,
    user_can_access_organization,
)

User = get_user_model()


@pytest.mark.django_db
def test_member_sees_only_their_org() -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    user = User.objects.create_user("alice", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org_a, user=user)

    assert allowed_organization_ids(user) == {org_a.id}
    assert list(scope_organizations(user)) == [org_a]
    assert user_can_access_organization(user, org_a.id) is True
    assert user_can_access_organization(user, org_b.id) is False


@pytest.mark.django_db
def test_platform_admin_sees_all_tenants() -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    root = User.objects.create_superuser("root", "root@example.com", "x")  # noqa: S106

    assert allowed_organization_ids(root) is None
    assert set(scope_organizations(root)) == {org_a, org_b}
    assert user_can_access_organization(root, org_b.id) is True


@pytest.mark.django_db
def test_anonymous_and_nonmember_see_nothing() -> None:
    Organization.objects.create(slug="org-a", name="A")
    stranger = User.objects.create_user("bob", password="x")  # noqa: S106

    assert allowed_organization_ids(AnonymousUser()) == set()
    assert allowed_organization_ids(stranger) == set()
    assert list(scope_organizations(stranger)) == []
