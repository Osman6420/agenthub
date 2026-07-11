from __future__ import annotations

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import ArtifactValidationError
from apps.catalog.models import AIProject, Scenario, ScenarioType
from apps.tenancy.models import Organization
from apps.workflows.compiler import WorkflowCompileError, compile_workflow
from apps.workflows.services import compile_workflow_version


def workflow_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "support_flow.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "check",
                    "type": "condition",
                    "config": {"expression": "request.score >= 0.6 and request.enabled == True"},
                },
                {"id": "yes", "type": "format_output", "config": {"template_ref": "ok.v1"}},
                {"id": "no", "type": "format_output", "config": {"template_ref": "no.v1"}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "check"},
                {"from": "check", "when": True, "to": "yes"},
                {"from": "check", "when": False, "to": "no"},
                {"from": "yes", "to": "done"},
                {"from": "no", "to": "done"},
            ],
        },
    }


def test_compile_is_deterministic_and_canonical() -> None:
    first = compile_workflow(workflow_body())
    second = compile_workflow(workflow_body())
    assert first.checksum == second.checksum
    assert first.graph == second.graph
    assert first.graph["api_version"] == "agenthub/compiled-workflow/v1"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda body: body["spec"]["edges"].append({"from": "done", "to": "request"}), "acyclic"),
        (lambda body: body["spec"]["nodes"].append({"id": "lost", "type": "end"}), "unreachable"),
        (lambda body: body["spec"]["nodes"].append({"id": "bad", "type": "python"}), "unknown"),
        (
            lambda body: body["spec"]["nodes"][1]["config"].update(
                {"expression": "__import__('os').system('whoami')"}
            ),
            "forbidden",
        ),
        (
            lambda body: body["spec"]["nodes"][2]["config"].update(
                {"endpoint": "https://attacker.example"}
            ),
            "forbidden",
        ),
    ],
)
def test_compile_rejects_unsafe_or_invalid_graphs(mutate, message: str) -> None:
    body = workflow_body()
    mutate(body)
    with pytest.raises(WorkflowCompileError, match=message):
        compile_workflow(body)


def test_compile_rejects_graph_over_hard_limit() -> None:
    body = workflow_body()
    body["spec"]["nodes"] = [{"id": f"node-{index}", "type": "input"} for index in range(51)]
    with pytest.raises(WorkflowCompileError, match="1..50"):
        compile_workflow(body)


def test_custom_node_requires_explicit_compiler_allowlist() -> None:
    body = workflow_body()
    body["spec"]["nodes"].insert(
        -1,
        {
            "id": "custom",
            "type": "custom",
            "config": {"node_ref": "redact.v1", "fields": ["answer"]},
        },
    )
    for edge in body["spec"]["edges"]:
        if edge["from"] in {"yes", "no"}:
            edge["to"] = "custom"
    body["spec"]["edges"].append({"from": "custom", "to": "done"})
    with pytest.raises(WorkflowCompileError, match="not allowed"):
        compile_workflow(body, allowed_custom_nodes=frozenset())
    compiled = compile_workflow(body, allowed_custom_nodes=frozenset({"redact.v1"}))
    assert any(node["type"] == "custom" for node in compiled.graph["nodes"])


@pytest.mark.django_db
def test_artifact_validation_and_tenant_scoped_compilation() -> None:
    organization = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=organization, slug="cx", name="CX")
    scenario = Scenario.objects.create(
        project=project,
        slug="workflow",
        name="Workflow",
        type=ScenarioType.WORKFLOW,
    )
    artifact = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="support_flow",
        body=workflow_body(),
        created_by="editor",
    )
    version = compile_workflow_version(
        scenario=scenario, source_artifact=artifact, created_by="editor"
    )
    replay = compile_workflow_version(
        scenario=scenario, source_artifact=artifact, created_by="editor"
    )
    assert replay.pk == version.pk
    assert version.organization_id == organization.id

    other = Organization.objects.create(slug="other", name="Other")
    other_project = AIProject.objects.create(organization=other, slug="other", name="Other")
    other_scenario = Scenario.objects.create(
        project=other_project,
        slug="workflow",
        name="Other workflow",
        type=ScenarioType.WORKFLOW,
    )
    with pytest.raises(WorkflowCompileError, match="another organization"):
        compile_workflow_version(
            scenario=other_scenario, source_artifact=artifact, created_by="attacker"
        )


@pytest.mark.django_db
def test_invalid_workflow_artifact_is_rejected_before_persistence() -> None:
    organization = Organization.objects.create(slug="mcm", name="MCM")
    body = workflow_body()
    body["spec"]["nodes"][1]["config"]["expression"] = "open('/etc/passwd').read()"
    with pytest.raises(ArtifactValidationError, match="forbidden"):
        create_artifact_version(
            organization=organization,
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
            logical_id="unsafe",
            body=body,
            created_by="editor",
        )
