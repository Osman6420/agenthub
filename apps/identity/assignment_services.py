"""Audited mutation boundary for delegated operator assignments."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction

from apps.audit.services import record_event
from apps.identity.authorization import Capability, authorize
from apps.identity.models import (
    DocumentSetManagerAssignment,
    ProjectAdministratorAssignment,
    ScenarioEditorAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership


class AssignmentError(PermissionError):
    """Stable, content-free delegated-assignment failure."""

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
    target_user_id: int,
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
        after={"target_user_id": target_user_id} if outcome == "success" else None,
    )


def _validate_target_user(
    *,
    organization: Organization,
    target_user: Any,
) -> None:
    if (
        not getattr(target_user, "is_active", False)
        or getattr(target_user, "is_superuser", False)
        or not OrganizationMembership.objects.select_for_update()
        .filter(organization_id=organization.pk, user_id=target_user.pk)
        .exists()
    ):
        raise AssignmentError("ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED")


def assign_project_administrator(
    *,
    project: Any,
    target_user: Any,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> ProjectAdministratorAssignment:
    action = "delegated_assignment.project_administrator.create"
    resource_id = str(project.public_id)
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=project.organization_id)
            decision = authorize(
                user=actor,
                capability=Capability.ORGANIZATION_MANAGE,
                organization=organization,
                project=project,
            )
            if not decision.allowed:
                raise AssignmentError(decision.reason)
            _validate_target_user(organization=organization, target_user=target_user)
            assignment = ProjectAdministratorAssignment.objects.create(
                organization=organization,
                project=project,
                user=target_user,
                assigned_by=actor,
            )
            _audit(
                actor=actor,
                organization_id=organization.pk,
                action=action,
                outcome="success",
                resource_type="project_administrator_assignment",
                resource_id=str(assignment.pk),
                reason="ASSIGNMENT_CREATED",
                target_user_id=target_user.pk,
                request_id=request_id,
                trace_id=trace_id,
            )
            return assignment
    except (AssignmentError, ValidationError, IntegrityError) as exc:
        reason = (
            "ASSIGNMENT_ALREADY_EXISTS"
            if isinstance(exc, IntegrityError)
            else exc.code
            if isinstance(exc, AssignmentError)
            else "INVALID_ASSIGNMENT_SCOPE"
        )
        _audit(
            actor=actor,
            organization_id=project.organization_id,
            action=action,
            outcome="deny",
            resource_type="project",
            resource_id=resource_id,
            reason=reason,
            target_user_id=target_user.pk,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc


def assign_scenario_editor(
    *,
    scenario: Any,
    target_user: Any,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioEditorAssignment:
    action = "delegated_assignment.scenario_editor.create"
    resource_id = str(scenario.public_id)
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(
                pk=scenario.organization_id
            )
            organization_decision = authorize(
                user=actor,
                capability=Capability.ORGANIZATION_MANAGE,
                organization=organization,
                scenario=scenario,
            )
            project_decision = authorize(
                user=actor,
                capability=Capability.PROJECT_MANAGE,
                organization=organization,
                project=scenario.project,
                scenario=scenario,
            )
            if not organization_decision.allowed and not project_decision.allowed:
                raise AssignmentError("SCENARIO_EDITOR_DELEGATION_DENIED")
            _validate_target_user(organization=organization, target_user=target_user)
            assignment = ScenarioEditorAssignment.objects.create(
                organization=organization,
                scenario=scenario,
                user=target_user,
                assigned_by=actor,
            )
            _audit(
                actor=actor,
                organization_id=organization.pk,
                action=action,
                outcome="success",
                resource_type="scenario_editor_assignment",
                resource_id=str(assignment.pk),
                reason="ASSIGNMENT_CREATED",
                target_user_id=target_user.pk,
                request_id=request_id,
                trace_id=trace_id,
            )
            return assignment
    except (AssignmentError, ValidationError, IntegrityError) as exc:
        reason = (
            "ASSIGNMENT_ALREADY_EXISTS"
            if isinstance(exc, IntegrityError)
            else exc.code
            if isinstance(exc, AssignmentError)
            else "INVALID_ASSIGNMENT_SCOPE"
        )
        _audit(
            actor=actor,
            organization_id=scenario.organization_id,
            action=action,
            outcome="deny",
            resource_type="scenario",
            resource_id=resource_id,
            reason=reason,
            target_user_id=target_user.pk,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc


def assign_document_set_manager(
    *,
    document_set: Any,
    target_user: Any,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> DocumentSetManagerAssignment:
    action = "delegated_assignment.document_set_manager.create"
    resource_id = str(document_set.public_id)
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(
                pk=document_set.organization_id
            )
            decision = authorize(
                user=actor,
                capability=Capability.ORGANIZATION_MANAGE,
                organization=organization,
                document_set=document_set,
            )
            if not decision.allowed:
                raise AssignmentError(decision.reason)
            _validate_target_user(organization=organization, target_user=target_user)
            assignment = DocumentSetManagerAssignment.objects.create(
                organization=organization,
                document_set=document_set,
                user=target_user,
                assigned_by=actor,
            )
            _audit(
                actor=actor,
                organization_id=organization.pk,
                action=action,
                outcome="success",
                resource_type="document_set_manager_assignment",
                resource_id=str(assignment.pk),
                reason="ASSIGNMENT_CREATED",
                target_user_id=target_user.pk,
                request_id=request_id,
                trace_id=trace_id,
            )
            return assignment
    except (AssignmentError, ValidationError, IntegrityError) as exc:
        reason = (
            "ASSIGNMENT_ALREADY_EXISTS"
            if isinstance(exc, IntegrityError)
            else exc.code
            if isinstance(exc, AssignmentError)
            else "INVALID_ASSIGNMENT_SCOPE"
        )
        _audit(
            actor=actor,
            organization_id=document_set.organization_id,
            action=action,
            outcome="deny",
            resource_type="document_set",
            resource_id=resource_id,
            reason=reason,
            target_user_id=target_user.pk,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc


def remove_delegated_assignment(
    *,
    assignment: Any,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> None:
    """Remove one exact assignment; required audit failure restores the row."""

    model = type(assignment)
    if model is ProjectAdministratorAssignment:
        assignment_type = "project_administrator"
        target = assignment.project
        authorization_kwargs = {"project": target}
    elif model is ScenarioEditorAssignment:
        assignment_type = "scenario_editor"
        target = assignment.scenario
        authorization_kwargs = {"project": target.project, "scenario": target}
    elif model is DocumentSetManagerAssignment:
        assignment_type = "document_set_manager"
        target = assignment.document_set
        authorization_kwargs = {"document_set": target}
    else:
        raise AssignmentError("UNKNOWN_ASSIGNMENT_TYPE")

    action = f"delegated_assignment.{assignment_type}.delete"
    organization_id = assignment.organization_id
    assignment_id = assignment.pk
    target_user_id = assignment.user_id
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            locked = model.objects.select_for_update().get(
                pk=assignment_id,
                organization_id=organization.pk,
            )
            organization_decision = authorize(
                user=actor,
                capability=Capability.ORGANIZATION_MANAGE,
                organization=organization,
                **authorization_kwargs,
            )
            project_decision = (
                authorize(
                    user=actor,
                    capability=Capability.PROJECT_MANAGE,
                    organization=organization,
                    **authorization_kwargs,
                )
                if model is ScenarioEditorAssignment
                else None
            )
            if not organization_decision.allowed and not (
                project_decision is not None and project_decision.allowed
            ):
                raise AssignmentError("ASSIGNMENT_REMOVAL_DENIED")
            locked.delete()
            _audit(
                actor=actor,
                organization_id=organization.pk,
                action=action,
                outcome="success",
                resource_type=f"{assignment_type}_assignment",
                resource_id=str(assignment_id),
                reason="ASSIGNMENT_REMOVED",
                target_user_id=target_user_id,
                request_id=request_id,
                trace_id=trace_id,
            )
    except (AssignmentError, ObjectDoesNotExist) as exc:
        reason = (
            exc.code if isinstance(exc, AssignmentError) else "ASSIGNMENT_NOT_FOUND"
        )
        _audit(
            actor=actor,
            organization_id=organization_id,
            action=action,
            outcome="deny",
            resource_type=f"{assignment_type}_assignment",
            resource_id=str(assignment_id),
            reason=reason,
            target_user_id=target_user_id,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise AssignmentError(reason) from exc
