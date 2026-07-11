from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.contrib.auth.models import User

from apps.builder.models import WorkflowDraft
from apps.catalog.models import AIProject
from apps.identity.roles import Role
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
    author: User  # scenario editor in ``org``
    viewer: User  # auditor in ``org`` (read scope, no author role)
    outsider: User  # scenario editor in ``other_org`` only
    draft: WorkflowDraft


@pytest.fixture
def bf(db: object) -> BuilderFixture:
    org = Organization.objects.create(slug="b-org", name="Builder Org")
    other = Organization.objects.create(slug="b-other", name="Other Org")
    project = AIProject.objects.create(organization=org, slug="ops", name="Ops")

    author = User.objects.create_user("author", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=author, role=Role.SCENARIO_EDITOR)
    viewer = User.objects.create_user("viewer", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=viewer, role=Role.AUDITOR)
    outsider = User.objects.create_user("outsider", password="x")  # noqa: S106
    OrganizationMembership.objects.create(
        organization=other, user=outsider, role=Role.SCENARIO_EDITOR
    )

    draft = WorkflowDraft.objects.create(
        organization=org,
        project=project,
        name="Flow draft",
        logical_id="flow_a",
        body=simple_workflow(),
        created_by="author",
        updated_by="author",
    )
    return BuilderFixture(org, other, project, author, viewer, outsider, draft)
