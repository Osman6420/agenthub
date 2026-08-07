"""Manifest derivation and the compile-time role gate that replaces manual pinning.

These cover the defect that motivated the change: a candidate could be compiled with the
*right* artifacts pinned under generic type-named roles while the workflow nodes referenced
their derived roles. Compilation and preflight both reported success, and the release only
failed when a consumer (or an evaluation) actually ran it.
"""

from __future__ import annotations

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.console.scenario_defaults import prepare_scenario_contract_defaults
from apps.releases.authoring import derive_manifest
from apps.releases.compiler import ArtifactRef, CompileError, compile_release
from apps.releases.scenario_artifacts import SCENARIO_SCOPED_ROLES
from apps.tenancy.models import Organization

RETRIEVE_ROLE = "ret_0c912fc4bda3b3c5a11c6590_profile"
PROMPT_ROLE = "gen_1afcdd2cd8a9777ce5f59afa_prompt"
MODEL_ROLE = "gen_1afcdd2cd8a9777ce5f59afa_model"
WORKFLOW_LOGICAL = "assistant_workflow"

RETRIEVAL_BODY = {
    "api_version": "agenthub/retrieval/v1",
    "kind": "RetrievalProfile",
    "mode": "hybrid",
    "top_k": 8,
    "score_threshold": 0,
    "vector_weight": 0.7,
    "keyword_weight": 0.3,
}


def _workflow_body() -> dict:
    """The node-bound shape produced by Studio: every artifact named by its derived role."""

    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": WORKFLOW_LOGICAL},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "retrieve",
                    "type": "retrieve",
                    "config": {"retrieval_profile_ref": RETRIEVE_ROLE},
                },
                {
                    "id": "answer",
                    "type": "generate",
                    "config": {"prompt_ref": PROMPT_ROLE, "model_profile_ref": MODEL_ROLE},
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "retrieve"},
                {"from": "retrieve", "to": "answer"},
                {"from": "answer", "to": "done"},
            ],
        },
    }


@pytest.fixture
def scenario(db) -> Scenario:
    organization = Organization.objects.create(slug="derive-org", name="Derive")
    project = AIProject.objects.create(organization=organization, slug="support", name="Support")
    return Scenario.objects.create(
        organization=organization,
        project=project,
        slug="assistant",
        name="Assistant",
    )


def _workflow_artifact(scenario: Scenario):
    return create_artifact_version(
        organization=scenario.organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id=WORKFLOW_LOGICAL,
        body=_workflow_body(),
        created_by="author",
    )


def _publish_node_artifacts(scenario: Scenario) -> None:
    """Publish exactly what Studio publishes with the workflow: logical id == manifest role."""

    for artifact_type, logical_id, body in (
        (ArtifactType.RETRIEVAL_PROFILE, RETRIEVE_ROLE, RETRIEVAL_BODY),
        (ArtifactType.PROMPT_TEMPLATE, PROMPT_ROLE, {"template": "Soruyu yanıtla: {{query}}"}),
        (
            ArtifactType.MODEL_PROFILE,
            MODEL_ROLE,
            {"profile_id": "00000000-0000-0000-0000-000000000001"},
        ),
    ):
        create_artifact_version(
            organization=scenario.organization,
            artifact_type=artifact_type,
            logical_id=logical_id,
            body=body,
            created_by="author",
        )


@pytest.mark.django_db
def test_derivation_pins_every_required_role_without_operator_input(scenario: Scenario) -> None:
    _publish_node_artifacts(scenario)
    prepare_scenario_contract_defaults(scenario=scenario, actor="author")
    workflow = _workflow_artifact(scenario)

    derived = derive_manifest(scenario=scenario, workflow_artifact=workflow)

    assert derived.ok is True
    assert derived.missing == []
    roles = {ref.role for ref in derived.refs}
    assert {"workflow_definition", RETRIEVE_ROLE, PROMPT_ROLE, MODEL_ROLE} <= roles
    assert set(SCENARIO_SCOPED_ROLES) <= roles


