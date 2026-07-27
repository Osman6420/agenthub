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
    assert first.graph["api_version"] == "agenthub/compiled-workflow/v5"
    assert first.graph["execution_mode_analysis"] == {
        "supported_execution_modes": ["background", "sync"],
        "sync_blockers": [],
    }


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


def test_execution_mode_analysis_is_stable_and_fails_closed_for_unproven_nodes() -> None:
    body = workflow_body()
    body["spec"]["nodes"].insert(
        1,
        {
            "id": "call_tool",
            "type": "tool",
            "config": {"binding_role": "search", "output_key": "tool_result"},
        },
    )
    body["spec"]["edges"][0] = {"from": "request", "to": "call_tool"}
    body["spec"]["edges"].insert(1, {"from": "call_tool", "to": "check"})

    assert compile_workflow(body).graph["execution_mode_analysis"] == {
        "supported_execution_modes": ["background"],
        "sync_blockers": [{"code": "tool_pause_policy_unproven", "node_ids": ["call_tool"]}],
    }


def test_agent_loop_is_gated_and_reuses_the_closed_agent_policy_contract() -> None:
    body = {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "agent_flow.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "agent",
                    "type": "agent_loop",
                    "config": {
                        "tool_binding_roles": ["tool_binding.search"],
                        "retrieval": {"enabled": True},
                        "limits": {"max_steps": 4, "max_tool_calls": 2},
                    },
                    "input_mapping": [{"from": "/input", "to": "/input"}],
                    "output_mapping": [{"from": "/output", "to": "/output"}],
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "agent"},
                {"from": "agent", "to": "done"},
            ],
        },
    }
    with pytest.raises(WorkflowCompileError, match="not enabled"):
        compile_workflow(body)

    compiled = compile_workflow(body, allow_agent_loop=True)
    agent = next(node for node in compiled.graph["nodes"] if node["id"] == "agent")
    assert agent["config"]["policy"]["tools"] == ["tool_binding.search"]
    assert len(agent["config"]["policy_checksum"]) == 64
    assert compiled.graph["execution_mode_analysis"] == {
        "supported_execution_modes": ["background"],
        "sync_blockers": [{"code": "agent_loop_pause_policy_unproven", "node_ids": ["agent"]}],
    }

    body["spec"]["nodes"][1]["config"]["endpoint"] = "https://attacker.example"
    with pytest.raises(WorkflowCompileError, match="forbidden"):
        compile_workflow(body, allow_agent_loop=True)


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


def _mapping_workflow() -> dict:
    """A minimal input -> retrieve -> transform -> end graph used for mapping tests."""
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "mapping_flow.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "search",
                    "type": "retrieve",
                    "input_mapping": [{"from": "/input/query", "to": "/query"}],
                    "output_mapping": [{"from": "/chunks", "to": "/evidence/chunks"}],
                },
                {
                    "id": "shape",
                    "type": "transform",
                    "config": {"transform_profile_ref": "transform_profile.normalize"},
                    "input_mapping": [{"from": "/evidence/chunks", "to": "/rows"}],
                    "output_mapping": [{"from": "/result", "to": "/output"}],
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "search"},
                {"from": "search", "to": "shape"},
                {"from": "shape", "to": "done"},
            ],
        },
    }


def test_compile_accepts_eligible_node_mappings_and_transform() -> None:
    compiled = compile_workflow(_mapping_workflow())
    nodes = {node["id"]: node for node in compiled.graph["nodes"]}
    assert nodes["search"]["input_mapping"] == [{"from": "/input/query", "to": "/query"}]
    assert nodes["search"]["output_mapping"] == [{"from": "/chunks", "to": "/evidence/chunks"}]
    assert nodes["shape"]["type"] == "transform"
    assert nodes["shape"]["config"] == {"transform_profile_ref": "transform_profile.normalize"}
    # Deterministic checksum with mappings present.
    assert compile_workflow(_mapping_workflow()).checksum == compiled.checksum


def test_compile_rejects_mappings_on_ineligible_node() -> None:
    body = workflow_body()
    body["spec"]["nodes"][1]["input_mapping"] = [{"from": "/input/x", "to": "/y"}]
    with pytest.raises(WorkflowCompileError, match="does not accept mappings"):
        compile_workflow(body)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda body: body["spec"]["nodes"][1]["output_mapping"].__setitem__(
                0, {"from": "/chunks", "to": "/secret/key"}
            ),
            "WORKFLOW_PATH_PROTECTED",
        ),
        (
            lambda body: body["spec"]["nodes"][1]["output_mapping"].__setitem__(
                0, {"from": "/chunks", "to": "/evidence/x*"}
            ),
            "WORKFLOW_PATH_INVALID",
        ),
        (
            lambda body: body["spec"]["nodes"][1]["output_mapping"].append(
                {"from": "/chunks", "to": "/evidence/chunks"}
            ),
            "WORKFLOW_MAPPING_CONFLICT",
        ),
    ],
)
def test_compile_rejects_unsafe_mappings(mutate, message: str) -> None:
    body = _mapping_workflow()
    mutate(body)
    with pytest.raises(WorkflowCompileError, match=message):
        compile_workflow(body)


def test_transform_node_requires_profile_and_both_mappings() -> None:
    body = _mapping_workflow()
    del body["spec"]["nodes"][2]["output_mapping"]
    with pytest.raises(WorkflowCompileError, match="requires input_mapping and output_mapping"):
        compile_workflow(body)
    body = _mapping_workflow()
    body["spec"]["nodes"][2]["config"] = {}
    with pytest.raises(WorkflowCompileError, match="transform config is missing"):
        compile_workflow(body)


def test_tool_node_requires_exactly_one_output_sink() -> None:
    def tool_body(config: dict, **extra) -> dict:
        return {
            "api_version": "agenthub/v1",
            "kind": "Workflow",
            "metadata": {"id": "tool_flow.v1"},
            "spec": {
                "input_node": "request",
                "nodes": [
                    {"id": "request", "type": "input"},
                    {"id": "call", "type": "tool", "config": config, **extra},
                    {"id": "done", "type": "end"},
                ],
                "edges": [
                    {"from": "request", "to": "call"},
                    {"from": "call", "to": "done"},
                ],
            },
        }

    # Neither output_key nor output_mapping -> rejected.
    with pytest.raises(WorkflowCompileError, match="exactly one of output_key/output_mapping"):
        compile_workflow(tool_body({"binding_role": "tool_binding.search"}))
    # Both an output_key and an output_mapping -> rejected.
    with pytest.raises(WorkflowCompileError, match="exactly one of output_key/output_mapping"):
        compile_workflow(
            tool_body(
                {"binding_role": "tool_binding.search", "output_key": "out"},
                output_mapping=[{"from": "/status", "to": "/evidence/status"}],
            )
        )
    # input_key and input_mapping together -> rejected.
    with pytest.raises(WorkflowCompileError, match="both input_key and input_mapping"):
        compile_workflow(
            tool_body(
                {"binding_role": "tool_binding.search", "input_key": "in", "output_key": "out"},
                input_mapping=[{"from": "/input/q", "to": "/query"}],
            )
        )
    # A typed mapping-only tool node compiles.
    compiled = compile_workflow(
        tool_body(
            {"binding_role": "tool_binding.search"},
            input_mapping=[{"from": "/input/q", "to": "/query"}],
            output_mapping=[{"from": "/status", "to": "/evidence/status"}],
        )
    )
    assert any(node["type"] == "tool" for node in compiled.graph["nodes"])


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
