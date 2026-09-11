from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.contrib.auth.models import User

from apps.builder.models import WorkflowDraft
from apps.catalog.models import AIProject, Scenario
from apps.identity.models import (
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership


def simple_workflow() -> dict:
    """A minimal DSL body that compiles cleanly (mirrors the workflow suite)."""
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "simple.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "format", "type": "format_output", "config": {"template_ref": "ok"}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "format"},
                {"from": "format", "to": "done"},
            ],
        },
    }


@dataclass
class BuilderFixture:
    org: Organization
    other_org: Organization
    project: AIProject
    scenario: Scenario
    author: User  # scenario editor in ``org``
    viewer: User  # auditor in ``org`` (read scope, no author role)
    outsider: User  # scenario editor in ``other_org`` only
    draft: WorkflowDraft


@pytest.fixture
def bf(db: object) -> BuilderFixture:
    org = Organization.objects.create(slug="b-org", name="Builder Org")
    other = Organization.objects.create(slug="b-other", name="Other Org")
    project = AIProject.objects.create(organization=org, slug="ops", name="Ops")
    scenario = Scenario.objects.create(project=project, slug="flow", name="Flow")

    author = User.objects.create_user("author", password="x")  # noqa: S106
    author_membership = OrganizationMembership.objects.create(organization=org, user=author)
    viewer = User.objects.create_user("viewer", password="x")  # noqa: S106
    viewer_membership = OrganizationMembership.objects.create(organization=org, user=viewer)
    outsider = User.objects.create_user("outsider", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=other, user=outsider)
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=author_membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=author,
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=viewer_membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.VIEWER,
        assigned_by=author,
    )

    draft = WorkflowDraft.objects.create(
        organization=org,
        project=project,
        scenario=scenario,
        name="Flow draft",
        logical_id="flow_a",
        logical_description="Stable flow purpose",
        body=simple_workflow(),
        created_by="author",
        updated_by="author",
    )
    return BuilderFixture(org, other, project, scenario, author, viewer, outsider, draft)
