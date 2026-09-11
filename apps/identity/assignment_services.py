"""Audited mutation boundary for typed operator responsibility assignments."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.catalog.models import AIProject, Scenario, ScenarioAccessMode
from apps.identity.authorization import Capability, authorize
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ResponsibilityStatus,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import MembershipStatus, Organization, OrganizationMembership


class AssignmentError(PermissionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _audit(
    *,
    actor: Any,
    organization_id: int,
    action: str,
    outcome: str,
    resource_type: str,
    resource_id: str,
    reason: str,
    membership_id: int | None,
    request_id: str,
    trace_id: str,
) -> None:
    record_event(
        actor_type="user",
        actor_id=actor.get_username(),
        action=action,
        outcome=outcome,
        organization_id=organization_id,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        request_id=request_id,
        trace_id=trace_id,
        after={"membership_id": membership_id} if outcome == "success" else None,
    )


def _locked_membership(
    *, organization: Organization, membership: OrganizationMembership
) -> OrganizationMembership:
    locked = (
        OrganizationMembership.objects.select_for_update()
        .select_related("user")
        .filter(
            pk=membership.pk,
            organization_id=organization.pk,
            status=MembershipStatus.ACTIVE,
            user__is_active=True,
            user__is_superuser=False,
        )
        .first()
    )
    if locked is None:
        raise AssignmentError("ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED")
    return locked


def _create_or_reinstate(
    model: Any,
    *,
    organization: Organization,
    membership: OrganizationMembership,
    responsibility: str,
    actor: Any,
    expires_at: Any = None,
    **scope: Any,
) -> Any:
    existing = (
        model.objects.select_for_update()
        .filter(
            organization=organization,
            membership=membership,
            responsibility=responsibility,
            **scope,
        )
        .first()
    )
    if existing is None:
        return model.objects.create(
            organization=organization,
            membership=membership,
            responsibility=responsibility,
            assigned_by=actor,
            expires_at=expires_at,
            **scope,
        )
    if existing.status == ResponsibilityStatus.ACTIVE and (
        existing.expires_at is None or existing.expires_at > timezone.now()
    ):
        raise AssignmentError("ASSIGNMENT_ALREADY_EXISTS")
    existing.status = ResponsibilityStatus.ACTIVE
    existing.revoked_by = None
    existing.revoked_at = None
    existing.assigned_by = actor
    existing.expires_at = expires_at
    existing.save()
    return existing


def _require_org_assignment_admin(*, actor: Any, organization: Organization) -> None:
    decision = authorize(
        user=actor,
        capability=Capability.RESPONSIBILITY_MANAGE,
        organization=organization,
    )
    if not decision.allowed:
        raise AssignmentError(decision.reason)


def _require_project_assignment_admin(*, actor: Any, project: AIProject, role: str) -> None:
    if authorize(
        user=actor, capability=Capability.RESPONSIBILITY_MANAGE, organization=project.organization
    ).allowed:
        return
    if (
        role
        in {
            ProjectResponsibility.VIEWER,
            ProjectResponsibility.EDITOR,
            ProjectResponsibility.MANAGER,
        }
        and authorize(
            user=actor, capability=Capability.PROJECT_ACCESS_MANAGE, project=project
        ).allowed
    ):
        return
    raise AssignmentError("PROJECT_RESPONSIBILITY_DELEGATION_DENIED")


def _require_scenario_assignment_admin(
    *, actor: Any, scenario: Scenario, role: str, granting: bool
) -> None:
    basic = role in {
        ScenarioResponsibility.VIEWER,
        ScenarioResponsibility.EDITOR,
        ScenarioResponsibility.MANAGER,
    }
    if basic and granting and scenario.access_mode == ScenarioAccessMode.INHERIT:
        raise AssignmentError("SCENARIO_INHERITS_PROJECT")
    if authorize(
        user=actor, capability=Capability.RESPONSIBILITY_MANAGE, organization=scenario.organization
    ).allowed:
        return
    if (
        basic
        and authorize(
            user=actor, capability=Capability.SCENARIO_ACCESS_MANAGE, scenario=scenario
        ).allowed
    ):
        return
    if (
        scenario.access_mode == ScenarioAccessMode.LEGACY
        and role in {ScenarioResponsibility.VIEWER, ScenarioResponsibility.EDITOR}
        and authorize(
            user=actor, capability=Capability.PROJECT_MANAGE, project=scenario.project
        ).allowed
    ):
        return
    raise AssignmentError("SCENARIO_RESPONSIBILITY_DELEGATION_DENIED")


def _require_other_permanent_manager(queryset: Any, *, code: str) -> None:
    if not queryset.filter(
        status=ResponsibilityStatus.ACTIVE,
        expires_at__isnull=True,
        membership__status=MembershipStatus.ACTIVE,
        membership__user__is_active=True,
        membership__user__is_superuser=False,
    ).exists():
        raise AssignmentError(code)


def grant_organization_responsibility(
    *,
    organization: Organization,
    membership: OrganizationMembership,
    responsibility: str,
    actor: Any,
    expires_at: Any = None,
    request_id: str = "",
    trace_id: str = "",
) -> OrganizationResponsibilityAssignment:
    action = "responsibility.organization.create"
    try:
        with transaction.atomic():
            locked_org = Organization.objects.select_for_update().get(pk=organization.pk)
            _require_org_assignment_admin(actor=actor, organization=locked_org)
            locked_member = _locked_membership(
                organization=locked_org,
                membership=membership,
            )
            if responsibility not in OrganizationResponsibility.values:
                raise AssignmentError("INVALID_RESPONSIBILITY")
            assignment = _create_or_reinstate(
                OrganizationResponsibilityAssignment,
                organization=locked_org,
                membership=locked_member,
                responsibility=responsibility,
                actor=actor,
                expires_at=expires_at,
            )
            _audit(
                actor=actor,
                organization_id=locked_org.pk,
                action=action,
                outcome="success",
                resource_type="organization_responsibility_assignment",
                resource_id=str(assignment.pk),
                reason="ASSIGNMENT_CREATED",
                membership_id=locked_member.pk,
                request_id=request_id,
                trace_id=trace_id,
            )
            return assignment
    except (AssignmentError, ValidationError, IntegrityError) as exc:
        reason = exc.code if isinstance(exc, AssignmentError) else "INVALID_ASSIGNMENT_SCOPE"
        _audit(
            actor=actor,
            organization_id=organization.pk,
            action=action,
            outcome="deny",
            resource_type="organization",
            resource_id=str(organization.pk),
            reason=reason,
            membership_id=membership.pk,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc


def grant_project_responsibility(
    *,
    project: Any,
    membership: OrganizationMembership,
    responsibility: str,
    actor: Any,
    expires_at: Any = None,
    request_id: str = "",
    trace_id: str = "",
) -> ProjectResponsibilityAssignment:
    action = "responsibility.project.create"
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=project.organization_id)
            project = AIProject.objects.select_related("organization").get(
                pk=project.pk, organization=organization
            )
            _require_project_assignment_admin(actor=actor, project=project, role=responsibility)
            locked_member = _locked_membership(
                organization=organization,
                membership=membership,
            )
            if responsibility not in ProjectResponsibility.values:
                raise AssignmentError("INVALID_RESPONSIBILITY")
            if responsibility == ProjectResponsibility.MANAGER and expires_at is not None:
                _require_other_permanent_manager(
                    ProjectResponsibilityAssignment.objects.filter(
                        project=project, responsibility=ProjectResponsibility.MANAGER
                    ).exclude(membership=locked_member),
                    code="LAST_PROJECT_MANAGER",
                )
            assignment = _create_or_reinstate(
                ProjectResponsibilityAssignment,
                organization=organization,
                membership=locked_member,
                responsibility=responsibility,
                actor=actor,
                expires_at=expires_at,
                project=project,
            )
            _audit(
                actor=actor,
                organization_id=organization.pk,
                action=action,
                outcome="success",
                resource_type="project_responsibility_assignment",
                resource_id=str(assignment.pk),
                reason="ASSIGNMENT_CREATED",
                membership_id=locked_member.pk,
                request_id=request_id,
                trace_id=trace_id,
            )
            return assignment
    except (AssignmentError, ValidationError, IntegrityError) as exc:
        reason = exc.code if isinstance(exc, AssignmentError) else "INVALID_ASSIGNMENT_SCOPE"
        _audit(
            actor=actor,
            organization_id=project.organization_id,
            action=action,
            outcome="deny",
            resource_type="project",
            resource_id=str(project.public_id),
            reason=reason,
            membership_id=membership.pk,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc


def grant_scenario_responsibility(
    *,
    scenario: Any,
    membership: OrganizationMembership,
    responsibility: str,
    actor: Any,
    expires_at: Any = None,
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioResponsibilityAssignment:
    action = "responsibility.scenario.create"
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=scenario.organization_id)
            scenario = Scenario.objects.select_related("organization", "project").get(
                pk=scenario.pk, organization=organization
            )
            _require_scenario_assignment_admin(
                actor=actor, scenario=scenario, role=responsibility, granting=True
            )
            locked_member = _locked_membership(
                organization=organization,
                membership=membership,
            )
            if responsibility not in ScenarioResponsibility.values:
                raise AssignmentError("INVALID_RESPONSIBILITY")
            if (
                responsibility == ScenarioResponsibility.MANAGER
                and scenario.access_mode == ScenarioAccessMode.PRIVATE
                and expires_at is not None
            ):
                _require_other_permanent_manager(
                    ScenarioResponsibilityAssignment.objects.filter(
                        scenario=scenario, responsibility=ScenarioResponsibility.MANAGER
                    ).exclude(membership=locked_member),
                    code="LAST_SCENARIO_MANAGER",
                )
            assignment = _create_or_reinstate(
                ScenarioResponsibilityAssignment,
                organization=organization,
                membership=locked_member,
                responsibility=responsibility,
                actor=actor,
                expires_at=expires_at,
                scenario=scenario,
            )
            _audit(
                actor=actor,
                organization_id=organization.pk,
                action=action,
                outcome="success",
                resource_type="scenario_responsibility_assignment",
                resource_id=str(assignment.pk),
                reason="ASSIGNMENT_CREATED",
                membership_id=locked_member.pk,
                request_id=request_id,
                trace_id=trace_id,
            )
            return assignment
    except (AssignmentError, ValidationError, IntegrityError) as exc:
        reason = exc.code if isinstance(exc, AssignmentError) else "INVALID_ASSIGNMENT_SCOPE"
        _audit(
            actor=actor,
            organization_id=scenario.organization_id,
            action=action,
            outcome="deny",
            resource_type="scenario",
            resource_id=str(scenario.public_id),
            reason=reason,
            membership_id=membership.pk,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc


def grant_document_set_responsibility(
    *,
    document_set: Any,
    membership: OrganizationMembership,
    responsibility: str,
    actor: Any,
    expires_at: Any = None,
    request_id: str = "",
    trace_id: str = "",
) -> DocumentSetResponsibilityAssignment:
    action = "responsibility.document_set.create"
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(
                pk=document_set.organization_id
            )
            _require_org_assignment_admin(actor=actor, organization=organization)
            locked_member = _locked_membership(
                organization=organization,
                membership=membership,
            )
            if responsibility not in DocumentSetResponsibility.values:
                raise AssignmentError("INVALID_RESPONSIBILITY")
            assignment = _create_or_reinstate(
                DocumentSetResponsibilityAssignment,
                organization=organization,
                membership=locked_member,
                responsibility=responsibility,
                actor=actor,
                expires_at=expires_at,
                document_set=document_set,
            )
            _audit(
                actor=actor,
                organization_id=organization.pk,
                action=action,
                outcome="success",
                resource_type="document_set_responsibility_assignment",
                resource_id=str(assignment.pk),
                reason="ASSIGNMENT_CREATED",
                membership_id=locked_member.pk,
                request_id=request_id,
                trace_id=trace_id,
            )
            return assignment
    except (AssignmentError, ValidationError, IntegrityError) as exc:
        reason = exc.code if isinstance(exc, AssignmentError) else "INVALID_ASSIGNMENT_SCOPE"
        _audit(
            actor=actor,
            organization_id=document_set.organization_id,
            action=action,
            outcome="deny",
            resource_type="document_set",
            resource_id=str(document_set.public_id),
            reason=reason,
            membership_id=membership.pk,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc


def remove_responsibility_assignment(
    *,
    assignment: Any,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> None:
    model = type(assignment)
    organization = assignment.organization
    responsibility = assignment.responsibility
    action = f"responsibility.{model._meta.model_name}.revoke"
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization.pk)
            locked = model.objects.select_for_update().get(
                pk=assignment.pk, organization=organization
            )
            responsibility = locked.responsibility
            if model is ProjectResponsibilityAssignment:
                _require_project_assignment_admin(
                    actor=actor, project=locked.project, role=responsibility
                )
            elif model is ScenarioResponsibilityAssignment:
                _require_scenario_assignment_admin(
                    actor=actor, scenario=locked.scenario, role=responsibility, granting=False
                )
            else:
                _require_org_assignment_admin(actor=actor, organization=organization)
            if locked.status != ResponsibilityStatus.ACTIVE:
                raise AssignmentError("ASSIGNMENT_NOT_ACTIVE")
            if (
                model is ProjectResponsibilityAssignment
                and responsibility == ProjectResponsibility.MANAGER
            ):
                _require_other_permanent_manager(
                    model.objects.filter(
                        project=locked.project, responsibility=responsibility
                    ).exclude(pk=locked.pk),
                    code="LAST_PROJECT_MANAGER",
                )
            if (
                model is ScenarioResponsibilityAssignment
                and responsibility == ScenarioResponsibility.MANAGER
                and locked.scenario.access_mode == ScenarioAccessMode.PRIVATE
            ):
                _require_other_permanent_manager(
                    model.objects.filter(
                        scenario=locked.scenario, responsibility=responsibility
                    ).exclude(pk=locked.pk),
                    code="LAST_SCENARIO_MANAGER",
                )
            if (
                model is OrganizationResponsibilityAssignment
                and responsibility == OrganizationResponsibility.ADMINISTRATOR
                and not OrganizationResponsibilityAssignment.objects.filter(
                    organization_id=organization.pk,
                    responsibility=OrganizationResponsibility.ADMINISTRATOR,
                    status=ResponsibilityStatus.ACTIVE,
                    membership__status=MembershipStatus.ACTIVE,
                )
                .exclude(pk=locked.pk)
                .exists()
            ):
                raise AssignmentError("LAST_ORGANIZATION_ADMIN")
            locked.status = ResponsibilityStatus.REVOKED
            locked.revoked_by = actor
            locked.revoked_at = timezone.now()
            locked.save(update_fields=["status", "revoked_by", "revoked_at", "updated_at"])
            _audit(
                actor=actor,
                organization_id=organization.pk,
                action=action,
                outcome="success",
                resource_type=model._meta.model_name,
                resource_id=str(locked.pk),
                reason="ASSIGNMENT_REVOKED",
                membership_id=locked.membership_id,
                request_id=request_id,
                trace_id=trace_id,
            )
    except (AssignmentError, ValidationError, model.DoesNotExist) as exc:
        reason = exc.code if isinstance(exc, AssignmentError) else "ASSIGNMENT_NOT_FOUND"
        _audit(
            actor=actor,
            organization_id=organization.pk,
            action=action,
            outcome="deny",
            resource_type=model._meta.model_name,
            resource_id=str(getattr(assignment, "pk", "")),
            reason=reason,
            membership_id=getattr(assignment, "membership_id", None),
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc
