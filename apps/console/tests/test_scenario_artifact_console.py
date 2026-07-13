"""P9.4 scenario-centred release, artifact DSL and builder deep-link views."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.builder.models import WorkflowDraft
from apps.catalog.models import AIProject, Scenario
from apps.identity.roles import Role
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


def _member(username: str, org: Organization, role: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


def _workflow() -> dict[str, Any]:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "policy.flow"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "answer", "type": "generate"},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "answer"},
                {"from": "answer", "to": "done"},
            ],
        },
    }


def _scenario(org: Organization) -> tuple[AIProject, Scenario]:
    project = AIProject.objects.create(organization=org, slug="assistant", name="Assistant")
    scenario = Scenario.objects.create(project=project, slug="policy", name="Policy Assistant")
    return project, scenario


@pytest.mark.django_db
def test_scenario_shows_exact_active_artifact_release_and_project_draft(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    project, scenario = _scenario(org)
    artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="policy-flow",
        body=_workflow(),
        created_by="author",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                role="workflow_definition",
                type=ArtifactType.WORKFLOW_DEFINITION,
                logical_id=artifact.logical_id,
                version=artifact.version,
            )
        ],
        runtime_version="runtime:v1",
        created_by="release",
    )
    release.status = ReleaseStatus.ACTIVE
    release.save(update_fields=["status"])
    draft = WorkflowDraft.objects.create(
        organization=org,
        project=project,
        name="Policy graph",
        logical_id=artifact.logical_id,
        body=_workflow(),
        created_by="author",
        updated_by="author",
        last_published_version=artifact.version,
    )
    client.force_login(_member("auditor", org, Role.AUDITOR))

    response = client.get(reverse("console:scenario_detail", args=[scenario.pk]))
    body = response.content.decode()
    assert response.status_code == 200
    assert "workflow_definition" in body
    assert artifact.ref in body
    assert "checksum doğru" in body
    assert f"organization={org.slug}&amp;draft={draft.pk}" in body
    assert "release #" in body
    assert "En fazla 50 node ve 100 edge" in body


@pytest.mark.django_db
def test_artifact_detail_is_scoped_escaped_and_lists_release_pin(
    client: Client, settings: Any
) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    other = Organization.objects.create(slug="org-b", name="B")
    _project, scenario = _scenario(org)
    artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="input",
        body={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "</textarea><script>alert(1)</script>",
        },
        created_by="gitops",
    )
    release = compile_release(
        scenario=scenario,
        refs=[ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "input", 1)],
        runtime_version="runtime:v1",
        created_by="release",
    )
    client.force_login(_member("auditor", org, Role.AUDITOR))
    response = client.get(reverse("console:artifact_detail", args=[artifact.pk]))
    body = response.content.decode()
    assert response.status_code == 200
    assert "&lt;/textarea&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "</textarea><script>alert(1)</script>" not in body
    assert scenario.name in body
    assert f"release #{release.pk}" in body

    settings.CONSOLE_MAX_ARTIFACT_DISPLAY_CHARS = 10
    bounded = client.get(reverse("console:artifact_detail", args=[artifact.pk])).content.decode()
    assert "güvenli console görüntüleme sınırını aşıyor" in bounded
    assert "alert(1)" not in bounded

    foreign = create_artifact_version(
        organization=other,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        logical_id="foreign",
        body={"template": "foreign"},
        created_by="other",
    )
    assert client.get(reverse("console:artifact_detail", args=[foreign.pk])).status_code == 404


@pytest.mark.django_db
def test_foreign_or_malformed_manifest_ref_never_resolves(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    other = Organization.objects.create(slug="org-b", name="B")
    _project, scenario = _scenario(org)
    foreign = create_artifact_version(
        organization=other,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        logical_id="foreign",
        body={"template": "FOREIGN_PRIVATE_BODY"},
        created_by="other",
    )
    ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="runtime:v1",
        manifest={
            "artifacts": {
                "prompt": {
                    "type": foreign.type,
                    "ref": foreign.ref,
                    "checksum": foreign.checksum,
                },
                "bad": {"type": "workflow_definition", "ref": "broken:vx"},
                "huge": {
                    "type": "workflow_definition",
                    "ref": f"broken:v{'9' * 100}",
                },
            }
        },
        artifact_manifest_sha256="0" * 64,
        created_by="malformed-fixture",
    )
    client.force_login(_member("auditor", org, Role.AUDITOR))
    body = client.get(reverse("console:scenario_detail", args=[scenario.pk])).content.decode()
    assert "Artifact çözümlenemedi" in body
    assert "FOREIGN_PRIVATE_BODY" not in body

    ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.CANDIDATE,
        runtime_version="runtime:v1",
        manifest=["not-an-object"],
        artifact_manifest_sha256="1" * 64,
        created_by="malformed-fixture",
    )
    assert client.get(reverse("console:scenario_detail", args=[scenario.pk])).status_code == 200


@pytest.mark.django_db
def test_builder_deep_link_is_server_scoped(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    other = Organization.objects.create(slug="org-b", name="B")
    project, _scenario_obj = _scenario(org)
    foreign_project, _foreign_scenario = _scenario(other)
    draft = WorkflowDraft.objects.create(
        organization=org,
        project=project,
        name="Graph",
        logical_id="graph",
        body=_workflow(),
        created_by="author",
        updated_by="author",
    )
    foreign = WorkflowDraft.objects.create(
        organization=other,
        project=foreign_project,
        name="Foreign graph",
        logical_id="foreign-graph",
        body=_workflow(),
        created_by="foreign",
        updated_by="foreign",
    )
    client.force_login(_member("auditor", org, Role.AUDITOR))
    url = reverse("console:builder")
    response = client.get(url, {"organization": org.slug, "draft": str(draft.pk)})
    body = response.content.decode()
    assert response.status_code == 200
    assert f'"draft_id": {draft.pk}' in body
    assert '"organization": "org-a"' in body
    assert (
        client.get(url, {"organization": other.slug, "draft": str(foreign.pk)}).status_code == 404
    )
    assert client.get(url, {"organization": other.slug, "draft": str(draft.pk)}).status_code == 404
    assert client.get(url, {"draft": "9" * 10_000}).status_code == 404
