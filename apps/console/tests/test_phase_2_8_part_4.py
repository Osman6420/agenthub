from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.builder.models import WorkflowDraft
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
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    if role == Role.ORGANIZATION_ADMIN:
        OrganizationResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            responsibility=OrganizationResponsibility.ADMINISTRATOR,
            assigned_by=user,
        )
        for scenario in Scenario.objects.filter(project__organization=org):
            ScenarioResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                scenario=scenario,
                responsibility=ScenarioResponsibility.RELEASE_MANAGER,
                assigned_by=user,
            )
    elif role == Role.SCENARIO_EDITOR:
        for project in org.projects.all():
            ProjectResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                project=project,
                responsibility=ProjectResponsibility.ADMINISTRATOR,
                assigned_by=user,
            )
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
            "access_mode": "private",
            "initial_manager": private_access_member(org),
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
    assert set(fields) == {
        "name",
        "preset",
        "logical_description",
        "access_mode",
        "initial_manager",
    }
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
                "access_mode": "private",
                "initial_manager": private_access_member(org),
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
        organization=org,
        artifact_type=ArtifactType.POLICY_PROFILE,
        logical_id="strict_policy",
        body={"mode": "strict"},
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
    capabilities = {item["value"]: item for item in types["options"]}
    assert capabilities[ArtifactType.WORKFLOW_DEFINITION]["authoring_capability"] == (
        "guided_elsewhere"
    )
    assert capabilities[ArtifactType.POLICY_PROFILE]["authoring_capability"] == "read_only"
    assert "salt okunur" in capabilities[ArtifactType.POLICY_PROFILE]["authoring_message"]
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


def test_artifact_options_exclude_document_set_owned_chunking_profiles(client: Client) -> None:
    """Chunking is consumed only by staged preparation; it is not a release-pinnable role."""

    org = Organization.objects.create(slug="chunking-scope-org", name="Chunking Scope")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    scenario = create_console_scenario(project=project, name="Scenario")
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.CHUNKING_PROFILE,
        logical_id="set_chunking",
        logical_description="Owned by the document set",
        version_description="Initial",
        body={
            "api_version": "agenthub/chunking/v1",
            "kind": "ChunkingProfile",
            "strategy": "tokens",
            "size": 800,
            "overlap": 80,
            "max_chunks": 500,
        },
        created_by="document-set-manager",
    )
    client.force_login(_member(org, "chunking-scope-admin"))
    url = reverse("console:scenario_artifact_options", args=[scenario.public_id])

    types = client.get(url)
    assert types.status_code == 200
    assert ArtifactType.CHUNKING_PROFILE not in {item["value"] for item in types.json()["options"]}
    # An explicit request for the retired type is a 404, not an empty list.
    assert client.get(url, {"artifact_type": ArtifactType.CHUNKING_PROFILE}).status_code == 404
    assert (
        client.get(
            url,
            {"artifact_type": ArtifactType.CHUNKING_PROFILE, "logical_id": "set_chunking"},
        ).status_code
        == 404
    )


def test_artifact_options_allow_editor_candidate_preset_and_recheck_revocation(
    client: Client,
) -> None:
    org = Organization.objects.create(slug="selector-role-org", name="Selector Role")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    scenario = create_console_scenario(project=project, name="Scenario")
    editor = _member(org, "selector-editor", Role.SCENARIO_EDITOR)
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=OrganizationMembership.objects.get(organization=org, user=editor),
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=editor,
    )
    client.force_login(editor)

    url = reverse("console:scenario_artifact_options", args=[scenario.public_id])
    response = client.get(url)

    assert response.status_code == 200
    assert client.get(url, {"preset": "minimum"}).status_code == 200
    ScenarioResponsibilityAssignment.objects.filter(
        scenario=scenario, membership__user=editor
    ).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.get(url, {"preset": "minimum"}).status_code in {403, 404}


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
    assert "1. Artifact type" not in body
    assert "2. Logical artifact" not in body
    assert "3. Exact version" not in body
    # Candidate preparation is reached from the ordered setup steps, not a manifest panel.
    assert "Yayımla ve test et" in body
    assert f"scenario={scenario.public_id}" in body
    assert 'name="role_' not in body
    assert "/v1/chat/completions" in body
    assert "/v1/responses" in body
    assert scenario.aliases.get().alias in body
    assert f'"model":"{scenario.pk}"' not in body
