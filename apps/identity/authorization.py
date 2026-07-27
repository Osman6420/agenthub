"""Central human-operator capability evaluation for Phase 2.8 Part 2.1.

Callers must pass trusted model lineage, never an organization selected by the
client. Object-scoped assignments are added to this boundary in later slices.
Until those rows exist, this module intentionally recognizes only the additive
Global Administrator, the owning Organization Administrator, and the exceptional
Django superadmin recovery identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from apps.identity.models import (
    DelegatedAssignmentStatus,
    DocumentSetManagerAssignment,
    GlobalAdministrator,
    ProjectAdministratorAssignment,
    ScenarioEditorAssignment,
)
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus


class Capability(StrEnum):
    PLATFORM_MANAGE = "platform.manage"
    ORGANIZATION_MANAGE = "organization.manage"
    PROJECT_MANAGE = "project.manage"
    SCENARIO_EDIT = "scenario.edit"
    SCENARIO_TEST = "scenario.test"
    SCENARIO_RELEASE = "scenario.release"
    DOCUMENT_SET_METADATA_READ = "document_set.metadata.read"
    DOCUMENT_SET_RETRIEVE_GRANT = "document_set.retrieve.grant"
    DOCUMENT_SET_CONTENT_READ = "document_set.content.read"
    DOCUMENT_SET_CONTENT_MANAGE = "document_set.content.manage"
    DOCUMENT_SET_OPERATIONS_MANAGE = "document_set.operations.manage"
    RUNTIME_CANCEL = "runtime.cancel"
    RUNTIME_PAUSE = "runtime.pause"
    RUNTIME_RESUME = "runtime.resume"


class AuthoritySource(StrEnum):
    NONE = "none"
    GLOBAL_ADMINISTRATOR = "global_administrator"
    ORGANIZATION_ADMINISTRATOR = "organization_administrator"
    PROJECT_ADMINISTRATOR = "project_administrator"
    SCENARIO_EDITOR = "scenario_editor"
    DOCUMENT_SET_MANAGER = "document_set_manager"
    SUPERADMIN_RECOVERY = "superadmin_recovery"


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    source: AuthoritySource
    reason: str


_GLOBAL_ADMIN_CAPABILITIES = frozenset(
    {
        Capability.PLATFORM_MANAGE,
        Capability.ORGANIZATION_MANAGE,
        Capability.PROJECT_MANAGE,
        Capability.SCENARIO_EDIT,
        Capability.SCENARIO_TEST,
        Capability.SCENARIO_RELEASE,
        Capability.DOCUMENT_SET_METADATA_READ,
        Capability.RUNTIME_CANCEL,
        Capability.RUNTIME_PAUSE,
        Capability.RUNTIME_RESUME,
    }
)

_ORGANIZATION_ADMIN_CAPABILITIES = frozenset(
    {
        Capability.ORGANIZATION_MANAGE,
        Capability.PROJECT_MANAGE,
        Capability.SCENARIO_EDIT,
        Capability.SCENARIO_TEST,
        Capability.SCENARIO_RELEASE,
        Capability.DOCUMENT_SET_METADATA_READ,
        Capability.RUNTIME_CANCEL,
        Capability.RUNTIME_PAUSE,
        Capability.RUNTIME_RESUME,
    }
)

_READ_CAPABILITIES = frozenset(
    {
        Capability.DOCUMENT_SET_METADATA_READ,
        Capability.DOCUMENT_SET_CONTENT_READ,
    }
)


def authorize(
    *,
    user: Any,
    capability: Capability,
    organization: Organization | None = None,
    project: Any | None = None,
    scenario: Any | None = None,
    document_set: Any | None = None,
) -> AuthorizationDecision:
    """Return a stable, content-free decision for one trusted target scope."""

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

    if (
        effective_organization is not None
        and effective_organization.status != OrganizationStatus.ACTIVE
        and capability not in _READ_CAPABILITIES
    ):
        return AuthorizationDecision(False, AuthoritySource.NONE, "ORGANIZATION_INACTIVE")

    is_global_administrator = GlobalAdministrator.objects.filter(user_id=user.pk).exists()
    if is_global_administrator:
        if capability in _GLOBAL_ADMIN_CAPABILITIES:
            return AuthorizationDecision(
                True, AuthoritySource.GLOBAL_ADMINISTRATOR, "GLOBAL_ADMINISTRATOR"
            )

    if effective_organization is None:
        if is_global_administrator:
            return AuthorizationDecision(
                False,
                AuthoritySource.GLOBAL_ADMINISTRATOR,
                "GLOBAL_ADMINISTRATOR_CAPABILITY_EXCLUDED",
            )
        return AuthorizationDecision(False, AuthoritySource.NONE, "TRUSTED_ORGANIZATION_REQUIRED")

    is_organization_administrator = OrganizationMembership.objects.filter(
        organization_id=effective_organization.pk,
        user_id=user.pk,
        role=Role.ORGANIZATION_ADMIN,
    ).exists()
    if is_organization_administrator:
        if capability in _ORGANIZATION_ADMIN_CAPABILITIES:
            return AuthorizationDecision(
                True,
                AuthoritySource.ORGANIZATION_ADMINISTRATOR,
                "ORGANIZATION_ADMINISTRATOR",
            )

    effective_project = project or (scenario.project if scenario is not None else None)
    if (
        effective_project is not None
        and ProjectAdministratorAssignment.objects.filter(
            organization_id=effective_organization.pk,
            project_id=effective_project.pk,
            user_id=user.pk,
            status=DelegatedAssignmentStatus.ACTIVE,
        ).exists()
    ):
        if capability in {
            Capability.PROJECT_MANAGE,
            Capability.SCENARIO_EDIT,
            Capability.SCENARIO_TEST,
            Capability.DOCUMENT_SET_METADATA_READ,
        }:
            return AuthorizationDecision(
                True,
                AuthoritySource.PROJECT_ADMINISTRATOR,
                "PROJECT_ADMINISTRATOR",
            )

    if (
        scenario is not None
        and ScenarioEditorAssignment.objects.filter(
            organization_id=effective_organization.pk,
            scenario_id=scenario.pk,
            user_id=user.pk,
            status=DelegatedAssignmentStatus.ACTIVE,
        ).exists()
    ):
        if capability in {
            Capability.SCENARIO_EDIT,
            Capability.SCENARIO_TEST,
            Capability.DOCUMENT_SET_METADATA_READ,
        }:
            return AuthorizationDecision(True, AuthoritySource.SCENARIO_EDITOR, "SCENARIO_EDITOR")

    if (
        document_set is not None
        and DocumentSetManagerAssignment.objects.filter(
            organization_id=effective_organization.pk,
            document_set_id=document_set.pk,
            user_id=user.pk,
            status=DelegatedAssignmentStatus.ACTIVE,
        ).exists()
    ):
        if capability in {
            Capability.DOCUMENT_SET_METADATA_READ,
            Capability.DOCUMENT_SET_RETRIEVE_GRANT,
            Capability.DOCUMENT_SET_CONTENT_READ,
            Capability.DOCUMENT_SET_CONTENT_MANAGE,
            Capability.DOCUMENT_SET_OPERATIONS_MANAGE,
        }:
            return AuthorizationDecision(
                True,
                AuthoritySource.DOCUMENT_SET_MANAGER,
                "DOCUMENT_SET_MANAGER",
            )

    if is_global_administrator:
        return AuthorizationDecision(
            False,
            AuthoritySource.GLOBAL_ADMINISTRATOR,
            "GLOBAL_ADMINISTRATOR_CAPABILITY_EXCLUDED",
        )
    if is_organization_administrator:
        return AuthorizationDecision(
            False,
            AuthoritySource.ORGANIZATION_ADMINISTRATOR,
            "ORGANIZATION_ADMINISTRATOR_CAPABILITY_EXCLUDED",
        )
    return AuthorizationDecision(False, AuthoritySource.NONE, "CAPABILITY_NOT_GRANTED")
