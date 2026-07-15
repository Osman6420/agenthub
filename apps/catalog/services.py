"""Transactional console creation services for catalog objects."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.catalog.models import AIProject, AliasStatus, Scenario, ScenarioAlias
from apps.tenancy.identifiers import (
    MAX_ALLOCATION_ATTEMPTS,
    IdentifierAllocationError,
    allocate_identifier,
    allocate_scenario_alias,
)
from apps.tenancy.models import Organization


def create_console_project(*, organization: Organization, name: str, **fields: object) -> AIProject:
    """Create a project while keeping explicit-ID GitOps paths unchanged."""
    for _attempt in range(MAX_ALLOCATION_ATTEMPTS):
        slug = allocate_identifier(
            name,
            fallback="project",
            max_length=64,
            exists=lambda value: AIProject.objects.filter(
                organization=organization, slug=value
            ).exists(),
        )
        try:
            with transaction.atomic():
                return AIProject.objects.create(
                    organization=organization, slug=slug, name=name, **fields
                )
        except IntegrityError:
            if AIProject.objects.filter(organization=organization, slug=slug).exists():
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
