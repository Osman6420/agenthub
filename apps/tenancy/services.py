"""Tenant authorization helpers.

These are the single source of truth for "which organizations may this user see".
Every tenant-scoped queryset in the console and (later) the gateway must derive its
scope from here so isolation cannot be bypassed by a forgotten filter in a view.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus


def create_console_organization(
    *, name: str, status: str, initial_admin: Any | None = None
) -> Organization:
    """Create an organization and, when supplied, its required initial admin atomically."""
    from django.db import IntegrityError, transaction

    from apps.tenancy.identifiers import (
        MAX_ALLOCATION_ATTEMPTS,
        IdentifierAllocationError,
        allocate_identifier,
    )

    for _attempt in range(MAX_ALLOCATION_ATTEMPTS):
        slug = allocate_identifier(
            name,
            fallback="organization",
            max_length=64,
            exists=lambda value: Organization.objects.filter(slug=value).exists(),
        )
        try:
            with transaction.atomic():
                organization = Organization.objects.create(slug=slug, name=name, status=status)
                if initial_admin is not None:
                    OrganizationMembership.objects.create(
                        organization=organization,
                        user=initial_admin,
                        role=Role.ORGANIZATION_ADMIN,
                    )
                return organization
        except IntegrityError:
            if Organization.objects.filter(slug=slug).exists():
                continue
            raise
    raise IdentifierAllocationError


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
_DOCUMENT_MANAGER_ROLES = frozenset(
    {
        Role.ORGANIZATION_ADMIN,
        Role.DOCUMENT_MANAGER,
        Role.PROJECT_OWNER,
        Role.SCENARIO_EDITOR,
    }
)


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


def can_manage_documents(user: UserLike, organization_id: int) -> bool:
    """Allow document-plane mutations without granting scenario or tenant administration."""
    if not _organization_accepts_mutations(organization_id):
        return False
    return is_platform_admin(user) or bool(
        _DOCUMENT_MANAGER_ROLES & user_roles_in_org(user, organization_id)
    )


class MembershipManagementError(Exception):
    """Safe membership-management failure with a stable operator-facing code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _record_membership_event(
    *,
    actor: AbstractBaseUser,
    organization_id: int,
    action: str,
    membership_id: int,
    before: dict[str, str] | None = None,
    after: dict[str, str] | None = None,
    request_id: str = "",
    trace_id: str = "",
) -> None:
    from apps.audit.services import record_event

    record_event(
        actor_type="user",
        actor_id=actor.get_username(),
        action=action,
        outcome="success",
        organization_id=organization_id,
        resource_type="organization_membership",
        resource_id=str(membership_id),
        request_id=request_id,
        trace_id=trace_id,
        before=before,
        after=after,
    )


def add_organization_membership(
    *,
    organization: Organization,
    user: Any,
    role: str,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> OrganizationMembership:
    from django.db import IntegrityError, transaction

    if role not in Role.values or role == Role.PLATFORM_ADMIN:
        raise MembershipManagementError("INVALID_ROLE")
    if not can_admin_org(actor, organization.pk):
        raise MembershipManagementError("ADMIN_REQUIRED_OR_ORGANIZATION_INACTIVE")
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization.pk)
            membership = OrganizationMembership.objects.create(
                organization=organization, user=user, role=role
            )
            _record_membership_event(
                actor=actor,
                organization_id=organization.pk,
                action="organization_membership.create",
                membership_id=membership.pk,
                after={"role": role},
                request_id=request_id,
                trace_id=trace_id,
            )
            return membership
    except IntegrityError as exc:
        if OrganizationMembership.objects.filter(
            organization=organization,
            user=user,
        ).exists():
            raise MembershipManagementError("MEMBERSHIP_ALREADY_EXISTS") from exc
        raise


def change_organization_membership(
    *,
    membership: OrganizationMembership,
    role: str,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> OrganizationMembership:
    from django.db import transaction

    if role not in Role.values or role == Role.PLATFORM_ADMIN:
        raise MembershipManagementError("INVALID_ROLE")
    if not can_admin_org(actor, membership.organization_id):
        raise MembershipManagementError("ADMIN_REQUIRED_OR_ORGANIZATION_INACTIVE")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=membership.organization_id)
        locked = OrganizationMembership.objects.select_for_update().get(pk=membership.pk)
        old_role = locked.role
        if old_role == Role.ORGANIZATION_ADMIN and role != Role.ORGANIZATION_ADMIN:
            if (
                not OrganizationMembership.objects.filter(
                    organization_id=locked.organization_id, role=Role.ORGANIZATION_ADMIN
                )
                .exclude(pk=locked.pk)
                .exists()
            ):
                raise MembershipManagementError("LAST_ORGANIZATION_ADMIN")
        locked.role = role
        locked.save(update_fields=["role", "updated_at"])
        _record_membership_event(
            actor=actor,
            organization_id=locked.organization_id,
            action="organization_membership.update",
            membership_id=locked.pk,
            before={"role": old_role},
            after={"role": role},
            request_id=request_id,
            trace_id=trace_id,
        )
        return locked


def remove_organization_membership(
    *, membership: OrganizationMembership, actor: Any, request_id: str = "", trace_id: str = ""
) -> None:
    from django.db import transaction

    if not can_admin_org(actor, membership.organization_id):
        raise MembershipManagementError("ADMIN_REQUIRED_OR_ORGANIZATION_INACTIVE")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=membership.organization_id)
        locked = OrganizationMembership.objects.select_for_update().get(pk=membership.pk)
        if (
            locked.role == Role.ORGANIZATION_ADMIN
            and not OrganizationMembership.objects.filter(
                organization_id=locked.organization_id, role=Role.ORGANIZATION_ADMIN
            )
            .exclude(pk=locked.pk)
            .exists()
        ):
            raise MembershipManagementError("LAST_ORGANIZATION_ADMIN")
        organization_id = locked.organization_id
        membership_id = locked.pk
        old_role = locked.role
        locked.delete()
        _record_membership_event(
            actor=actor,
            organization_id=organization_id,
            action="organization_membership.delete",
            membership_id=membership_id,
            before={"role": old_role},
            request_id=request_id,
            trace_id=trace_id,
        )


def can_manage_scenario_releases(user: UserLike, organization_id: int) -> bool:
    """Return whether ``user`` has central scenario-release authority."""
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None or organization.status != OrganizationStatus.ACTIVE:
        return False

    # Local import avoids making the tenant visibility module part of identity's
    # model-import cycle while this compatibility facade is migrated caller by caller.
    from apps.identity.authorization import Capability, authorize

    return authorize(
        user=user,
        capability=Capability.SCENARIO_RELEASE,
        organization=organization,
    ).allowed


def can_manage_document_set_operations(user: UserLike, document_set: Any) -> bool:
    """Return whether ``user`` may operate the exact active document set."""
    organization = document_set.organization
    if organization.status != OrganizationStatus.ACTIVE:
        return False

    from apps.identity.authorization import Capability, authorize

    return authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_OPERATIONS_MANAGE,
        organization=organization,
        document_set=document_set,
    ).allowed


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
