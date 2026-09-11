"""The scenario page states the order of work instead of listing eleven peer sections."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import AIProject, Scenario
from apps.catalog.services import create_console_scenario
from apps.console.tests.access_fixtures import private_access_member
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db

# Questions are authored before the single publish action prepares and evaluates its candidate.
STEP_TITLES = (
    "Temel bilgiler",
    "Bilgi kaynağı",
    "Akış",
    "Test soruları",
    "Senaryoyu yayına al",
)


def _org_admin(org: Organization, project: AIProject, username: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    OrganizationResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    ProjectResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        project=project,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    return user


def _scenario_page(client: Client, scenario: Scenario) -> str:
    response = client.get(reverse("console:scenario_detail_public", args=[scenario.public_id]))
    assert response.status_code == 200
    return response.content.decode()


def test_the_page_leads_with_ordered_steps(client: Client) -> None:
    org = Organization.objects.create(slug="steps-org", name="Steps")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    admin = _org_admin(org, project, "steps-admin")
    client.force_login(admin)
    client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {
            "access_mode": "private",
            "initial_manager": private_access_member(org),
            "name": "Steps scenario",
            "preset": "empty_workflow",
            "logical_description": "Purpose",
        },
    )
    scenario = Scenario.objects.get(project=project)

    body = _scenario_page(client, scenario)

    positions = [body.index(title) for title in STEP_TITLES]
    assert positions == sorted(positions), "steps must render in their journey order"
    # Contracts and the evaluation suite are prepared at creation, so they start satisfied.
    assert "Kimlik, API adı ve giriş/çıkış sözleşmeleri" in body
    # Nothing is published yet, so the flow and the candidate are still outstanding.
    assert "Akış henüz yayımlanmadı" in body
    assert "Henüz aday sürüm hazırlanmadı" in body
    assert "Yayında sürüm yok" in body


def test_a_scenario_editor_sees_authoring_steps_but_not_the_publish_action(client: Client) -> None:
    org = Organization.objects.create(slug="editor-org", name="Editor")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    admin = _org_admin(org, project, "editor-admin")
    scenario = create_console_scenario(project=project, name="Editor scenario")

    editor = User.objects.create_user("scenario-editor", password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=editor)
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=admin,
    )
    client.force_login(editor)

    body = _scenario_page(client, scenario)

    assert "Akışı düzenle" in body
    assert "Yayımla ve test et" in body
    # Promotion stays release-manager work: the step is present but its control is disabled.
    # Step 6 now also activates the scenario, which is why its label says so.
    assert "Yayına al ve çağrılabilir yap" in body
    disabled_index = body.index("Yayına al ve çağrılabilir yap")
    assert 'disabled aria-disabled="true"' in body[disabled_index - 400 : disabled_index]


def test_a_viewer_from_another_tenant_cannot_see_the_page(client: Client) -> None:
    org = Organization.objects.create(slug="home-org", name="Home")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    scenario = create_console_scenario(project=project, name="Home scenario")

    other = Organization.objects.create(slug="away-org", name="Away")
    away_project = AIProject.objects.create(organization=other, slug="away", name="Away")
    outsider = _org_admin(other, away_project, "outsider")
    client.force_login(outsider)

    response = client.get(reverse("console:scenario_detail_public", args=[scenario.public_id]))

    assert response.status_code == 404


def test_existing_legacy_release_precedes_next_publication_preparation(client: Client) -> None:
    org = Organization.objects.create(slug="live-org", name="Live")
    project = AIProject.objects.create(organization=org, slug="live", name="Live")
    scenario = Scenario.objects.create(project=project, slug="live", name="Live", status="active")
    release = ScenarioRelease.objects.create(
        scenario=scenario,
        status="active",
        runtime_version="v1",
        manifest={},
        artifact_manifest_sha256="a" * 64,
        created_by="seed",
    )
    client.force_login(_org_admin(org, project, "live-admin"))
    body = _scenario_page(client, scenario)
    assert body.index(f"Yayındaki sürüm #{release.pk}") < body.index(
        "Sonraki yayın için hazırlıklar"
    )
    assert '<details class="card" id="next-publication-preparation">' in body
    assert "İzinli istemciler bu sürümü kullanır." in body
    scenario.status = "disabled"
    scenario.save(update_fields=["status"])
    body = _scenario_page(client, scenario)
    assert "Yeni çağrılar kapalı. Yayındaki sürüm korunuyor." in body
    assert "İzinli istemciler bu sürümü kullanır." not in body
