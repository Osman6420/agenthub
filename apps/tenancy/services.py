"""Tenant membership lifecycle and responsibility-backed compatibility facades."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.tenancy.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)

UserLike = AbstractBaseUser | AnonymousUser


class MembershipManagementError(Exception):
    """Safe membership-management failure with a stable operator-facing code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def create_console_organization(
    *, name: str, status: str, initial_admin: Any | None = None
) -> Organization:
    """Create an organization, roleless member and non-expiring admin assignment atomically."""
    from apps.identity.models import (
        OrganizationResponsibility,
        OrganizationResponsibilityAssignment,
    )
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
                # Emergency superusers retain platform recovery authority and must
                # not become ordinary tenant principals. Responsibility models
                # deliberately reject superuser memberships.
                if initial_admin is not None and not getattr(initial_admin, "is_superuser", False):
                    membership = OrganizationMembership.objects.create(
                        organization=organization,
                        user=initial_admin,
                        created_by=initial_admin,
                    )
                    OrganizationResponsibilityAssignment.objects.create(
                        organization=organization,
                        membership=membership,
                        responsibility=OrganizationResponsibility.ADMINISTRATOR,
                        assigned_by=initial_admin,
                    )
                return organization
        except IntegrityError:
            if Organization.objects.filter(slug=slug).exists():
                continue
            raise
    raise IdentifierAllocationError


def _has_platform_responsibility(user: UserLike) -> bool:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    from apps.identity.models import (
        PlatformResponsibility,
        PlatformResponsibilityAssignment,
        ResponsibilityStatus,
    )

    return PlatformResponsibilityAssignment.objects.filter(
        user_id=cast(AbstractBaseUser, user).pk,
        responsibility=PlatformResponsibility.GLOBAL_ADMINISTRATOR,
        status=ResponsibilityStatus.ACTIVE,
    ).exists()


def is_platform_admin(user: UserLike) -> bool:
    """Return daily platform authority or exceptional superadmin recovery."""
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and (getattr(user, "is_superuser", False) or _has_platform_responsibility(user))
    )


def allowed_organization_ids(user: UserLike) -> set[int] | None:
    """Organization-shell scope; object visibility is evaluated separately."""
    if not getattr(user, "is_authenticated", False):
        return set()
    if is_platform_admin(user):
        return None
    concrete = cast(AbstractBaseUser, user)
    return set(
        OrganizationMembership.objects.filter(
            user_id=concrete.pk,
            user__is_active=True,
            status=MembershipStatus.ACTIVE,
        ).values_list("organization_id", flat=True)
    )


def scope_organizations(user: UserLike) -> Iterable[Organization]:
    allowed = allowed_organization_ids(user)
    qs = Organization.objects.all()
    return qs if allowed is None else qs.filter(id__in=allowed)


def user_can_access_organization(user: UserLike, organization_id: int) -> bool:
    allowed = allowed_organization_ids(user)
    return allowed is None or organization_id in allowed


def can_create_organization(user: UserLike) -> bool:
    return is_platform_admin(user)


def _organization(organization_id: int) -> Organization | None:
    return Organization.objects.filter(pk=organization_id).first()


def can_admin_org(user: UserLike, organization_id: int) -> bool:
    from apps.identity.authorization import Capability, authorize

    organization = _organization(organization_id)
    return bool(
        organization is not None
        and organization.status == OrganizationStatus.ACTIVE
        and authorize(
            user=user,
            capability=Capability.ORGANIZATION_MANAGE,
            organization=organization,
        ).allowed
    )


def can_author_scenarios(
    user: UserLike,
    organization_id: int,
    *,
    project: Any | None = None,
    scenario: Any | None = None,
) -> bool:
    """Compatibility facade; callers should pass the exact project/scenario target."""
    from apps.identity.authorization import Capability, authorize

    organization = _organization(organization_id)
    if organization is None:
        return False
    if project is not None or scenario is not None:
        return authorize(
            user=user,
            capability=Capability.SCENARIO_EDIT,
            organization=organization,
            project=project,
            scenario=scenario,
        ).allowed

    # Authoring is protected content access. A target-less request can never prove
    # exact scenario authority, including for organization administrators.
    return False


def can_manage_documents(
    user: UserLike,
    organization_id: int,
    *,
    document_set: Any | None = None,
) -> bool:
    """Compatibility facade; mutations must pass the exact document set."""
    from apps.identity.authorization import Capability, authorize

    organization = _organization(organization_id)
    if organization is None:
        return False
    if document_set is not None:
        return authorize(
            user=user,
            capability=Capability.DOCUMENT_SET_CONTENT_MANAGE,
            organization=organization,
            document_set=document_set,
        ).allowed
    # Content authority is never organization-wide. Set managers must pass their
    # exact set; callers creating metadata use a separate organization capability.
    return False


