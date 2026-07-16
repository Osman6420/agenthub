from __future__ import annotations

import json

import pytest

from apps.builder.authoring_context import build_authoring_context, validate_workflow_references
from apps.builder.tests.conftest import BuilderFixture, simple_workflow
from apps.catalog.models import Scenario, ScenarioType
from apps.tools.models import ToolBinding, ToolDefinition, ToolRisk

pytestmark = pytest.mark.django_db


def test_context_is_deterministic_scoped_and_redacted(bf: BuilderFixture) -> None:
    scenario = Scenario.objects.create(
        organization=bf.org,
        project=bf.project,
        slug="studio",
        name="Studio",
        type=ScenarioType.WORKFLOW,
    )
    definition = ToolDefinition.objects.create(
        organization=bf.org,
        logical_id="search",
        version=1,
        manifest={"endpoint": "https://private.invalid", "description": "Private"},
        checksum="a" * 64,
        protocol="http",
        risk=ToolRisk.LOW,
        side_effecting=False,
    )
    ToolBinding.objects.create(
        organization=bf.org,
        tool_definition=definition,
        logical_id="search_role",
        version=1,
        manifest={"credential": "secret:token"},
        checksum="b" * 64,
        approval_required=True,
    )

    first = build_authoring_context(project=bf.project, scenario=scenario)
    second = build_authoring_context(project=bf.project, scenario=scenario)

    assert first == second
    assert first["snapshot"]["workflow"]["tool_binding_roles"] == [
        {"role": "search_role", "approval_required": True}
    ]
    serialized = json.dumps(first)
    assert "private.invalid" not in serialized
    assert "secret:token" not in serialized


def test_reference_validation_rejects_invented_tool_role(bf: BuilderFixture) -> None:
    scenario = Scenario.objects.create(
        organization=bf.org,
        project=bf.project,
        slug="studio",
        name="Studio",
        type=ScenarioType.WORKFLOW,
    )
    context = build_authoring_context(project=bf.project, scenario=scenario)
    body = simple_workflow()
    body["spec"]["nodes"].insert(
        1,
        {
            "id": "invented",
            "type": "tool",
            "config": {"binding_role": "foreign", "input_key": "x", "output_key": "y"},
        },
    )
    with pytest.raises(ValueError, match="capability_reference_invalid"):
        validate_workflow_references(body, context)
