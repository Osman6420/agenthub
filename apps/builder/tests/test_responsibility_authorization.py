import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.builder.models import WorkflowDraft
from apps.builder.tests.conftest import simple_workflow
from apps.catalog.models import AIProject, Scenario
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


def _member(organization: Organization, username: str):
    user = get_user_model().objects.create_user(username=username)
    membership = OrganizationMembership.objects.create(
        organization=organization,
        user=user,
    )
    return user, membership


def _post_draft(client: Client, organization: Organization, project: AIProject, scenario: Scenario):
    return client.post(
        reverse("builder_api:drafts"),
        data=json.dumps(
            {
                "organization": organization.slug,
                "project_id": project.pk,
                "scenario_id": scenario.pk,
                "name": f"{scenario.name} workflow",
                "logical_id": f"{scenario.slug}_workflow",
                "body": simple_workflow(),
            }
        ),
        content_type="application/json",
    )


def test_builder_authoring_requires_exact_scenario_editor_not_organization_admin() -> None:
    organization = Organization.objects.create(slug="builder-auth", name="Builder Auth")
    project = AIProject.objects.create(
        organization=organization,
        slug="project",
        name="Project",
    )
    scenario = Scenario.objects.create(project=project, slug="scenario", name="Scenario")
    sibling = Scenario.objects.create(project=project, slug="sibling", name="Sibling")
    admin, admin_membership = _member(organization, "builder-admin")
    editor, editor_membership = _member(organization, "builder-editor")
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=admin_membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=admin,
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        scenario=scenario,
        membership=editor_membership,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=admin,
    )

    client = Client()
    client.force_login(admin)
    assert _post_draft(client, organization, project, scenario).status_code == 403

    client.force_login(editor)
    response = _post_draft(client, organization, project, scenario)
    assert response.status_code == 201
    draft = WorkflowDraft.objects.get(pk=response.json()["id"])
    assert draft.scenario_id == scenario.id
    assert _post_draft(client, organization, project, sibling).status_code == 403


def test_builder_hides_protected_draft_body_without_exact_scenario_visibility() -> None:
    organization = Organization.objects.create(slug="builder-read", name="Builder Read")
    project = AIProject.objects.create(
        organization=organization,
        slug="project",
        name="Project",
    )
    visible = Scenario.objects.create(project=project, slug="visible", name="Visible")
    hidden = Scenario.objects.create(project=project, slug="hidden", name="Hidden")
    viewer, membership = _member(organization, "builder-viewer")
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        scenario=visible,
        membership=membership,
        responsibility=ScenarioResponsibility.VIEWER,
        assigned_by=viewer,
    )
    visible_draft = WorkflowDraft.objects.create(
        organization=organization,
        project=project,
        scenario=visible,
        name="Visible",
        logical_id="visible",
        body=simple_workflow(),
        created_by="seed",
        updated_by="seed",
    )
    hidden_draft = WorkflowDraft.objects.create(
        organization=organization,
        project=project,
        scenario=hidden,
        name="Hidden",
        logical_id="hidden",
        body=simple_workflow(),
        created_by="seed",
        updated_by="seed",
    )

    client = Client()
    client.force_login(viewer)
    listed_ids = {item["id"] for item in client.get(reverse("builder_api:drafts")).json()["drafts"]}
    assert listed_ids == {visible_draft.id}
    assert (
        client.get(reverse("builder_api:draft_detail", args=[hidden_draft.id])).status_code == 404
    )
