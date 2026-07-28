from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.builder.models import WorkflowDraft
from apps.catalog.models import AIProject, Scenario
from apps.catalog.services import create_console_scenario
from apps.identity.roles import Role
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.compiler import compile_workflow
from apps.workflows.presets import empty_workflow

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member(org: Organization, username: str, role: str = Role.ORGANIZATION_ADMIN) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


@pytest.mark.parametrize("preset", ["empty_workflow", "document_answer", "agent_loop"])
def test_contextual_preset_create_produces_valid_draft_without_release(
    client: Client, preset: str
) -> None:
    org = Organization.objects.create(slug=f"org-{preset}", name=preset)
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    user = _member(org, f"author-{preset}", Role.SCENARIO_EDITOR)
    client.force_login(user)

    response = client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {
            "name": f"{preset} scenario",
            "preset": preset,
            "logical_description": f"Stable purpose for {preset}",
            "project": "forged-parent-is-ignored",
            "status": "active",
        },
    )

    assert response.status_code == 302
    scenario = Scenario.objects.get(project=project)
    draft = WorkflowDraft.objects.get(scenario=scenario)
    assert draft.logical_description == f"Stable purpose for {preset}"
    assert compile_workflow(draft.body).checksum
    assert scenario.status == "draft"
    assert not ScenarioRelease.objects.exists()
    assert AuditEvent.objects.filter(
        organization_id=org.pk, action="console.builder.draft.create"
    ).exists()
    assert AuditEvent.objects.filter(
        organization_id=org.pk, action="console.scenario.create"
    ).exists()


def test_scenario_create_form_exposes_no_parent_or_removed_technical_fields(client: Client) -> None:
    org = Organization.objects.create(slug="form-org", name="Form")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    client.force_login(_member(org, "form-author", Role.SCENARIO_EDITOR))

    response = client.get(reverse("console:project_scenario_create", args=[project.public_id]))

    assert response.status_code == 200
    fields = response.context["form"].fields
    assert set(fields) == {"name", "preset", "logical_description"}
    body = response.content.decode()
    assert "Empty Workflow" in body
    assert "Document Answer" in body
    assert "Agent Loop" in body


def test_preset_create_rolls_back_scenario_and_draft_when_audit_fails(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = Organization.objects.create(slug="rollback-org", name="Rollback")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    client.force_login(_member(org, "rollback-author", Role.SCENARIO_EDITOR))

    def fail_audit(**_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.builder.services.record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        client.post(
            reverse("console:project_scenario_create", args=[project.public_id]),
            {
                "name": "Must rollback",
                "preset": "empty_workflow",
                "logical_description": "Rollback test",
            },
        )

    assert not Scenario.objects.filter(project=project).exists()
    assert not WorkflowDraft.objects.filter(project=project).exists()


def test_artifact_options_are_tenant_scoped_bounded_and_explain_each_level(
    client: Client,
) -> None:
    org = Organization.objects.create(slug="selector-org", name="Selector")
    foreign_org = Organization.objects.create(slug="private-org", name="Private")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    scenario = create_console_scenario(project=project, name="Scenario")
    v1 = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="answer_flow",
        logical_description="Answers governed customer questions",
        version_description="Initial reviewed workflow",
        body=empty_workflow(logical_id="answer_flow"),
        created_by="author",
    )
    v2 = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="answer_flow",
        logical_description="Answers governed customer questions",
        version_description="Adds bounded response formatting",
        body=empty_workflow(logical_id="answer_flow"),
        created_by="author",
    )
    create_artifact_version(
        organization=foreign_org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="private_flow",
        logical_description="FOREIGN_LOGICAL_SECRET",
        version_description="FOREIGN_VERSION_SECRET",
        body=empty_workflow(logical_id="private_flow"),
        created_by="foreign",
    )
    client.force_login(_member(org, "selector-admin"))
    url = reverse("console:scenario_artifact_options", args=[scenario.public_id])

    types = client.get(url).json()
    assert types["options"][0]["description"]
    logical = client.get(url, {"artifact_type": ArtifactType.WORKFLOW_DEFINITION}).json()
    assert logical["options"] == [
        {
            "value": "answer_flow",
            "label": "answer_flow",
            "description": "Answers governed customer questions",
            "latest_version": 2,
        }
    ]
    exact_response = client.get(
        url,
        {
            "artifact_type": ArtifactType.WORKFLOW_DEFINITION,
            "logical_id": "answer_flow",
        },
    )
    exact = exact_response.json()
    assert [item["id"] for item in exact["options"]] == [v2.pk, v1.pk]
    assert exact["options"][0]["description"] == "Adds bounded response formatting"
    assert exact["options"][0]["checksum"] == v2.checksum
    assert "workflow_definition" in exact["roles"]
    rendered = exact_response.content.decode()
    assert "FOREIGN_LOGICAL_SECRET" not in rendered
    assert "FOREIGN_VERSION_SECRET" not in rendered
    assert '"body"' not in rendered


def test_artifact_options_require_release_management_role(client: Client) -> None:
    org = Organization.objects.create(slug="selector-role-org", name="Selector Role")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    scenario = create_console_scenario(project=project, name="Scenario")
    client.force_login(_member(org, "selector-editor", Role.SCENARIO_EDITOR))

    response = client.get(reverse("console:scenario_artifact_options", args=[scenario.public_id]))

    assert response.status_code == 403


def test_scenario_page_uses_dependent_selector_and_compiler_mode_curl(client: Client) -> None:
    org = Organization.objects.create(slug="journey-org", name="Journey")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    scenario = create_console_scenario(project=project, name="Support Assistant")
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="support_flow",
        logical_description="Support workflow",
        version_description="Initial sync-capable release",
        body=empty_workflow(logical_id="support_flow"),
        created_by="author",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                role="workflow_definition",
                type=workflow.type,
                logical_id=workflow.logical_id,
                version=workflow.version,
            )
        ],
        runtime_version="runtime:v1",
        created_by="release-manager",
    )
    release.status = ReleaseStatus.ACTIVE
    release.save(update_fields=["status"])
    client.force_login(_member(org, "journey-admin"))

    response = client.get(reverse("console:scenario_detail_public", args=[scenario.public_id]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "1. Artifact type" in body
    assert "2. Logical artifact" in body
    assert "3. Exact version" in body
    assert 'name="role_' not in body
    assert "/v1/chat/completions" in body
    assert "/v1/responses" in body
    assert scenario.aliases.get().alias in body
    assert f'"model":"{scenario.pk}"' not in body
