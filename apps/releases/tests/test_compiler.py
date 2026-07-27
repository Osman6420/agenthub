"""Release compiler behavior and the single-active-release invariant."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.catalog.models import AIProject, Scenario, ScenarioType
from apps.releases.compiler import (
    ArtifactRef,
    CompileError,
    _assert_agent_loop_tools_pinned,
    _release_execution_mode_analysis,
    compile_release,
    promote_release,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization

INPUT_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {"query": {"type": "string"}},
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
    "additionalProperties": False,
}


@pytest.fixture
def scenario(db) -> Scenario:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    return Scenario.objects.create(project=project, slug="info", name="Info", type=ScenarioType.RAG)


def _seed_contracts(org: Organization) -> None:
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="customer_query",
        body=INPUT_SCHEMA,
        created_by="alice",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="customer_answer",
        body=OUTPUT_SCHEMA,
        created_by="alice",
    )


def _refs() -> list[ArtifactRef]:
    return [
        ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "customer_query", 1),
        ArtifactRef("output_contract", ArtifactType.OUTPUT_CONTRACT, "customer_answer", 1),
    ]


@pytest.mark.django_db
def test_compile_happy_path_is_deterministic(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)

    r1 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    r2 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )

    assert r1.status == ReleaseStatus.CANDIDATE
    assert r1.manifest["artifacts"]["input_contract"]["ref"] == "customer_query:v1"
    # Same inputs -> same manifest checksum.
    assert r1.artifact_manifest_sha256 == r2.artifact_manifest_sha256


@pytest.mark.django_db
def test_compile_fails_on_missing_reference(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    refs = [ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "customer_query", 99)]
    with pytest.raises(CompileError, match="unresolved reference"):
        compile_release(
            scenario=scenario, refs=refs, runtime_version="rt:3.0.0", created_by="alice"
        )
    assert ScenarioRelease.objects.count() == 0  # no candidate created


@pytest.mark.django_db
def test_compile_rejects_role_type_confusion(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    with pytest.raises(CompileError, match="incompatible"):
        compile_release(
            scenario=scenario,
            refs=[ArtifactRef("output_contract", ArtifactType.INPUT_CONTRACT, "customer_query", 1)],
            runtime_version="rt:3.0.0",
            created_by="alice",
        )
    assert ScenarioRelease.objects.count() == 0


@pytest.mark.django_db
def test_compile_fails_on_inline_secret_in_pinned_body(scenario: Scenario) -> None:
    org = scenario.project.organization
    # Bypass the service to plant a secret-bearing artifact, then compile.
    secret_body = {"token": "abc123"}
    ArtifactVersion.objects.create(
        organization=org,
        type=ArtifactType.MODEL_PROFILE,
        logical_id="chat",
        version=1,
        body=secret_body,
        checksum=compute_checksum(secret_body),
        created_by="x",
    )
    refs = [ArtifactRef("model_profile", ArtifactType.MODEL_PROFILE, "chat", 1)]
    with pytest.raises(CompileError, match="validation"):
        compile_release(
            scenario=scenario, refs=refs, runtime_version="rt:3.0.0", created_by="alice"
        )


@pytest.mark.django_db
def test_single_active_release_constraint(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    r1 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    r2 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    promote_release(r1)

    r2.status = ReleaseStatus.ACTIVE
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            r2.save()


@pytest.mark.django_db
def test_promote_supersedes_previous_active(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    r1 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    r2 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    promote_release(r1)
    promote_release(r2)

    r1.refresh_from_db()
    r2.refresh_from_db()
    assert r1.status == ReleaseStatus.SUPERSEDED
    assert r2.status == ReleaseStatus.ACTIVE
    active = ScenarioRelease.objects.filter(scenario=scenario, status=ReleaseStatus.ACTIVE)
    assert active.count() == 1


def test_agent_loop_policy_requires_exact_release_pinned_tools() -> None:
    graph = {
        "nodes": [
            {
                "id": "agent",
                "type": "agent_loop",
                "config": {
                    "policy": {
                        "tools": ["tool_binding.search"],
                        "actions": {"verify_roles": ["tool_binding.search"]},
                    }
                },
            }
        ]
    }
    with pytest.raises(CompileError, match="no pinned tool_binding"):
        _assert_agent_loop_tools_pinned(graph, {})

    unsafe_manifest = {
        "tool_binding.search": {
            "type": ArtifactType.TOOL_BINDING,
            "tool": {"side_effecting": False, "approval_required": True},
        }
    }
    with pytest.raises(CompileError, match="no-side-effect"):
        _assert_agent_loop_tools_pinned(graph, unsafe_manifest)

    safe_manifest = {
        "tool_binding.search": {
            "type": ArtifactType.TOOL_BINDING,
            "tool": {"side_effecting": False, "approval_required": False},
        }
    }
    _assert_agent_loop_tools_pinned(graph, safe_manifest)


@pytest.mark.django_db
@override_settings(WORKFLOW_AGENT_LOOP_ENABLED=True)
def test_release_pins_agent_loop_execution_mode_analysis(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    workflow = create_artifact_version(
        organization=scenario.project.organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="unified_agent",
        body={
            "api_version": "agenthub/v1",
            "kind": "Workflow",
            "metadata": {"id": "unified_agent.v1"},
            "spec": {
                "input_node": "request",
                "nodes": [
                    {"id": "request", "type": "input"},
                    {
                        "id": "agent",
                        "type": "agent_loop",
                        "config": {"tool_binding_roles": []},
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
        },
        created_by="alice",
    )

    release = compile_release(
        scenario=scenario,
        refs=[
            *_refs(),
            ArtifactRef(
                "workflow_definition",
                ArtifactType.WORKFLOW_DEFINITION,
                workflow.logical_id,
                workflow.version,
            ),
        ],
        runtime_version="rt:part-3",
        created_by="alice",
    )

    assert release.manifest["execution_mode_analysis"] == {
        "supported_execution_modes": ["background"],
        "sync_blockers": [{"code": "agent_loop_pause_policy_unproven", "node_ids": ["agent"]}],
        "sync_budget_seconds": 0,
    }


def _tool_graph(node_ids: list[str]) -> dict:
    return {
        "nodes": [
            {
                "id": node_id,
                "type": "tool",
                "config": {"binding_role": f"tool_binding.{node_id}"},
            }
            for node_id in node_ids
        ],
        "execution_mode_analysis": {
            "supported_execution_modes": ["background"],
            "sync_blockers": [{"code": "tool_pause_policy_unproven", "node_ids": node_ids}],
        },
    }


def _tool_pin(**overrides: object) -> dict:
    pin: dict[str, object] = {"approval_required": False, "timeout_seconds": 10}
    pin.update(overrides)
    return {"type": ArtifactType.TOOL_BINDING, "tool": pin}


def test_pinned_bounded_tool_discharges_the_sync_blocker() -> None:
    analysis = _release_execution_mode_analysis(
        _tool_graph(["call", "lookup"]),
        {"tool_binding.call": _tool_pin(), "tool_binding.lookup": _tool_pin(timeout_seconds=5)},
    )
    assert analysis == {
        "supported_execution_modes": ["background", "sync"],
        "sync_blockers": [],
        "sync_budget_seconds": 15,
    }


@pytest.mark.parametrize(
    ("pin", "code"),
    [
        (_tool_pin(approval_required=True), "tool_requires_approval"),
        (_tool_pin(timeout_seconds=None), "tool_timeout_unpinned"),
        (_tool_pin(timeout_seconds=0), "tool_timeout_unpinned"),
        (_tool_pin(timeout_seconds=31), "tool_timeout_unpinned"),
        (_tool_pin(timeout_seconds=True), "tool_timeout_unpinned"),
    ],
)
def test_unproven_tool_keeps_sync_unavailable_with_an_exact_reason(pin: dict, code: str) -> None:
    analysis = _release_execution_mode_analysis(_tool_graph(["call"]), {"tool_binding.call": pin})
    assert analysis == {
        "supported_execution_modes": ["background"],
        "sync_blockers": [{"code": code, "node_ids": ["call"]}],
        "sync_budget_seconds": 0,
    }


def test_tool_node_without_a_pinned_binding_is_never_sync() -> None:
    analysis = _release_execution_mode_analysis(_tool_graph(["call"]), {})
    assert analysis == {
        "supported_execution_modes": ["background"],
        "sync_blockers": [{"code": "tool_not_pinned", "node_ids": ["call"]}],
        "sync_budget_seconds": 0,
    }


def test_durable_blockers_are_never_discharged_by_tool_evidence() -> None:
    graph = _tool_graph(["call"])
    graph["nodes"].append({"id": "hold", "type": "event_wait", "config": {}})
    blockers = graph["execution_mode_analysis"]["sync_blockers"]
    blockers.append({"code": "durable_event_wait", "node_ids": ["hold"]})

    analysis = _release_execution_mode_analysis(graph, {"tool_binding.call": _tool_pin()})

    # The tool node is proven safe, but a reachable durable wait still forbids sync outright and
    # the budget is withheld so no caller can read a bound from a background-only graph.
    assert analysis == {
        "supported_execution_modes": ["background"],
        "sync_blockers": [{"code": "durable_event_wait", "node_ids": ["hold"]}],
        "sync_budget_seconds": 0,
    }


@pytest.mark.parametrize(
    "graph",
    [
        {"nodes": []},
        {"nodes": [], "execution_mode_analysis": {"sync_blockers": "not-a-list"}},
        {"nodes": [], "execution_mode_analysis": {"sync_blockers": ["not-a-mapping"]}},
        {"nodes": "not-a-list", "execution_mode_analysis": {"sync_blockers": []}},
    ],
)
def test_unreadable_analysis_fails_closed_to_background(graph: dict) -> None:
    analysis = _release_execution_mode_analysis(graph, {})
    assert analysis == {
        "supported_execution_modes": ["background"],
        "sync_blockers": [{"code": "compiled_mode_analysis_missing", "node_ids": []}],
        "sync_budget_seconds": 0,
    }


def _tool_definition_body(*, approval_required: bool) -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolDefinition",
        "metadata": {"id": "search.v1", "owner": "platform"},
        "spec": {
            "protocol": "http",
            "destination": {"scheme": "https", "host": "api.example.com"},
            "method": "POST",
            "input_contract_ref": "customer_query:v1",
            "output_contract_ref": "customer_answer:v1",
            "risk": "high" if approval_required else "low",
            "side_effecting": approval_required,
            "timeout_seconds": 12,
            "max_response_bytes": 65536,
            "rate_limit_per_minute": 60,
            "allowed_organizations": ["mcm"],
        },
    }


def _tool_workflow_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "tool_flow.v1"},
        "spec": {
            "input_node": "req",
            "nodes": [
                {"id": "req", "type": "input"},
                {
                    "id": "call",
                    "type": "tool",
                    "config": {
                        "binding_role": "tool_binding.search",
                        "input_key": "input",
                        "output_key": "output",
                    },
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [{"from": "req", "to": "call"}, {"from": "call", "to": "done"}],
        },
    }


def _compile_tool_release(scenario: Scenario, *, approval_required: bool) -> ScenarioRelease:
    from apps.tools.services import register_tool_binding, register_tool_definition

    org = scenario.project.organization
    _seed_contracts(org)
    register_tool_definition(
        artifact=create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.TOOL_DEFINITION,
            logical_id="search",
            body=_tool_definition_body(approval_required=approval_required),
            created_by="platform",
        )
    )
    binding = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_BINDING,
        logical_id="search_binding",
        body={
            "api_version": "agenthub/v1",
            "kind": "ToolBinding",
            "metadata": {"id": "search-binding.v1", "owner": "editor"},
            "spec": {
                "tool_ref": "search:v1",
                "allowed_input_fields": ["query"],
                "allowed_output_fields": ["answer"],
                "approval": {
                    "required": approval_required,
                    "approver_roles": ["approver"],
                    "self_approval_allowed": False,
                },
            },
        },
        created_by="editor",
    )
    register_tool_binding(artifact=binding)
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="tool_flow",
        body=_tool_workflow_body(),
        created_by="editor",
    )
    return compile_release(
        scenario=scenario,
        refs=[
            *_refs(),
            ArtifactRef("workflow_definition", workflow.type, "tool_flow", 1),
            ArtifactRef("tool_binding.search", binding.type, "search_binding", 1),
        ],
        runtime_version="rt:part-3",
        created_by="editor",
    )


@pytest.mark.django_db
def test_release_pins_the_tool_timeout_and_proves_a_bounded_graph_is_sync_capable(
    scenario: Scenario,
) -> None:
    release = _compile_tool_release(scenario, approval_required=False)

    assert release.manifest["artifacts"]["tool_binding.search"]["tool"]["timeout_seconds"] == 12
    assert release.manifest["execution_mode_analysis"] == {
        "supported_execution_modes": ["background", "sync"],
        "sync_blockers": [],
        "sync_budget_seconds": 12,
    }


@pytest.mark.django_db
def test_release_keeps_an_approval_requiring_tool_graph_background_only(
    scenario: Scenario,
) -> None:
    release = _compile_tool_release(scenario, approval_required=True)

    assert release.manifest["execution_mode_analysis"] == {
        "supported_execution_modes": ["background"],
        "sync_blockers": [{"code": "tool_requires_approval", "node_ids": ["call"]}],
        "sync_budget_seconds": 0,
    }