@pytest.mark.django_db
def test_derived_manifest_compiles_into_a_candidate(scenario: Scenario) -> None:
    _publish_node_artifacts(scenario)
    prepare_scenario_contract_defaults(scenario=scenario, actor="author")
    workflow = _workflow_artifact(scenario)

    derived = derive_manifest(scenario=scenario, workflow_artifact=workflow)
    release = compile_release(
        scenario=scenario,
        refs=derived.refs,
        runtime_version="runtime:v1",
        created_by="editor",
    )

    pinned = release.manifest["artifacts"]
    assert pinned[RETRIEVE_ROLE]["type"] == ArtifactType.RETRIEVAL_PROFILE
    assert pinned[PROMPT_ROLE]["type"] == ArtifactType.PROMPT_TEMPLATE
    assert pinned[MODEL_ROLE]["type"] == ArtifactType.MODEL_PROFILE


@pytest.mark.django_db
def test_type_named_roles_are_rejected_at_compile_time(scenario: Scenario) -> None:
    """Regression for the released defect: right artifacts, wrong role keys.

    This manifest is exactly what the old Studio panel produced, because the role defaulted
    to the artifact *type*. It used to compile and then fail at request time with
    ``WORKFLOW_RETRIEVAL_BINDING_INVALID``.
    """

    _publish_node_artifacts(scenario)
    workflow = _workflow_artifact(scenario)
    refs = [
        ArtifactRef("workflow_definition", ArtifactType.WORKFLOW_DEFINITION, WORKFLOW_LOGICAL, 1),
        ArtifactRef("retrieval_profile", ArtifactType.RETRIEVAL_PROFILE, RETRIEVE_ROLE, 1),
        ArtifactRef("prompt_template", ArtifactType.PROMPT_TEMPLATE, PROMPT_ROLE, 1),
        ArtifactRef("model_profile", ArtifactType.MODEL_PROFILE, MODEL_ROLE, 1),
    ]
    assert workflow.version == 1

    with pytest.raises(CompileError) as excinfo:
        compile_release(
            scenario=scenario,
            refs=refs,
            runtime_version="runtime:v1",
            created_by="editor",
        )

    assert excinfo.value.code == "workflow_role_unpinned"
    diagnostic = excinfo.value.as_diagnostic()
    assert diagnostic["role"] in {RETRIEVE_ROLE, PROMPT_ROLE, MODEL_ROLE}
    assert diagnostic["node_id"] in {"retrieve", "answer"}


@pytest.mark.django_db
def test_unpublished_node_artifact_is_reported_in_author_language(scenario: Scenario) -> None:
    prepare_scenario_contract_defaults(scenario=scenario, actor="author")
    workflow = _workflow_artifact(scenario)

    derived = derive_manifest(scenario=scenario, workflow_artifact=workflow)

    assert derived.ok is False
    missing_roles = {entry["role"] for entry in derived.missing}
    assert {RETRIEVE_ROLE, PROMPT_ROLE, MODEL_ROLE} == missing_roles
    retrieve_entry = next(e for e in derived.missing if e["role"] == RETRIEVE_ROLE)
    assert retrieve_entry["node_ids"] == ["retrieve"]
    # Author-facing, not a compiler diagnostic: it names the step, never the derived role.
    assert "retrieve" in retrieve_entry["message"]
    assert RETRIEVE_ROLE not in retrieve_entry["message"]


@pytest.mark.django_db
def test_derivation_never_resolves_another_tenants_artifact(scenario: Scenario) -> None:
    other = Organization.objects.create(slug="other-org", name="Other")
    for artifact_type, logical_id, body in (
        (ArtifactType.RETRIEVAL_PROFILE, RETRIEVE_ROLE, RETRIEVAL_BODY),
        (ArtifactType.PROMPT_TEMPLATE, PROMPT_ROLE, {"template": "foreign"}),
        (
            ArtifactType.MODEL_PROFILE,
            MODEL_ROLE,
            {"profile_id": "00000000-0000-0000-0000-000000000002"},
        ),
    ):
        create_artifact_version(
            organization=other,
            artifact_type=artifact_type,
            logical_id=logical_id,
            body=body,
            created_by="intruder",
        )
    prepare_scenario_contract_defaults(scenario=scenario, actor="author")
    workflow = _workflow_artifact(scenario)

    derived = derive_manifest(scenario=scenario, workflow_artifact=workflow)

    # The foreign artifacts carry the exact logical ids this workflow asks for, so a
    # tenant-blind lookup would have resolved them and produced a compilable manifest.
    assert {entry["role"] for entry in derived.missing} == {
        RETRIEVE_ROLE,
        PROMPT_ROLE,
        MODEL_ROLE,
    }
    assert {ref.role for ref in derived.refs} == {"workflow_definition", *SCENARIO_SCOPED_ROLES}
