"""Transactional console creation services for catalog objects."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction

from apps.catalog.models import (
    AIProject,
    AliasStatus,
    Scenario,
    ScenarioAccessMode,
    ScenarioAlias,
    ScenarioDataSelection,
    ScenarioExecutionContract,
)
from apps.tenancy.identifiers import (
    MAX_ALLOCATION_ATTEMPTS,
    IdentifierAllocationError,
    allocate_identifier,
    allocate_scenario_alias,
)
from apps.tenancy.models import Organization, OrganizationStatus


class ProjectOwnerError(ValueError):
    code = "PROJECT_OWNER_INVALID"


def create_authorized_console_scenario(
    *,
    project: AIProject,
    name: str,
    actor: Any,
    access_mode: str,
    initial_manager: object = None,
    request_id: str = "",
    trace_id: str = "",
) -> Scenario:
    from apps.audit.services import record_event
    from apps.identity.assignment_services import AssignmentError

    try:
        return _create_authorized_console_scenario(
            project=project,
            name=name,
            actor=actor,
            access_mode=access_mode,
            initial_manager=initial_manager,
            request_id=request_id,
            trace_id=trace_id,
        )
    except AssignmentError as exc:
        record_event(
            actor_type="user",
            actor_id=actor.get_username(),
            organization_id=project.organization_id,
            action="responsibility.scenario.access_created",
            outcome="deny",
            resource_type="project",
            resource_id=str(project.public_id),
            reason=exc.code,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise


def _create_authorized_console_scenario(
    *,
    project: AIProject,
    name: str,
    actor: Any,
    access_mode: str,
    initial_manager: object = None,
    request_id: str = "",
    trace_id: str = "",
) -> Scenario:
    """New console access semantics; legacy model/GitOps creation stays unchanged."""
    from apps.audit.services import record_event
    from apps.identity.assignment_services import AssignmentError
    from apps.identity.authorization import Capability, _active_assignments, authorize
    from apps.identity.models import (
        ProjectResponsibility,
        ProjectResponsibilityAssignment,
        ScenarioResponsibility,
        ScenarioResponsibilityAssignment,
    )
    from apps.tenancy.context import set_tenant_context
    from apps.tenancy.models import OrganizationMembership

    with transaction.atomic():
        set_tenant_context(project.organization_id)
        Organization.objects.select_for_update().get(pk=project.organization_id)
        current = AIProject.objects.select_related("organization").get(
            pk=project.pk, organization_id=project.organization_id
        )
        if (
            current.organization.status != OrganizationStatus.ACTIVE
            or not authorize(
                user=actor, capability=Capability.SCENARIO_CREATE, project=current
            ).allowed
        ):
            raise AssignmentError("SCENARIO_CREATE_REQUIRED")
        if access_mode not in (ScenarioAccessMode.INHERIT, ScenarioAccessMode.PRIVATE):
            raise AssignmentError("INVALID_ACCESS_MODE")
        manager = None
        if access_mode == ScenarioAccessMode.INHERIT:
            if initial_manager is not None:
                raise AssignmentError("INVALID_ACCESS_ASSIGNMENTS")
            if not _active_assignments(
                ProjectResponsibilityAssignment.objects.filter(
                    project=current,
                    organization_id=current.organization_id,
                    responsibility=ProjectResponsibility.MANAGER,
                    expires_at__isnull=True,
                )
            ).exists():
                raise AssignmentError("LAST_PROJECT_MANAGER")
        else:
            manager = (
                OrganizationMembership.objects.select_for_update()
                .filter(
                    pk=getattr(initial_manager, "pk", 0),
                    organization_id=current.organization_id,
                    status="active",
                    user__is_active=True,
                    user__is_superuser=False,
                )
                .first()
            )
            if manager is None:
                raise AssignmentError("ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED")
        scenario = create_console_scenario(
            project=current,
            name=name,
            access_mode=access_mode,
            execution_contract=ScenarioExecutionContract.SNAPSHOT,
            data_selection=ScenarioDataSelection.ACTIVE_GENERATION,
        )
        if manager is not None:
            ScenarioResponsibilityAssignment.objects.create(
                organization_id=current.organization_id,
                scenario=scenario,
                membership=manager,
                responsibility=ScenarioResponsibility.MANAGER,
                assigned_by=actor,
            )
        record_event(
            actor_type="user",
            actor_id=actor.get_username(),
            organization_id=current.organization_id,
            action="responsibility.scenario.access_created",
            outcome="success",
            resource_type="scenario",
            resource_id=str(scenario.public_id),
            reason="EXPLICIT_INITIAL_ACCESS",
            request_id=request_id,
            trace_id=trace_id,
            after={
                "mode": access_mode,
                "manager_membership_id": manager.pk if manager else None,
                "execution_contract": scenario.execution_contract,
                "data_selection": scenario.data_selection,
            },
        )
        return scenario


def create_console_project(
    *,
    organization: Organization,
    name: str,
    **fields: object,
) -> AIProject:
    """Create a project while keeping explicit-ID GitOps paths unchanged."""
    with transaction.atomic():
        locked_organization = (
            Organization.objects.select_for_update().filter(pk=organization.pk).first()
        )
        if locked_organization is None or locked_organization.status != OrganizationStatus.ACTIVE:
            raise ProjectOwnerError
        for _attempt in range(MAX_ALLOCATION_ATTEMPTS):
            slug = allocate_identifier(
                name,
                fallback="project",
                max_length=64,
                exists=lambda value: AIProject.objects.filter(
                    organization=locked_organization, slug=value
                ).exists(),
            )
            try:
                with transaction.atomic():
                    return AIProject.objects.create(
                        organization=locked_organization,
                        slug=slug,
                        name=name,
                        **fields,
                    )
            except IntegrityError:
                if AIProject.objects.filter(organization=locked_organization, slug=slug).exists():
                    continue
                raise
    raise IdentifierAllocationError


def create_console_scenario(*, project: AIProject, name: str, **fields: object) -> Scenario:
    """Atomically create a scenario and exactly one active initial alias."""
    for _attempt in range(MAX_ALLOCATION_ATTEMPTS):
        slug = allocate_identifier(
            name,
            fallback="scenario",
            max_length=64,
            exists=lambda value: Scenario.objects.filter(project=project, slug=value).exists(),
        )
        alias = allocate_scenario_alias(
            project.name,
            name,
            exists=lambda value: ScenarioAlias.objects.filter(
                organization_id=project.organization_id, alias=value
            ).exists(),
        )
        try:
            with transaction.atomic():
                scenario = Scenario.objects.create(
                    organization_id=project.organization_id,
                    project=project,
                    slug=slug,
                    name=name,
                    **fields,
                )
                ScenarioAlias.objects.create(
                    organization_id=project.organization_id,
                    scenario=scenario,
                    alias=alias,
                    status=AliasStatus.ACTIVE,
                )
                return scenario
        except IntegrityError:
            slug_exists = Scenario.objects.filter(project=project, slug=slug).exists()
            alias_exists = ScenarioAlias.objects.filter(
                organization_id=project.organization_id, alias=alias
            ).exists()
            if slug_exists or alias_exists:
                continue
            raise
    raise IdentifierAllocationError
