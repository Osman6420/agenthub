"""A new scenario is usable without manual contract authoring, and the main page has no
creation panel for input/output/eval artifacts."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.catalog.services import create_console_scenario
from apps.console.scenario_defaults import (
    default_contract_body,
    prepare_scenario_contract_defaults,
    scenario_artifact_logical_id,
)
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _author(org: Organization, project: AIProject, username: str) -> Any:
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


def _make_scenario_editor(org: Organization, user: Any, scenario: Scenario) -> None:
    """Creating a scenario does not make the creator its editor; assign that exactly."""

    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=OrganizationMembership.objects.get(organization=org, user=user),
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=user,
    )


@pytest.mark.parametrize("preset", ["empty_workflow", "document_answer", "agent_loop"])
def test_scenario_creation_prepares_exact_contract_defaults(client: Client, preset: str) -> None:
    org = Organization.objects.create(slug=f"defaults-{preset}", name=preset)
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    client.force_login(_author(org, project, f"author-{preset}"))

    response = client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {
            "name": f"{preset} scenario",
            "preset": preset,
            "logical_description": f"Stable purpose for {preset}",
        },
    )

    assert response.status_code == 302
    scenario = Scenario.objects.get(project=project)
    for artifact_type in (ArtifactType.INPUT_CONTRACT, ArtifactType.OUTPUT_CONTRACT):
        artifact = ArtifactVersion.objects.get(
            organization=org,
            type=artifact_type,
            logical_id=scenario_artifact_logical_id(scenario, artifact_type),
        )
        assert artifact.version == 1
        assert artifact.body == default_contract_body(artifact_type)
    assert (
        AuditEvent.objects.filter(
            organization_id=org.pk, action="console.scenario.contract_default.prepare"
        ).count()
        == 2
    )


def test_default_contracts_accept_the_canonical_envelope_and_reject_drift() -> None:
    input_schema = default_contract_body(ArtifactType.INPUT_CONTRACT)
    output_schema = default_contract_body(ArtifactType.OUTPUT_CONTRACT)

    jsonschema.validate({"query": "Kargo ne zaman gelir?"}, input_schema)
    jsonschema.validate({"answer": "Yarın", "sources": []}, output_schema)

    # The default is canonical, not permissive: it is not an "anything goes" schema.
    invalid_inputs: tuple[dict[str, Any], ...] = (
        {},
        {"query": ""},
        {"question": "yanlış anahtar"},
        {"query": "x", "extra": 1},
    )
    for invalid_input in invalid_inputs:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_input, input_schema)
    invalid_outputs: tuple[dict[str, Any], ...] = (
        {"answer": "x"},
        {"answer": 1, "sources": []},
        {"sources": []},
    )
    for invalid_output in invalid_outputs:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_output, output_schema)


def test_preparing_defaults_twice_never_creates_a_surprise_version() -> None:
    org = Organization.objects.create(slug="idempotent-org", name="Idempotent")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    scenario = create_console_scenario(project=project, name="Scenario")

    first = prepare_scenario_contract_defaults(scenario=scenario, actor="author")
    second = prepare_scenario_contract_defaults(scenario=scenario, actor="author")

    assert len(first) == 2
    assert second == []
    assert (
        ArtifactVersion.objects.filter(
            organization=org,
            type__in=(ArtifactType.INPUT_CONTRACT, ArtifactType.OUTPUT_CONTRACT),
        ).count()
        == 2
    )


def test_scenario_page_shows_contract_status_and_no_creation_panel(client: Client) -> None:
    org = Organization.objects.create(slug="panel-org", name="Panel")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    author = _author(org, project, "panel-author")
    client.force_login(author)
    client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {"name": "Panel scenario", "preset": "empty_workflow", "logical_description": "Purpose"},
    )
    scenario = Scenario.objects.get(project=project)
    _make_scenario_editor(org, author, scenario)

    body = client.get(
        reverse("console:scenario_detail_public", args=[scenario.public_id])
    ).content.decode()

    # The prepared defaults are visible as status, with a single explicit override action.
    assert "kanonik varsayılan" in body
    assert "Sözleşmeyi override et" in body
    assert body.count("Sözleşmeyi override et") == 2
    # No creation panel remains: eval suite moved to the candidate evaluation step.
    assert "?type=eval_suite" not in body
    assert "Eval suite artık aday değerlendirme adımında" in body


def test_override_route_still_enforces_exact_author_authorization(client: Client) -> None:
    org = Organization.objects.create(slug="override-org", name="Override")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    author = _author(org, project, "override-author")
    client.force_login(author)
    client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {"name": "Override scenario", "preset": "empty_workflow", "logical_description": "Purpose"},
    )
    scenario = Scenario.objects.get(project=project)
    url = reverse("console:scenario_artifact_create", args=[scenario.public_id])

    # Without the exact scenario responsibility the override route denies even a project admin.
    assert client.get(url, {"type": ArtifactType.INPUT_CONTRACT}).status_code == 403
    _make_scenario_editor(org, author, scenario)

    # The direct route stays reachable for an author and seeds from the canonical default.
    seeded = client.get(url, {"type": ArtifactType.INPUT_CONTRACT})
    assert seeded.status_code == 200
    assert "minLength" in seeded.content.decode()

    outsider = User.objects.create_user("override-outsider", password="x")  # noqa: S106
    client.force_login(outsider)
    assert client.get(url, {"type": ArtifactType.INPUT_CONTRACT}).status_code in {403, 404}
