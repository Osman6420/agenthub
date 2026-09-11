"""Scenario Studio exact-manifest resolution and no-write preflight."""

from __future__ import annotations

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.releases.authoring import (
    ManifestRequestError,
    analyze_workflow_requirements,
    preflight_release,
    resolve_manifest_refs,
)
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization
from apps.workflows.models import WorkflowVersion
from apps.workflows.presets import empty_workflow


@pytest.fixture
def scenario(db) -> Scenario:
    organization = Organization.objects.create(slug="studio-release", name="Studio Release")
    project = AIProject.objects.create(
        organization=organization,
        slug="support",
        name="Support",
    )
    return Scenario.objects.create(
        organization=organization,
        project=project,
        slug="assistant",
        name="Assistant",
    )


def _workflow(scenario: Scenario):
    return create_artifact_version(
        organization=scenario.organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="assistant_flow",
        body=empty_workflow(logical_id="assistant_flow"),
        created_by="author",
    )


@pytest.mark.django_db
def test_preflight_reuses_canonical_compiler_without_persisting(scenario: Scenario) -> None:
    workflow = _workflow(scenario)
    refs = resolve_manifest_refs(
        scenario=scenario,
        items=[
            {
                "artifact_version_id": workflow.pk,
                "role": "workflow_definition",
            }
        ],
    )

    result = preflight_release(
        scenario=scenario,
        refs=refs,
        runtime_version="runtime:v1",
        created_by="release-manager",
    )

    assert result.ok is True
    assert result.artifact_manifest_sha256
    assert ScenarioRelease.objects.count() == 0
    assert WorkflowVersion.objects.count() == 0


@pytest.mark.django_db
def test_preflight_returns_safe_structured_compiler_diagnostic(scenario: Scenario) -> None:
    contract = create_artifact_version(
        organization=scenario.organization,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="request",
        body={"type": "object"},
        created_by="author",
    )
    refs = resolve_manifest_refs(
        scenario=scenario,
        items=[
            {
                "artifact_version_id": contract.pk,
                "role": "input_contract",
            }
        ],
    )

    result = preflight_release(
        scenario=scenario,
        refs=refs,
        runtime_version="runtime:v1",
        created_by="release-manager",
    )

    assert result.as_dict() == {
        "ok": False,
        "diagnostics": [
            {
                "code": "workflow_missing",
                "message": "Candidate manifest bir canonical workflow_definition pini içermelidir.",
                "role": "workflow_definition",
                "artifact_type": "workflow_definition",
            }
        ],
    }
    assert ScenarioRelease.objects.count() == 0
    assert WorkflowVersion.objects.count() == 0


@pytest.mark.django_db
def test_manifest_resolution_denies_foreign_duplicate_and_malformed_rows(
    scenario: Scenario,
) -> None:
    workflow = _workflow(scenario)
    other = Organization.objects.create(slug="foreign-studio", name="Foreign")
    foreign = create_artifact_version(
        organization=other,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="private",
        body={"type": "object"},
        created_by="foreign",
    )

    with pytest.raises(ManifestRequestError, match="bulunamadı") as foreign_error:
        resolve_manifest_refs(
            scenario=scenario,
            items=[
                {
                    "artifact_version_id": foreign.pk,
                    "role": "input_contract",
                }
            ],
        )
    assert foreign_error.value.code == "artifact_not_found"

    with pytest.raises(ManifestRequestError) as duplicate_error:
        resolve_manifest_refs(
            scenario=scenario,
            items=[
                {
                    "artifact_version_id": workflow.pk,
                    "role": "workflow_definition",
                },
                {
                    "artifact_version_id": workflow.pk,
                    "role": "child_workflow.assistant",
                },
            ],
        )
    assert duplicate_error.value.code == "duplicate_artifact_version"

    with pytest.raises(ManifestRequestError) as malformed_error:
        resolve_manifest_refs(
            scenario=scenario,
            items=[{"artifact_version_id": True, "role": "workflow_definition"}],
        )
    assert malformed_error.value.code == "manifest_item_invalid"


@pytest.mark.django_db
def test_requirements_are_extracted_from_the_canonical_compiled_graph(
    scenario: Scenario,
) -> None:
    body = {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "dependency_flow"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "search",
                    "type": "tool",
                    "config": {
                        "binding_role": "tool_binding.search",
                        "output_key": "search_result",
                    },
                },
                {
                    "id": "answer",
                    "type": "generate",
                    "config": {
                        "prompt_ref": "prompt_template.summary",
                        "model_profile_ref": "model_profile.fast",
                    },
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "search"},
                {"from": "search", "to": "answer"},
                {"from": "answer", "to": "done"},
            ],
        },
    }
    workflow = create_artifact_version(
        organization=scenario.organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="dependency_flow",
        body=body,
        created_by="author",
    )

    result = analyze_workflow_requirements(
        scenario=scenario,
        workflow_artifact_id=workflow.pk,
    )

    assert result["workflow"] == {
        "artifact_version_id": workflow.pk,
        "logical_id": "dependency_flow",
        "version": 1,
        "checksum": workflow.checksum,
    }
    assert result["requirements"] == [
        {
            "role": "workflow_definition",
            "artifact_type": "workflow_definition",
            "node_ids": [],
        },
        {
            "role": "model_profile.fast",
            "artifact_type": "model_profile",
            "node_ids": ["answer"],
        },
        {
            "role": "prompt_template.summary",
            "artifact_type": "prompt_template",
            "node_ids": ["answer"],
        },
        {
            "role": "tool_binding.search",
            "artifact_type": "tool_binding",
            "node_ids": ["search"],
        },
    ]