def can_manage_document(user: UserLike, document: Any) -> bool:
    """Authorize a manager of an exact set containing the document."""
    if not getattr(user, "is_authenticated", False):
        return False
    from django.db.models import Q

    from apps.identity.models import (
        DocumentSetResponsibility,
        DocumentSetResponsibilityAssignment,
        ResponsibilityStatus,
    )

    now = timezone.now()
    return (
        DocumentSetResponsibilityAssignment.objects.filter(
            organization_id=document.organization_id,
            membership__user_id=cast(AbstractBaseUser, user).pk,
            membership__status=MembershipStatus.ACTIVE,
            membership__user__is_active=True,
            responsibility=DocumentSetResponsibility.MANAGER,
            status=ResponsibilityStatus.ACTIVE,
            document_set__versions__memberships__document_version__document=document,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .exists()
    )


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
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> OrganizationMembership:
    if not can_admin_org(actor, organization.pk):
        raise MembershipManagementError("ADMIN_REQUIRED_OR_ORGANIZATION_INACTIVE")
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization.pk)
            existing = (
                OrganizationMembership.objects.select_for_update()
                .filter(
                    organization=organization,
                    user=user,
                )
                .first()
            )
            if existing is not None:
                if existing.status == MembershipStatus.ACTIVE:
                    raise MembershipManagementError("MEMBERSHIP_ALREADY_EXISTS")
                existing.status = MembershipStatus.ACTIVE
                existing.revoked_by = None
                existing.revoked_at = None
                existing.created_by = actor
                existing.save(
                    update_fields=[
                        "status",
                        "revoked_by",
                        "revoked_at",
                        "created_by",
                        "updated_at",
                    ]
                )
                _record_membership_event(
                    actor=actor,
                    organization_id=organization.pk,
                    action="organization_membership.reactivate",
                    membership_id=existing.pk,
                    before={"status": MembershipStatus.REVOKED},
                    after={"status": MembershipStatus.ACTIVE},
                    request_id=request_id,
                    trace_id=trace_id,
                )
                return existing
            membership = OrganizationMembership.objects.create(
                organization=organization,
                user=user,
                created_by=actor,
            )
            _record_membership_event(
                actor=actor,
                organization_id=organization.pk,
                action="organization_membership.create",
                membership_id=membership.pk,
                after={"status": MembershipStatus.ACTIVE},
                request_id=request_id,
                trace_id=trace_id,
            )
            return membership
    except IntegrityError as exc:
        raise MembershipManagementError("MEMBERSHIP_ALREADY_EXISTS") from exc


def _active_organization_admin_count(
    *, organization_id: int, excluding_membership_id: int | None = None
) -> int:
    from apps.identity.models import (
        OrganizationResponsibility,
        OrganizationResponsibilityAssignment,
        ResponsibilityStatus,
    )

    qs = OrganizationResponsibilityAssignment.objects.filter(
        organization_id=organization_id,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        status=ResponsibilityStatus.ACTIVE,
        membership__status=MembershipStatus.ACTIVE,
    )
    if excluding_membership_id is not None:
        qs = qs.exclude(membership_id=excluding_membership_id)
    return qs.count()


def remove_organization_membership(
    *, membership: OrganizationMembership, actor: Any, request_id: str = "", trace_id: str = ""
) -> None:
    """Revoke membership and every active responsibility atomically."""
    from apps.identity.models import (
        DocumentSetResponsibilityAssignment,
        OrganizationResponsibilityAssignment,
        ProjectResponsibilityAssignment,
        ResponsibilityStatus,
        ScenarioResponsibilityAssignment,
    )

    if not can_admin_org(actor, membership.organization_id):
        raise MembershipManagementError("ADMIN_REQUIRED_OR_ORGANIZATION_INACTIVE")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=membership.organization_id)
        locked = OrganizationMembership.objects.select_for_update().get(pk=membership.pk)
        if locked.status != MembershipStatus.ACTIVE:
            raise MembershipManagementError("MEMBERSHIP_NOT_ACTIVE")
        if (
            OrganizationResponsibilityAssignment.objects.filter(
                organization_id=locked.organization_id,
                membership_id=locked.pk,
                responsibility="organization_administrator",
                status=ResponsibilityStatus.ACTIVE,
            ).exists()
            and _active_organization_admin_count(
                organization_id=locked.organization_id,
                excluding_membership_id=locked.pk,
            )
            == 0
        ):
            raise MembershipManagementError("LAST_ORGANIZATION_ADMIN")

        now = timezone.now()
        for model in (
            OrganizationResponsibilityAssignment,
            ProjectResponsibilityAssignment,
            ScenarioResponsibilityAssignment,
            DocumentSetResponsibilityAssignment,
        ):
            active_assignments = list(
                model.objects.filter(
                    membership_id=locked.pk,
                    status=ResponsibilityStatus.ACTIVE,
                )
            )
            model.objects.filter(
                membership_id=locked.pk,
                status=ResponsibilityStatus.ACTIVE,
            ).update(
                status=ResponsibilityStatus.REVOKED,
                revoked_by=actor,
                revoked_at=now,
                updated_at=now,
            )
            from apps.audit.services import record_event

            for assignment in active_assignments:
                record_event(
                    actor_type="user",
                    actor_id=actor.get_username(),
                    action="responsibility.revoke_with_membership",
                    outcome="success",
                    organization_id=locked.organization_id,
                    resource_type=model._meta.model_name or model.__name__.lower(),
                    resource_id=str(assignment.pk),
                    reason="MEMBERSHIP_REVOKED",
                    request_id=request_id,
                    trace_id=trace_id,
                    before={"status": ResponsibilityStatus.ACTIVE},
                    after={"status": ResponsibilityStatus.REVOKED},
                )
        locked.status = MembershipStatus.REVOKED
        locked.revoked_by = actor
        locked.revoked_at = now
        locked.save(update_fields=["status", "revoked_by", "revoked_at", "updated_at"])
        _record_membership_event(
            actor=actor,
            organization_id=locked.organization_id,
            action="organization_membership.revoke",
            membership_id=locked.pk,
            before={"status": MembershipStatus.ACTIVE},
            after={"status": MembershipStatus.REVOKED},
            request_id=request_id,
            trace_id=trace_id,
        )


