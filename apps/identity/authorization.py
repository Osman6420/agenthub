"""Central deny-by-default human-operator responsibility evaluation.

Membership establishes tenant affiliation only. Every object read or action is
authorized from an active, unexpired typed responsibility assignment. Callers
must pass trusted persisted targets; workspace/session values are navigation
state and never authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    PlatformResponsibility,
    PlatformResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ResponsibilityStatus,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)


class Capability(StrEnum):
    PLATFORM_MANAGE = "platform.manage"
    ORGANIZATION_VIEW = "organization.view"
    ORGANIZATION_MANAGE = "organization.manage"
    MEMBERSHIP_MANAGE = "membership.manage"
    RESPONSIBILITY_MANAGE = "responsibility.manage"
    AUDIT_VIEW = "audit.view"
    PROJECT_VIEW = "project.view"
    PROJECT_MANAGE = "project.manage"
    SCENARIO_CREATE = "scenario.create"
    SCENARIO_VIEW = "scenario.view"
    SCENARIO_EDIT = "scenario.edit"
    SCENARIO_TEST = "scenario.test"
    SCENARIO_RELEASE = "scenario.release"
    SCENARIO_APPROVAL_VIEW = "scenario.approval.view"
    SCENARIO_APPROVAL_DECIDE = "scenario.approval.decide"
    DOCUMENT_SET_METADATA_READ = "document_set.metadata.read"
    DOCUMENT_SET_RETRIEVE_GRANT = "document_set.retrieve.grant"
    DOCUMENT_SET_CONTENT_READ = "document_set.content.read"
    DOCUMENT_SET_CONTENT_MANAGE = "document_set.content.manage"
    DOCUMENT_SET_OPERATIONS_MANAGE = "document_set.operations.manage"
    RUNTIME_VIEW = "runtime.view"
    RUNTIME_CANCEL = "runtime.cancel"
    RUNTIME_PAUSE = "runtime.pause"
    RUNTIME_RESUME = "runtime.resume"


class AuthoritySource(StrEnum):
    NONE = "none"
    PLATFORM_RESPONSIBILITY = "platform_responsibility"
    ORGANIZATION_RESPONSIBILITY = "organization_responsibility"
    PROJECT_RESPONSIBILITY = "project_responsibility"
    SCENARIO_RESPONSIBILITY = "scenario_responsibility"
    DOCUMENT_SET_RESPONSIBILITY = "document_set_responsibility"
    MEMBERSHIP_SHELL = "membership_shell"
    SUPERADMIN_RECOVERY = "superadmin_recovery"


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    source: AuthoritySource
    reason: str
    assignment_id: int | None = None


_GLOBAL_ADMIN_CAPABILITIES = frozenset(
    {
        Capability.PLATFORM_MANAGE,
        Capability.ORGANIZATION_VIEW,
        Capability.ORGANIZATION_MANAGE,
        Capability.MEMBERSHIP_MANAGE,
        Capability.RESPONSIBILITY_MANAGE,
        Capability.AUDIT_VIEW,
        Capability.PROJECT_VIEW,
        Capability.PROJECT_MANAGE,
        Capability.SCENARIO_VIEW,
        Capability.DOCUMENT_SET_METADATA_READ,
        Capability.RUNTIME_VIEW,
    }
)

_ORGANIZATION_ADMIN_CAPABILITIES = _GLOBAL_ADMIN_CAPABILITIES - {
    Capability.PLATFORM_MANAGE,
}

_ORGANIZATION_AUDITOR_CAPABILITIES = frozenset(
    {
        Capability.ORGANIZATION_VIEW,
        Capability.AUDIT_VIEW,
        Capability.PROJECT_VIEW,
        Capability.SCENARIO_VIEW,
        Capability.DOCUMENT_SET_METADATA_READ,
        Capability.RUNTIME_VIEW,
    }
)

_PROJECT_RESPONSIBILITY_CAPABILITIES = {
    ProjectResponsibility.VIEWER: frozenset(
        {
            Capability.PROJECT_VIEW,
            Capability.SCENARIO_VIEW,
        }
    ),
    ProjectResponsibility.ADMINISTRATOR: frozenset(
        {
            Capability.PROJECT_VIEW,
            Capability.PROJECT_MANAGE,
            Capability.SCENARIO_CREATE,
            Capability.SCENARIO_VIEW,
            Capability.DOCUMENT_SET_METADATA_READ,
        }
    ),
}

_SCENARIO_RESPONSIBILITY_CAPABILITIES = {
    ScenarioResponsibility.VIEWER: frozenset({Capability.SCENARIO_VIEW}),
    ScenarioResponsibility.EDITOR: frozenset(
        {
            Capability.SCENARIO_VIEW,
            Capability.SCENARIO_EDIT,
            Capability.SCENARIO_TEST,
        }
    ),
    ScenarioResponsibility.RELEASE_MANAGER: frozenset(
        {
            Capability.SCENARIO_VIEW,
            Capability.SCENARIO_RELEASE,
        }
    ),
    ScenarioResponsibility.RUNTIME_OPERATOR: frozenset(
        {
            Capability.SCENARIO_VIEW,
            Capability.RUNTIME_VIEW,
            Capability.RUNTIME_CANCEL,
            Capability.RUNTIME_PAUSE,
            Capability.RUNTIME_RESUME,
        }
    ),
    ScenarioResponsibility.APPROVER: frozenset(
        {
            Capability.SCENARIO_VIEW,
            Capability.SCENARIO_APPROVAL_VIEW,
            Capability.SCENARIO_APPROVAL_DECIDE,
        }
    ),
}

_DOCUMENT_SET_RESPONSIBILITY_CAPABILITIES = {
    DocumentSetResponsibility.METADATA_VIEWER: frozenset({Capability.DOCUMENT_SET_METADATA_READ}),
    DocumentSetResponsibility.CONTENT_READER: frozenset(
        {
            Capability.DOCUMENT_SET_METADATA_READ,
            Capability.DOCUMENT_SET_CONTENT_READ,
        }
    ),
    DocumentSetResponsibility.MANAGER: frozenset(
        {
            Capability.DOCUMENT_SET_METADATA_READ,
            Capability.DOCUMENT_SET_RETRIEVE_GRANT,
            Capability.DOCUMENT_SET_CONTENT_READ,
            Capability.DOCUMENT_SET_CONTENT_MANAGE,
            Capability.DOCUMENT_SET_OPERATIONS_MANAGE,
        }
    ),
}

_INACTIVE_ORGANIZATION_READ_CAPABILITIES = frozenset(
    {
        Capability.ORGANIZATION_VIEW,
        Capability.AUDIT_VIEW,
        Capability.PROJECT_VIEW,
        Capability.SCENARIO_VIEW,
        Capability.DOCUMENT_SET_METADATA_READ,
        Capability.DOCUMENT_SET_CONTENT_READ,
        Capability.RUNTIME_VIEW,
        Capability.SCENARIO_APPROVAL_VIEW,
    }
)


def _active_assignments(queryset: QuerySet[Any]) -> QuerySet[Any]:
    now = timezone.now()
    return queryset.filter(
        status=ResponsibilityStatus.ACTIVE,
        membership__status=MembershipStatus.ACTIVE,
        membership__user__is_active=True,
        membership__user__is_superuser=False,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def _allow(source: AuthoritySource, assignment: Any, reason: str) -> AuthorizationDecision:
    return AuthorizationDecision(True, source, reason, getattr(assignment, "pk", None))


def authorize(
    *,
    user: Any,
    capability: Capability,
    organization: Organization | None = None,
    project: Any | None = None,
    scenario: Any | None = None,
    document_set: Any | None = None,
) -> AuthorizationDecision:
    """Return a stable decision for one exact trusted target scope."""

    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return AuthorizationDecision(
            False,
            AuthoritySource.NONE,
            "AUTHENTICATED_ACTIVE_USER_REQUIRED",
        )

    target_organizations = [
        target.organization for target in (project, scenario, document_set) if target is not None
    ]
    effective_organization = organization
    if effective_organization is None and target_organizations:
        effective_organization = target_organizations[0]
    if effective_organization is not None and any(
        target.organization_id != effective_organization.pk
        for target in (project, scenario, document_set)
        if target is not None
    ):
        return AuthorizationDecision(False, AuthoritySource.NONE, "TARGET_SCOPE_MISMATCH")
    if project is not None and scenario is not None and scenario.project_id != project.pk:
        return AuthorizationDecision(False, AuthoritySource.NONE, "TARGET_SCOPE_MISMATCH")

    if getattr(user, "is_superuser", False):
        return AuthorizationDecision(
            True,
            AuthoritySource.SUPERADMIN_RECOVERY,
            "SUPERADMIN_RECOVERY",
        )

    platform_assignment = PlatformResponsibilityAssignment.objects.filter(
        user_id=user.pk,
        user__is_active=True,
        user__is_superuser=False,
        responsibility=PlatformResponsibility.GLOBAL_ADMINISTRATOR,
        status=ResponsibilityStatus.ACTIVE,
    ).first()
    if platform_assignment is not None and capability in _GLOBAL_ADMIN_CAPABILITIES:
        return _allow(
            AuthoritySource.PLATFORM_RESPONSIBILITY,
            platform_assignment,
            "GLOBAL_ADMINISTRATOR",
        )

    if effective_organization is None:
        return AuthorizationDecision(False, AuthoritySource.NONE, "TRUSTED_ORGANIZATION_REQUIRED")

    membership = OrganizationMembership.objects.filter(
        organization_id=effective_organization.pk,
        user_id=user.pk,
        status=MembershipStatus.ACTIVE,
        user__is_active=True,
        user__is_superuser=False,
    ).first()
    if membership is None:
        return AuthorizationDecision(False, AuthoritySource.NONE, "ACTIVE_MEMBERSHIP_REQUIRED")

    if (
        effective_organization.status != OrganizationStatus.ACTIVE
        and capability not in _INACTIVE_ORGANIZATION_READ_CAPABILITIES
    ):
        return AuthorizationDecision(False, AuthoritySource.NONE, "ORGANIZATION_INACTIVE")

    if capability == Capability.ORGANIZATION_VIEW:
        return _allow(AuthoritySource.MEMBERSHIP_SHELL, membership, "ACTIVE_MEMBERSHIP")

    organization_assignments = _active_assignments(
        OrganizationResponsibilityAssignment.objects.filter(
            organization_id=effective_organization.pk,
            membership_id=membership.pk,
        )
    )
    for assignment in organization_assignments:
        allowed = (
            _ORGANIZATION_ADMIN_CAPABILITIES
            if assignment.responsibility == OrganizationResponsibility.ADMINISTRATOR
            else _ORGANIZATION_AUDITOR_CAPABILITIES
            if assignment.responsibility == OrganizationResponsibility.AUDITOR
            else frozenset()
        )
        if capability in allowed:
            return _allow(
                AuthoritySource.ORGANIZATION_RESPONSIBILITY,
                assignment,
                assignment.responsibility.upper(),
            )

    effective_project = project or (scenario.project if scenario is not None else None)
    if effective_project is not None:
        project_assignments = _active_assignments(
            ProjectResponsibilityAssignment.objects.filter(
                organization_id=effective_organization.pk,
                membership_id=membership.pk,
                project_id=effective_project.pk,
            )
        )
        for assignment in project_assignments:
            if capability in _PROJECT_RESPONSIBILITY_CAPABILITIES.get(
                assignment.responsibility, frozenset()
            ):
                return _allow(
                    AuthoritySource.PROJECT_RESPONSIBILITY,
                    assignment,
                    assignment.responsibility.upper(),
                )

    if scenario is not None:
        scenario_assignments = _active_assignments(
            ScenarioResponsibilityAssignment.objects.filter(
                organization_id=effective_organization.pk,
                membership_id=membership.pk,
                scenario_id=scenario.pk,
            )
        )
        for assignment in scenario_assignments:
            if capability in _SCENARIO_RESPONSIBILITY_CAPABILITIES.get(
                assignment.responsibility, frozenset()
            ):
                return _allow(
                    AuthoritySource.SCENARIO_RESPONSIBILITY,
                    assignment,
                    assignment.responsibility.upper(),
                )

    if document_set is not None:
        document_assignments = _active_assignments(
            DocumentSetResponsibilityAssignment.objects.filter(
                organization_id=effective_organization.pk,
                membership_id=membership.pk,
                document_set_id=document_set.pk,
            )
        )
        for assignment in document_assignments:
            if capability in _DOCUMENT_SET_RESPONSIBILITY_CAPABILITIES.get(
                assignment.responsibility, frozenset()
            ):
                return _allow(
                    AuthoritySource.DOCUMENT_SET_RESPONSIBILITY,
                    assignment,
                    assignment.responsibility.upper(),
                )

    return AuthorizationDecision(False, AuthoritySource.NONE, "CAPABILITY_NOT_GRANTED")
