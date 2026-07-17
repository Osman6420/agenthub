from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import override_settings

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.builder.authoring_context import build_authoring_context, validate_workflow_references
from apps.builder.tests.conftest import BuilderFixture, simple_workflow
from apps.catalog.models import Scenario, ScenarioType
from apps.documents.models import (
    DocumentSet,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    ScenarioDocumentSetBinding,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tools.models import ToolBinding, ToolDefinition, ToolRisk

pytestmark = pytest.mark.django_db


def python_catalog_provider(*, organization_id: int) -> list[dict]:
    assert organization_id > 0
    schema = {"type": "object", "additionalProperties": False}
    return [
        {
            "node_ref": "multiply:r3",
            "execution_class": "python",
            "display_name": "Multiply",
            "purpose": "Multiply one bounded number",
            "revision": 3,
            "checksum": "c" * 64,
            "config_schema": schema,
            "input_schema": schema,
            "output_schema": schema,
        }
    ]


def unsafe_python_catalog_provider(*, organization_id: int) -> list[dict]:
    item = python_catalog_provider(organization_id=organization_id)[0]
    return [{**item, "source_code": "import os"}]


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
        {
            "role": "search_role",
            "approval_required": True,
            "description": "Private",
            "risk": "low",
            "side_effecting": False,
        }
    ]
    serialized = json.dumps(first)
    assert "private.invalid" not in serialized
    assert "secret:token" not in serialized


@override_settings(
    PYTHON_NODE_PUBLIC_CATALOG_PROVIDER=(
        "apps.builder.tests.test_authoring_context.python_catalog_provider"
    )
)
def test_context_includes_safe_python_release_contract_and_retrieval_capabilities(
    bf: BuilderFixture,
) -> None:
    scenario = Scenario.objects.create(
        organization=bf.org,
        project=bf.project,
        slug="capabilities",
        name="Capabilities",
        type=ScenarioType.WORKFLOW,
    )
    input_schema = {"type": "object", "properties": {"question": {"type": "string"}}}
    artifact = ArtifactVersion.objects.create(
        organization=bf.org,
        type=ArtifactType.INPUT_CONTRACT,
        logical_id="question",
        version=1,
        body=input_schema,
        checksum=compute_checksum(input_schema),
        created_by="author",
    )
    ScenarioRelease.objects.create(
        organization=bf.org,
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="v1",
        manifest={
            "artifacts": {
                "input_contract": {
                    "type": ArtifactType.INPUT_CONTRACT,
                    "ref": artifact.ref,
                    "checksum": artifact.checksum,
                },
                "prompt.summary": {
                    "type": ArtifactType.PROMPT_TEMPLATE,
                    "ref": "summary:v1",
                    "checksum": "d" * 64,
                },
                "model.default": {
                    "type": ArtifactType.MODEL_PROFILE,
                    "ref": "default:v1",
                    "checksum": "e" * 64,
                },
            }
        },
        artifact_manifest_sha256="f" * 64,
        created_by="author",
    )
    document_set = DocumentSet.objects.create(
        organization=bf.org, logical_id="manuals", name="Manuals"
    )
    DocumentSetVersion.objects.create(
        organization=bf.org,
        document_set=document_set,
        version=1,
        status=DocumentSetVersionStatus.ACTIVE,
    )
    ScenarioDocumentSetBinding.objects.create(
        organization=bf.org, scenario=scenario, document_set=document_set
    )

    context = build_authoring_context(project=bf.project, scenario=scenario)["snapshot"]

    assert context["workflow"]["python_nodes"][0]["node_ref"] == "multiply:r3"
    assert context["roles"]["prompt"] == [
        {"role": "prompt.summary", "ref": "summary:v1", "release_status": "active"}
    ]
    assert context["roles"]["model"][0]["role"] == "model.default"
    assert context["contracts"]["input"]["schema"] == input_schema
    assert context["retrieval"]["document_sets"] == [
        {"logical_id": "manuals", "name": "Manuals", "retrieval_available": False}
    ]


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


@override_settings(
    PYTHON_NODE_PUBLIC_CATALOG_PROVIDER=(
        "apps.builder.tests.test_authoring_context.unsafe_python_catalog_provider"
    )
)
def test_context_rejects_python_catalog_with_non_public_fields(bf: BuilderFixture) -> None:
    scenario = Scenario.objects.create(
        organization=bf.org,
        project=bf.project,
        slug="unsafe-catalog",
        name="Unsafe catalog",
        type=ScenarioType.WORKFLOW,
    )

    with pytest.raises(ValueError, match="python_node_catalog_invalid"):
        build_authoring_context(project=bf.project, scenario=scenario)


def test_reference_validation_rejects_invented_prompt_and_model_roles(
    bf: BuilderFixture,
) -> None:
    scenario = Scenario.objects.create(
        organization=bf.org,
        project=bf.project,
        slug="invented-generation-role",
        name="Invented generation role",
        type=ScenarioType.WORKFLOW,
    )
    context = build_authoring_context(project=bf.project, scenario=scenario)
    body = simple_workflow()
    generate_config: dict[str, Any] = {"input_key": "question", "output_key": "answer"}
    generate: dict[str, Any] = {
        "id": "generated-answer",
        "type": "generate",
        "config": generate_config,
    }
    body["spec"]["nodes"].append(generate)
    generate_config["prompt_ref"] = "invented.prompt"

    with pytest.raises(ValueError, match="capability_reference_invalid"):
        validate_workflow_references(body, context)

    generate_config.pop("prompt_ref")
    generate_config["model_profile_ref"] = "invented.model"
    with pytest.raises(ValueError, match="capability_reference_invalid"):
        validate_workflow_references(body, context)