def can_manage_scenario_releases(
    user: UserLike,
    organization_id: int,
    *,
    scenario: Any | None = None,
) -> bool:
    from apps.identity.authorization import Capability, authorize

    organization = _organization(organization_id)
    return bool(
        organization is not None
        and authorize(
            user=user,
            capability=Capability.SCENARIO_RELEASE,
            organization=organization,
            scenario=scenario,
        ).allowed
    )


def can_manage_document_set_operations(user: UserLike, document_set: Any) -> bool:
    from apps.identity.authorization import Capability, authorize

    return authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_OPERATIONS_MANAGE,
        organization=document_set.organization,
        document_set=document_set,
    ).allowed


def admin_organization_ids(user: UserLike) -> set[int] | None:
    if is_platform_admin(user):
        return None
    if not getattr(user, "is_authenticated", False):
        return set()
    from apps.identity.models import (
        OrganizationResponsibility,
        OrganizationResponsibilityAssignment,
        ResponsibilityStatus,
    )

    return set(
        OrganizationResponsibilityAssignment.objects.filter(
            membership__user_id=cast(AbstractBaseUser, user).pk,
            membership__status=MembershipStatus.ACTIVE,
            responsibility=OrganizationResponsibility.ADMINISTRATOR,
            status=ResponsibilityStatus.ACTIVE,
            organization__status=OrganizationStatus.ACTIVE,
        ).values_list("organization_id", flat=True)
    )


def author_organization_ids(user: UserLike) -> set[int] | None:
    if is_platform_admin(user):
        return None
    if not getattr(user, "is_authenticated", False):
        return set()
    from apps.identity.models import (
        OrganizationResponsibility,
        OrganizationResponsibilityAssignment,
        ProjectResponsibility,
        ProjectResponsibilityAssignment,
        ResponsibilityStatus,
        ScenarioResponsibility,
        ScenarioResponsibilityAssignment,
    )

    user_id = cast(AbstractBaseUser, user).pk
    common = {
        "membership__user_id": user_id,
        "membership__status": MembershipStatus.ACTIVE,
        "status": ResponsibilityStatus.ACTIVE,
        "organization__status": OrganizationStatus.ACTIVE,
    }
    ids = set(
        OrganizationResponsibilityAssignment.objects.filter(
            **common,
            responsibility=OrganizationResponsibility.ADMINISTRATOR,
        ).values_list("organization_id", flat=True)
    )
    ids.update(
        ProjectResponsibilityAssignment.objects.filter(
            **common,
            responsibility=ProjectResponsibility.ADMINISTRATOR,
        ).values_list("organization_id", flat=True)
    )
    ids.update(
        ScenarioResponsibilityAssignment.objects.filter(
            **common,
            responsibility=ScenarioResponsibility.EDITOR,
        ).values_list("organization_id", flat=True)
    )
    return ids


def document_manager_organization_ids(user: UserLike) -> set[int] | None:
    if is_platform_admin(user):
        return None
    if not getattr(user, "is_authenticated", False):
        return set()
    from apps.identity.models import (
        DocumentSetResponsibility,
        DocumentSetResponsibilityAssignment,
        ResponsibilityStatus,
    )

    return set(
        DocumentSetResponsibilityAssignment.objects.filter(
            membership__user_id=cast(AbstractBaseUser, user).pk,
            membership__status=MembershipStatus.ACTIVE,
            responsibility=DocumentSetResponsibility.MANAGER,
            status=ResponsibilityStatus.ACTIVE,
            organization__status=OrganizationStatus.ACTIVE,
        ).values_list("organization_id", flat=True)
    )
