"""Catalog uniqueness invariants are enforced by database constraints."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import AIProject, Scenario, ScenarioAlias
from apps.tenancy.models import Organization


def _project(org: Organization, slug: str) -> AIProject:
    return AIProject.objects.create(organization=org, slug=slug, name=slug.title())


def _scenario(project: AIProject, slug: str) -> Scenario:
    return Scenario.objects.create(project=project, slug=slug, name=slug.title())


@pytest.mark.django_db
def test_alias_unique_within_organization() -> None:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = _project(org, "cx")
    s1 = _scenario(project, "s1")
    s2 = _scenario(project, "s2")
    ScenarioAlias.objects.create(scenario=s1, alias="customer-information")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ScenarioAlias.objects.create(scenario=s2, alias="customer-information")


@pytest.mark.django_db
def test_same_alias_allowed_in_different_organizations() -> None:
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    s_a = _scenario(_project(org_a, "p"), "s")
    s_b = _scenario(_project(org_b, "p"), "s")

    ScenarioAlias.objects.create(scenario=s_a, alias="shared")
    ScenarioAlias.objects.create(scenario=s_b, alias="shared")  # different org: ok

    assert ScenarioAlias.objects.filter(alias="shared").count() == 2


@pytest.mark.django_db
def test_project_slug_unique_within_org_but_free_across_orgs() -> None:
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    _project(org_a, "dup")
    _project(org_b, "dup")  # same slug, different org: ok

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _project(org_a, "dup")


@pytest.mark.django_db
def test_scenario_direct_tenant_lineage_rejects_mismatch() -> None:
    org_a = Organization.objects.create(slug="lineage-a", name="A")
    org_b = Organization.objects.create(slug="lineage-b", name="B")
    project = _project(org_a, "p")

    with pytest.raises(ValueError, match="scenario organization must match"):
        Scenario.objects.create(
            organization=org_b,
            project=project,
            slug="mismatch",
            name="Mismatch",
        )
