"""Tenant authorization helpers.

These are the single source of truth for "which organizations may this user see".
Every tenant-scoped queryset in the console and (later) the gateway must derive its
scope from here so isolation cannot be bypassed by a forgotten filter in a view.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from apps.tenancy.models import Organization, OrganizationMembership

UserLike = AbstractBaseUser | AnonymousUser


def is_platform_admin(user: UserLike) -> bool:
    """Platform admins (Django superusers) may cross organization boundaries."""
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))


def allowed_organization_ids(user: UserLike) -> set[int] | None:
    """IDs of organizations the user may access.

    Returns ``None`` to mean "all organizations" (platform admin). Returns an empty
    set for anonymous or membership-less users. Callers must treat ``None`` as an
    unrestricted scope and anything else as an explicit allowlist.
    """
    if not getattr(user, "is_authenticated", False):
        return set()
    if is_platform_admin(user):
        return None
    # Past the guards the user is a concrete authenticated account with a pk.
    concrete = cast(AbstractBaseUser, user)
    return set(
        OrganizationMembership.objects.filter(user_id=concrete.pk).values_list(
            "organization_id", flat=True
        )
    )


def scope_organizations(user: UserLike) -> Iterable[Organization]:
    """Organization queryset limited to the user's allowed scope."""
    allowed = allowed_organization_ids(user)
    qs = Organization.objects.all()
    if allowed is None:
        return qs
    return qs.filter(id__in=allowed)


def user_can_access_organization(user: UserLike, organization_id: int) -> bool:
    allowed = allowed_organization_ids(user)
    return allowed is None or organization_id in allowed
