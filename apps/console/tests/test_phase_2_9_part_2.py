"""Phase 2.9 Part 2 console lifecycle authorization and affordance tests."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias
from apps.identity.models import (
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


def _scenario(org: Organization, slug: str) -> Scenario:
    project = AIProject.objects.create(organization=org, slug=f"p-{slug}", name=slug)
    scenario = Scenario.objects.create(project=project, slug=slug, name=slug)
    ScenarioAlias.objects.create(scenario=scenario, alias=f"alias-{slug}")
    ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="runtime:1",
        manifest={},
        artifact_manifest_sha256=slug[0] * 64,
        created_by="seed",
    )
    return scenario


def _assign(user, scenario: Scenario, responsibility: str) -> None:
    membership = OrganizationMembership.objects.create(
        organization=scenario.organization, user=user
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=scenario.organization,
        membership=membership,
        scenario=scenario,
        responsibility=responsibility,
        assigned_by=user,
    )


@pytest.mark.django_db
def test_exact_release_manager_can_activate_and_disable_from_scenario(client: Client) -> None:
    org = Organization.objects.create(slug="part-2", name="Part 2")
    scenario = _scenario(org, "ready")
    manager = User.objects.create_user("manager", password="unused")  # noqa: S106
    _assign(manager, scenario, ScenarioResponsibility.RELEASE_MANAGER)
    client.force_login(manager)
    url = reverse("console:scenario_lifecycle_change", args=[scenario.public_id])

    detail = client.get(reverse("console:scenario_detail_public", args=[scenario.public_id]))
    assert detail.status_code == 200
    assert url in detail.content.decode()
    assert client.get(url).status_code == 405
    assert client.post(url, {"action": "activate"}).status_code == 302
    scenario.refresh_from_db()
    assert scenario.status == LifecycleStatus.ACTIVE
    assert client.post(url, {"action": "disable"}).status_code == 302
    scenario.refresh_from_db()
    assert scenario.status == LifecycleStatus.DISABLED


@pytest.mark.django_db
def test_neighboring_role_direct_post_is_denied(client: Client) -> None:
    org = Organization.objects.create(slug="neighbor", name="Neighbor")
    scenario = _scenario(org, "ready")
    editor = User.objects.create_user("editor", password="unused")  # noqa: S106
    _assign(editor, scenario, ScenarioResponsibility.EDITOR)
    client.force_login(editor)

    response = client.post(
        reverse("console:scenario_lifecycle_change", args=[scenario.public_id]),
        {"action": "activate"},
    )

    assert response.status_code == 403
    scenario.refresh_from_db()
    assert scenario.status == LifecycleStatus.DRAFT


@pytest.mark.django_db
def test_same_tenant_cross_scenario_post_is_non_disclosing(client: Client) -> None:
    org = Organization.objects.create(slug="cross-scope", name="Cross scope")
    assigned = _scenario(org, "assigned")
    hidden = _scenario(org, "hidden")
    manager = User.objects.create_user("manager-cross", password="unused")  # noqa: S106
    _assign(manager, assigned, ScenarioResponsibility.RELEASE_MANAGER)
    client.force_login(manager)

    response = client.post(
        reverse("console:scenario_lifecycle_change", args=[hidden.public_id]),
        {"action": "activate"},
    )

    assert response.status_code == 404
    hidden.refresh_from_db()
    assert hidden.status == LifecycleStatus.DRAFT
