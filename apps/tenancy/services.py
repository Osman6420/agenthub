"""Tenant authorization helpers.

These are the single source of truth for "which organizations may this user see".
Every tenant-scoped queryset in the console and (later) the gateway must derive its
scope from here so isolation cannot be bypassed by a forgotten filter in a view.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus

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


# --- Write authorization (role-gated) ---------------------------------------
# Read scope is membership-based (above); creating records additionally requires the
# right role in the target organization. A disabled organization is read-only even for a
# platform_admin; reactivation is a separate platform lifecycle operation, not an operational write.

_ADMIN_ROLES = frozenset({Role.ORGANIZATION_ADMIN})
_SCENARIO_AUTHOR_ROLES = frozenset(
    {Role.ORGANIZATION_ADMIN, Role.PROJECT_OWNER, Role.SCENARIO_EDITOR}
)
_RELEASE_MANAGER_ROLES = frozenset({Role.ORGANIZATION_ADMIN, Role.RELEASE_MANAGER})


def user_roles_in_org(user: UserLike, organization_id: int) -> set[str]:
    if not getattr(user, "is_authenticated", False):
        return set()
    concrete = cast(AbstractBaseUser, user)
    return set(
        OrganizationMembership.objects.filter(
            user_id=concrete.pk, organization_id=organization_id
        ).values_list("role", flat=True)
    )


def can_create_organization(user: UserLike) -> bool:
    """Only platform admins may create organizations."""
    return is_platform_admin(user)


def _organization_accepts_mutations(organization_id: int) -> bool:
    """Disabled tenants remain readable but reject every operational mutation."""

    return Organization.objects.filter(
        pk=organization_id, status=OrganizationStatus.ACTIVE
    ).exists()


def can_admin_org(user: UserLike, organization_id: int) -> bool:
    if not _organization_accepts_mutations(organization_id):
        return False
    return is_platform_admin(user) or bool(_ADMIN_ROLES & user_roles_in_org(user, organization_id))


def can_author_scenarios(user: UserLike, organization_id: int) -> bool:
    if not _organization_accepts_mutations(organization_id):
        return False
    return is_platform_admin(user) or bool(
        _SCENARIO_AUTHOR_ROLES & user_roles_in_org(user, organization_id)
    )


def can_manage_releases(user: UserLike, organization_id: int) -> bool:
    """Promote/canary/rollback requires ``release_manager`` (or platform admin)."""
    if not _organization_accepts_mutations(organization_id):
        return False
    return is_platform_admin(user) or bool(
        _RELEASE_MANAGER_ROLES & user_roles_in_org(user, organization_id)
    )


def admin_organization_ids(user: UserLike) -> set[int] | None:
    """Active organizations the user may administer (None = all active, platform admin)."""
    if is_platform_admin(user):
        return None
    if not getattr(user, "is_authenticated", False):
        return set()
    concrete = cast(AbstractBaseUser, user)
    return set(
        OrganizationMembership.objects.filter(
            user_id=concrete.pk,
            role__in=_ADMIN_ROLES,
            organization__status=OrganizationStatus.ACTIVE,
        ).values_list("organization_id", flat=True)
    )


def author_organization_ids(user: UserLike) -> set[int] | None:
    """Active organizations where the user may author scenarios (None = all active)."""
    if is_platform_admin(user):
        return None
    if not getattr(user, "is_authenticated", False):
        return set()
    concrete = cast(AbstractBaseUser, user)
    return set(
        OrganizationMembership.objects.filter(
            user_id=concrete.pk,
            role__in=_SCENARIO_AUTHOR_ROLES,
            organization__status=OrganizationStatus.ACTIVE,
        ).values_list("organization_id", flat=True)
    )
