from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.identity.models import GlobalAdministrator
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tools.authz import resolve_actor_roles

pytestmark = pytest.mark.django_db


def _user(username: str, *, superuser: bool = False):
    return get_user_model().objects.create_user(
        username=username,
        password=None,
        is_superuser=superuser,
        is_staff=superuser,
    )


def test_resolve_actor_roles_uses_central_platform_authority() -> None:
    organization = Organization.objects.create(slug="tools", name="Tools")
    daily_admin = _user("daily-admin")
    recovery = _user("recovery", superuser=True)
    organization_admin = _user("organization-admin")
    GlobalAdministrator.objects.create(user=daily_admin)
    OrganizationMembership.objects.create(
        organization=organization,
        user=organization_admin,
        role=Role.ORGANIZATION_ADMIN,
    )

    assert resolve_actor_roles(
        username=daily_admin.get_username(),
        organization_id=organization.pk,
    ) == ["platform_admin"]
    assert resolve_actor_roles(
        username=recovery.get_username(),
        organization_id=organization.pk,
    ) == ["platform_admin"]
    assert resolve_actor_roles(
        username=organization_admin.get_username(),
        organization_id=organization.pk,
    ) == [Role.ORGANIZATION_ADMIN]


def test_resolve_actor_roles_is_non_enumerating_for_unknown_actor() -> None:
    organization = Organization.objects.create(slug="unknown", name="Unknown")

    assert resolve_actor_roles(username="missing", organization_id=organization.pk) is None
