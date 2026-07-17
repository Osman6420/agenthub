"""P2.6.5 pinned child composition: compiler, authorization, budgets, isolation, lifecycle.

Composition is disabled by default; these tests enable ``WORKFLOW_COMPOSITION_ENABLED`` and prove
the ADR-0009 boundary: exact release pinning, four-source capability attenuation, tenant isolation,
recursion/budget guards, idempotency, terminal guards and untrusted child-output validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias, ScenarioType
from apps.gateway.execution_context import issue_execution_context
from apps.identity.models import BindingStatus, Consumer, ConsumerBinding, ConsumerProtocol
from apps.releases.compiler import ArtifactRef, CompileError, compile_release, promote_release
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization
from apps.workflows.compiler import WorkflowCompileError, compile_workflow
from apps.workflows.models import (
    ChildLinkStatus,
    WorkflowChildLink,
    WorkflowRun,
    WorkflowRunStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _enable_composition(settings: Any) -> None:
    settings.WORKFLOW_COMPOSITION_ENABLED = True


# --------------------------------------------------------------------------------------------------
# DSL / artifact builders
# --------------------------------------------------------------------------------------------------
def _input_contract() -> dict:
    return {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
        "additionalProperties": True,
    }


def _output_contract() -> dict:
    return {
        "type": "object",
        "required": ["answer", "sources"],
        "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
        "additionalProperties": True,
    }


def _leaf_workflow(workflow_id: str) -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": workflow_id},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "format", "type": "format_output", "config": {"template_ref": "clause"}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "format"},
                {"from": "format", "to": "done"},
            ],
        },
    }


def _leaf_agent(agent_id: str, *, tools: list[str] | None = None) -> dict:
    spec: dict = {
        "objective_key": "query",
        "output_key": "output",
        "retrieval": {"enabled": False},
        "tools": tools or [],
    }
    return {
        "api_version": "agenthub/v1",
        "kind": "Agent",
        "metadata": {"id": agent_id, "owner": "platform"},
        "spec": spec,
    }


def _parent_workflow(*, workflow_id: str, subworkflow_role: str, agent_role: str) -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": workflow_id},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "clause_extraction",
                    "type": "subworkflow",
                    "config": {"workflow_role": subworkflow_role, "max_depth": 2},
                    "input_mapping": [{"from": "/input/query", "to": "/input/query"}],
                    "output_mapping": [{"from": "/output", "to": "/branches/clauses/output"}],
                },
                {
                    "id": "risk_review",
                    "type": "agent_call",
                    "config": {
                        "agent_role": agent_role,
                        "max_decisions": 4,
                        "allowed_actions": ["respond"],
                    },
                    "input_mapping": [{"from": "/input/query", "to": "/input/query"}],
                    "output_mapping": [{"from": "/output", "to": "/output"}],
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "clause_extraction"},
                {"from": "clause_extraction", "to": "risk_review"},
                {"from": "risk_review", "to": "done"},
            ],
        },
    }


@dataclass
class Fixture:
    organization: Organization
    project: AIProject
    consumer: Consumer
    parent_scenario: Scenario
    parent_release: ScenarioRelease
    child_workflow_scenario: Scenario
    child_agent_scenario: Scenario
    child_workflow_artifact: Any
    child_agent_artifact: Any


def _make_child_workflow(org: Organization, project: AIProject, slug: str) -> tuple:
    scenario = Scenario.objects.create(
        project=project,
        slug=slug,
        name=slug,
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
    ic = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id=f"{slug}_in",
        body=_input_contract(),
        created_by="e",
    )
    oc = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id=f"{slug}_out",
        body=_output_contract(),
        created_by="e",
    )
    wf = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id=f"{slug}_wf",
        body=_leaf_workflow(f"{slug}.v1"),
        created_by="e",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("input_contract", ic.type, ic.logical_id, 1),
            ArtifactRef("output_contract", oc.type, oc.logical_id, 1),
            ArtifactRef("workflow_definition", wf.type, wf.logical_id, 1),
        ],
        runtime_version="wf:1",
        created_by="e",
    )
    promote_release(release)
    return scenario, release, wf


def _make_child_agent(org: Organization, project: AIProject, slug: str, *, tools=None) -> tuple:
    scenario = Scenario.objects.create(
        project=project,
        slug=slug,
        name=slug,
        type=ScenarioType.AGENT,
        status=LifecycleStatus.ACTIVE,
    )
    ic = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id=f"{slug}_in",
        body=_input_contract(),
        created_by="e",
    )
    oc = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id=f"{slug}_out",
        body=_output_contract(),
        created_by="e",
    )
    ag = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.AGENT_DEFINITION,
        logical_id=f"{slug}_ag",
        body=_leaf_agent(f"{slug}.v1", tools=tools),
        created_by="e",
    )
    refs = [
        ArtifactRef("input_contract", ic.type, ic.logical_id, 1),
        ArtifactRef("output_contract", oc.type, oc.logical_id, 1),
        ArtifactRef("agent_definition", ag.type, ag.logical_id, 1),
    ]
    release = compile_release(scenario=scenario, refs=refs, runtime_version="ag:1", created_by="e")
    promote_release(release)
    return scenario, release, ag


def _make_parent(
    org, project, child_wf_artifact, child_ag_artifact, *, sub_role="clause", agent_role="risk"
) -> tuple:
    scenario = Scenario.objects.create(
        project=project,
        slug="parent",
        name="parent",
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
    ic = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="parent_in",
        body=_input_contract(),
        created_by="e",
    )
    oc = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="parent_out",
        body=_output_contract(),
        created_by="e",
    )
    wf = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="parent_wf",
        body=_parent_workflow(
            workflow_id="parent.v1", subworkflow_role=sub_role, agent_role=agent_role
        ),
        created_by="e",
    )
    refs = [
        ArtifactRef("input_contract", ic.type, ic.logical_id, 1),
        ArtifactRef("output_contract", oc.type, oc.logical_id, 1),
        ArtifactRef("workflow_definition", wf.type, wf.logical_id, 1),
        ArtifactRef(
            f"child_workflow.{sub_role}",
            child_wf_artifact.type,
            child_wf_artifact.logical_id,
            1,
        ),
        ArtifactRef(
            f"child_agent.{agent_role}",
            child_ag_artifact.type,
            child_ag_artifact.logical_id,
            1,
        ),
    ]
    release = compile_release(scenario=scenario, refs=refs, runtime_version="wf:1", created_by="e")
    return scenario, release, refs


@pytest.fixture
def fx() -> Fixture:
    org = Organization.objects.create(slug="comp-org", name="Comp Org")
    project = AIProject.objects.create(organization=org, slug="proj", name="Proj")
    cw_scenario, _cw_release, cw_art = _make_child_workflow(org, project, "clausewf")
    ca_scenario, _ca_release, ca_art = _make_child_agent(org, project, "riskag")
    parent_scenario, parent_release, _refs = _make_parent(org, project, cw_art, ca_art)
    promote_release(parent_release)
    consumer = Consumer.objects.create(
        organization=org,
        subject="parent-client",
        name="Parent",
        protocol=ConsumerProtocol.REST,
    )
    ScenarioAlias.objects.create(organization=org, alias="parent", scenario=parent_scenario)
    ConsumerBinding.objects.create(
        consumer=consumer, scenario=parent_scenario, capabilities=["workflow_run"]
    )
    ConsumerBinding.objects.create(
        consumer=consumer, scenario=cw_scenario, capabilities=["workflow_run"]
    )
    ConsumerBinding.objects.create(
        consumer=consumer, scenario=ca_scenario, capabilities=["agent_invoke", "query"]
    )
    return Fixture(
        organization=org,
        project=project,
        consumer=consumer,
        parent_scenario=parent_scenario,
        parent_release=parent_release,
        child_workflow_scenario=cw_scenario,
        child_agent_scenario=ca_scenario,
        child_workflow_artifact=cw_art,
        child_agent_artifact=ca_art,
    )


def _parent_context(fx: Fixture, capabilities: list[str], composition=None) -> dict:
    return issue_execution_context(
        organization_id=fx.organization.id,
        project_id=fx.project.id,
        scenario_id=fx.parent_scenario.id,
        scenario_alias="parent",
        consumer_id=fx.consumer.id,
        capabilities=capabilities,
        release_id=fx.parent_release.id,
        request_id="req-1",
        composition=composition,
    )


def _parent_run(fx: Fixture, capabilities=None, composition=None) -> WorkflowRun:
    from apps.workflows.services import resolve_release_workflow

    capabilities = capabilities or ["workflow_run", "agent_invoke", "query"]
    version = resolve_release_workflow(fx.parent_release)
    run = WorkflowRun.objects.create(
        organization_id=fx.organization.id,
        scenario=fx.parent_scenario,
        release=fx.parent_release,
        workflow_version=version,
        consumer=fx.consumer,
        idempotency_key="parent-idem",
        input_checksum="x",
        execution_context=_parent_context(fx, capabilities, composition),
        redacted_state={"input": {"query": "hello"}},
        status=WorkflowRunStatus.RUNNING,
        deadline_at=timezone.now() + timedelta(seconds=300),
    )
    return run


def _node(fx: Fixture, node_type: str) -> dict:
    from apps.workflows.services import resolve_release_workflow

    graph = resolve_release_workflow(fx.parent_release).compiled_graph
    return next(n for n in graph["nodes"] if n["type"] == node_type)


def _child_wf(link: WorkflowChildLink) -> WorkflowRun:
    assert link.child_workflow_run_id is not None
    return WorkflowRun.objects.get(pk=link.child_workflow_run_id)


# --------------------------------------------------------------------------------------------------
# Compiler tests
# --------------------------------------------------------------------------------------------------
def test_composition_disabled_rejects_nodes(settings: Any) -> None:
    settings.WORKFLOW_COMPOSITION_ENABLED = False
    body = _parent_workflow(workflow_id="p.v1", subworkflow_role="c", agent_role="r")
    with pytest.raises(WorkflowCompileError, match="not enabled"):
        compile_workflow(body)


def test_valid_composition_compiles_when_enabled() -> None:
    body = _parent_workflow(workflow_id="p.v1", subworkflow_role="c", agent_role="r")
    compiled = compile_workflow(body, allow_composition=True)
    types = {n["type"] for n in compiled.graph["nodes"]}
    assert {"subworkflow", "agent_call"} <= types


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda c: c.pop("max_depth"), "subworkflow config"),
        (lambda c: c.update(max_depth=99), "max_depth"),
        (lambda c: c.update(max_depth=0), "max_depth"),
        (lambda c: c.update(workflow_role="bad role"), "workflow_role"),
    ],
)
def test_subworkflow_config_validation(mutate, match) -> None:
    body = _parent_workflow(workflow_id="p.v1", subworkflow_role="c", agent_role="r")
    node = next(n for n in body["spec"]["nodes"] if n["type"] == "subworkflow")
    mutate(node["config"])
    with pytest.raises(WorkflowCompileError, match=match):
        compile_workflow(body, allow_composition=True)


@pytest.mark.parametrize(
    "actions,match",
    [
        (["respond", "fly"], "unknown action"),
        (["retrieve"], "include respond"),
        (["respond", "respond"], "unique"),
        ([], "non-empty"),
    ],
)
def test_agent_call_action_validation(actions, match) -> None:
    body = _parent_workflow(workflow_id="p.v1", subworkflow_role="c", agent_role="r")
    node = next(n for n in body["spec"]["nodes"] if n["type"] == "agent_call")
    node["config"]["allowed_actions"] = actions
    with pytest.raises(WorkflowCompileError, match=match):
        compile_workflow(body, allow_composition=True)


def test_agent_call_max_decisions_bounds() -> None:
    body = _parent_workflow(workflow_id="p.v1", subworkflow_role="c", agent_role="r")
    node = next(n for n in body["spec"]["nodes"] if n["type"] == "agent_call")
    node["config"]["max_decisions"] = 999
    with pytest.raises(WorkflowCompileError, match="max_decisions"):
        compile_workflow(body, allow_composition=True)


def test_composition_requires_mappings() -> None:
    body = _parent_workflow(workflow_id="p.v1", subworkflow_role="c", agent_role="r")
    node = next(n for n in body["spec"]["nodes"] if n["type"] == "subworkflow")
    del node["input_mapping"]
    with pytest.raises(WorkflowCompileError, match="requires input_mapping"):
        compile_workflow(body, allow_composition=True)


# --------------------------------------------------------------------------------------------------
# Release-compiler pinning tests
# --------------------------------------------------------------------------------------------------
def test_release_pins_exact_child_metadata(fx: Fixture) -> None:
    manifest = fx.parent_release.manifest["artifacts"]
    sub = manifest["child_workflow.clause"]["child"]
    assert sub["kind"] == "workflow"
    assert sub["scenario_id"] == fx.child_workflow_scenario.id
    assert sub["release_checksum"]
    ag = manifest["child_agent.risk"]["child"]
    assert ag["kind"] == "agent"
    assert ag["scenario_id"] == fx.child_agent_scenario.id


def test_unpinned_child_role_fails_closed(fx: Fixture) -> None:
    # A parent workflow referencing a child role with no matching manifest pin fails compilation.
    org, project = fx.organization, fx.project
    scenario = Scenario.objects.create(
        project=project,
        slug="p2",
        name="p2",
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
    wf = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="p2_wf",
        body=_parent_workflow(workflow_id="p2.v1", subworkflow_role="ghost", agent_role="risk"),
        created_by="e",
    )
    oc = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="p2_out",
        body=_output_contract(),
        created_by="e",
    )
    with pytest.raises(CompileError, match="unpinned child role"):
        compile_release(
            scenario=scenario,
            refs=[
                ArtifactRef("output_contract", oc.type, oc.logical_id, 1),
                ArtifactRef("workflow_definition", wf.type, wf.logical_id, 1),
                # only the agent child pinned; the subworkflow "ghost" role is missing
                ArtifactRef(
                    "child_agent.risk",
                    fx.child_agent_artifact.type,
                    fx.child_agent_artifact.logical_id,
                    1,
                ),
            ],
            runtime_version="wf:1",
            created_by="e",
        )


def test_self_cycle_rejected(fx: Fixture) -> None:
    # A parent that pins itself as its own child sub-workflow is a static cycle.
    org, project = fx.organization, fx.project
    scenario = Scenario.objects.create(
        project=project,
        slug="selfref",
        name="selfref",
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
    ic = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="self_in",
        body=_input_contract(),
        created_by="e",
    )
    oc = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="self_out",
        body=_output_contract(),
        created_by="e",
    )
    leaf = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="self_leaf",
        body=_leaf_workflow("self_leaf.v1"),
        created_by="e",
    )
    base = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("input_contract", ic.type, ic.logical_id, 1),
            ArtifactRef("output_contract", oc.type, oc.logical_id, 1),
            ArtifactRef("workflow_definition", leaf.type, leaf.logical_id, 1),
        ],
        runtime_version="wf:1",
        created_by="e",
    )
    promote_release(base)
    # Now build a release for the SAME scenario whose workflow pins itself as a child.
    selfwf = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="self_leaf",  # same logical id -> new version 2
        body=_leaf_workflow("self_leaf.v2"),
        created_by="e",
    )
    del selfwf  # only needed to bump the version; not central to the assertion
    parent_body = _parent_workflow(workflow_id="selfp.v1", subworkflow_role="me", agent_role="risk")
    # Keep only the subworkflow branch to make the cycle explicit.
    parent_art = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="selfp",
        body=parent_body,
        created_by="e",
    )
    with pytest.raises(CompileError, match="cycle|multiple releases|no active released"):
        compile_release(
            scenario=scenario,
            refs=[
                ArtifactRef("input_contract", ic.type, ic.logical_id, 1),
                ArtifactRef("output_contract", oc.type, oc.logical_id, 1),
                ArtifactRef("workflow_definition", parent_art.type, parent_art.logical_id, 1),
                ArtifactRef("child_workflow.me", leaf.type, leaf.logical_id, 1),
                ArtifactRef(
                    "child_agent.risk",
                    fx.child_agent_artifact.type,
                    fx.child_agent_artifact.logical_id,
                    1,
                ),
            ],
            runtime_version="wf:1",
            created_by="e",
        )


# --------------------------------------------------------------------------------------------------
# Authorization / four-source intersection
# --------------------------------------------------------------------------------------------------
def test_source1_parent_caps_denied(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionError, admit_child

    run = _parent_run(fx, capabilities=["query"])  # missing agent_invoke and workflow_run
    node = _node(fx, "subworkflow")
    with transaction.atomic():
        run_locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
        with pytest.raises(CompositionError) as exc:
            admit_child(parent_run=run_locked, node=node, input_env={"input": {"query": "q"}})
    assert exc.value.code == "COMPOSITION_AUTHORITY_DENIED"


def test_source4_no_child_binding_denied(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionError, admit_child

    ConsumerBinding.objects.filter(
        consumer=fx.consumer, scenario=fx.child_workflow_scenario
    ).update(status=BindingStatus.DISABLED)
    run = _parent_run(fx)
    node = _node(fx, "subworkflow")
    with transaction.atomic():
        run_locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
        with pytest.raises(CompositionError) as exc:
            admit_child(parent_run=run_locked, node=node, input_env={"input": {"query": "q"}})
    assert exc.value.code == "COMPOSITION_AUTHORITY_DENIED"


def test_source2_callsite_envelope_gates_capability() -> None:
    # Source 2 (compiled call-site envelope): the agent-call ``allowed_actions`` gate tool_call.
    from apps.workflows.composition import _callsite_envelope

    respond_only = _callsite_envelope("agent", {"allowed_actions": ["respond"]})
    with_tool = _callsite_envelope("agent", {"allowed_actions": ["tool", "respond"]})
    assert "agent_invoke" in respond_only
    assert "tool_call" not in respond_only
    assert "tool_call" in with_tool


def test_source3_child_release_allowlist_excludes_capability(fx: Fixture) -> None:
    # A no-tool child agent: even when parent+call-site+live all grant tool_call, the child release
    # allowlist (source 3) omits it, so the effective set omits it.
    from apps.workflows.composition import _effective_child_capabilities

    child_release = ScenarioRelease.objects.get(scenario=fx.child_agent_scenario, status="active")
    node_config = {"agent_role": "risk", "max_decisions": 3, "allowed_actions": ["tool", "respond"]}
    payload = {"capabilities": ["agent_invoke", "query", "tool_call", "tool_call_side_effect"]}
    ConsumerBinding.objects.filter(consumer=fx.consumer, scenario=fx.child_agent_scenario).update(
        capabilities=["agent_invoke", "query", "tool_call", "tool_call_side_effect"]
    )
    effective = _effective_child_capabilities(
        kind="agent",
        node_config=node_config,
        parent_payload=payload,
        consumer=fx.consumer,
        child_scenario=fx.child_agent_scenario,
        child_release=child_release,
    )
    assert "agent_invoke" in effective
    assert "tool_call" not in effective


# --------------------------------------------------------------------------------------------------
# Stale release / budgets / cycle
# --------------------------------------------------------------------------------------------------
def test_stale_child_release_denied(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionError, admit_child

    # Re-promote a NEW release for the child workflow so its active release drifts from the pin.
    org = fx.organization
    ic = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="clausewf_in",
        body=_input_contract(),
        created_by="e2",
    )
    del ic
    new_wf = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="clausewf_wf",
        body=_leaf_workflow("clausewf.v2"),
        created_by="e2",
    )
    oc = ArtifactRef("output_contract", ArtifactType.OUTPUT_CONTRACT, "clausewf_out", 1)
    new_release = compile_release(
        scenario=fx.child_workflow_scenario,
        refs=[
            ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "clausewf_in", 1),
            oc,
            ArtifactRef("workflow_definition", new_wf.type, new_wf.logical_id, 2),
        ],
        runtime_version="wf:2",
        created_by="e2",
    )
    promote_release(new_release)
    run = _parent_run(fx)
    node = _node(fx, "subworkflow")
    with transaction.atomic():
        run_locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
        with pytest.raises(CompositionError) as exc:
            admit_child(parent_run=run_locked, node=node, input_env={"input": {"query": "q"}})
    assert exc.value.code == "COMPOSITION_CHILD_STALE"


def test_cycle_via_ancestry_denied(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionError, admit_child

    # The claim already lists the child scenario as an ancestor -> COMPOSITION_CYCLE.
    composition = {
        "depth": 1,
        "ancestry": [fx.parent_scenario.id, fx.child_workflow_scenario.id],
        "calls": 1,
        "root_run": 1,
    }
    run = _parent_run(fx, composition=composition)
    node = _node(fx, "subworkflow")
    with transaction.atomic():
        run_locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
        with pytest.raises(CompositionError) as exc:
            admit_child(parent_run=run_locked, node=node, input_env={"input": {"query": "q"}})
    assert exc.value.code == "COMPOSITION_CYCLE"


def test_max_depth_denied(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionError, admit_child

    composition = {"depth": 2, "ancestry": [fx.parent_scenario.id], "calls": 1, "root_run": 1}
    run = _parent_run(fx, composition=composition)
    node = _node(fx, "subworkflow")  # node max_depth=2 -> child depth would be 3 > cap 2
    with transaction.atomic():
        run_locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
        with pytest.raises(CompositionError) as exc:
            admit_child(parent_run=run_locked, node=node, input_env={"input": {"query": "q"}})
    assert exc.value.code == "COMPOSITION_MAX_DEPTH"


def test_cumulative_calls_denied(fx: Fixture) -> None:
    from apps.workflows.composition import (
        MAX_CUMULATIVE_CHILD_CALLS,
        CompositionError,
        admit_child,
    )

    composition = {
        "depth": 0,
        "ancestry": [fx.parent_scenario.id],
        "calls": MAX_CUMULATIVE_CHILD_CALLS,
        "root_run": 1,
    }
    run = _parent_run(fx, composition=composition)
    node = _node(fx, "subworkflow")
    with transaction.atomic():
        run_locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
        with pytest.raises(CompositionError) as exc:
            admit_child(parent_run=run_locked, node=node, input_env={"input": {"query": "q"}})
    assert exc.value.code == "COMPOSITION_MAX_CALLS"


def test_invalid_child_input_denied(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionError, admit_child

    run = _parent_run(fx)
    node = _node(fx, "subworkflow")
    with transaction.atomic():
        run_locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
        with pytest.raises(CompositionError) as exc:
            # Missing the mandatory ``input`` object.
            admit_child(parent_run=run_locked, node=node, input_env={"retrieval": {}})
    assert exc.value.code == "COMPOSITION_CHILD_INPUT_INVALID"


# --------------------------------------------------------------------------------------------------
# Admission / idempotency / lifecycle
# --------------------------------------------------------------------------------------------------
def _admit(fx: Fixture, node_type: str, run: WorkflowRun) -> WorkflowChildLink:
    from apps.workflows.composition import admit_child

    node = _node(fx, node_type)
    with transaction.atomic():
        run_locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
        admit_child(parent_run=run_locked, node=node, input_env={"input": {"query": "q"}})
    return WorkflowChildLink.objects.get(parent_run=run, call_site=node["id"])


def test_admit_creates_separate_child_run_and_link(fx: Fixture) -> None:
    run = _parent_run(fx)
    link = _admit(fx, "subworkflow", run)
    assert link.status == ChildLinkStatus.ADMITTED
    assert link.child_workflow_run_id is not None
    child = _child_wf(link)
    assert child.id != run.id
    assert child.organization_id == fx.organization.id
    assert child.scenario_id == fx.child_workflow_scenario.id
    # Fresh, attenuated child context (never the parent context).
    assert child.execution_context["composition"]["parent_run"] == run.id
    assert child.execution_context["capabilities"] == ["workflow_run"]
    assert child.execution_context["signature"] != run.execution_context["signature"]
    assert link.effective_capability_checksum


def test_duplicate_admission_is_idempotent(fx: Fixture) -> None:
    run = _parent_run(fx)
    link1 = _admit(fx, "subworkflow", run)
    link2 = _admit(fx, "subworkflow", run)
    assert link1.id == link2.id
    assert WorkflowRun.objects.filter(scenario=fx.child_workflow_scenario).count() == 1


def test_agent_child_context_carries_max_decisions(fx: Fixture) -> None:
    run = _parent_run(fx)
    link = _admit(fx, "agent_call", run)
    from apps.agents.models import AgentRun

    assert link.child_agent_run_id is not None
    child = AgentRun.objects.get(pk=link.child_agent_run_id)
    assert child.execution_context["composition"]["max_decisions"] == 4
    assert set(child.execution_context["capabilities"]) == {"agent_invoke", "query"}


def test_finalize_pending_then_success(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionPending, finalize_child

    run = _parent_run(fx)
    link = _admit(fx, "subworkflow", run)
    with pytest.raises(CompositionPending):
        finalize_child(link=link)
    # Complete the child run out-of-band.
    child = _child_wf(link)
    child.status = WorkflowRunStatus.COMPLETED
    child.redacted_state = {"output": {"answer": "clauses", "sources": []}}
    child.save(update_fields=["status", "redacted_state", "updated_at"])
    env = finalize_child(link=link)
    assert env == {"output": {"answer": "clauses", "sources": []}}
    link.refresh_from_db()
    assert link.status == ChildLinkStatus.COMPLETED


def test_finalize_child_failure_fails_closed(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionError, finalize_child

    run = _parent_run(fx)
    link = _admit(fx, "subworkflow", run)
    child = _child_wf(link)
    child.status = WorkflowRunStatus.FAILED
    child.save(update_fields=["status", "updated_at"])
    with pytest.raises(CompositionError) as exc:
        finalize_child(link=link)
    assert exc.value.code == "COMPOSITION_CHILD_FAILED"
    link.refresh_from_db()
    assert link.status == ChildLinkStatus.FAILED


def test_finalize_invalid_child_output_denied(fx: Fixture) -> None:
    from apps.workflows.composition import CompositionError, finalize_child

    run = _parent_run(fx)
    link = _admit(fx, "subworkflow", run)
    child = _child_wf(link)
    child.status = WorkflowRunStatus.COMPLETED
    child.redacted_state = {"output": {"answer": "x"}}  # missing required "sources"
    child.save(update_fields=["status", "redacted_state", "updated_at"])
    with pytest.raises(CompositionError) as exc:
        finalize_child(link=link)
    assert exc.value.code == "COMPOSITION_CHILD_OUTPUT_INVALID"


def test_cancellation_propagates_to_pending_child(fx: Fixture) -> None:
    from apps.workflows.services import cancel_workflow_run

    run = _parent_run(fx)
    run.status = WorkflowRunStatus.WAITING_CHILD
    run.save(update_fields=["status", "updated_at"])
    link = _admit(fx, "subworkflow", run)
    cancel_workflow_run(run=run, consumer=fx.consumer)
    link.refresh_from_db()
    assert link.status == ChildLinkStatus.CANCELLED
    child = _child_wf(link)
    assert child.status == WorkflowRunStatus.CANCELLED


def test_late_result_cannot_mutate_terminal_parent(fx: Fixture) -> None:
    # A terminal parent stays terminal even if a child result arrives late (task no-op guard).
    from apps.workflows.tasks import execute_workflow_run

    run = _parent_run(fx)
    run.status = WorkflowRunStatus.COMPLETED
    run.save(update_fields=["status", "updated_at"])
    result = execute_workflow_run(run.id, fx.organization.id)
    assert result == str(WorkflowRunStatus.COMPLETED)


_TERMINAL = {
    WorkflowRunStatus.COMPLETED,
    WorkflowRunStatus.FAILED,
    WorkflowRunStatus.TIMED_OUT,
    WorkflowRunStatus.CANCELLED,
}


def _drive_pending_children(fx: Fixture, run: WorkflowRun) -> None:
    """Run any admitted-but-unfinished child runs to completion (backend-agnostic pump)."""
    from apps.agents.models import TERMINAL_RUN_STATUSES, AgentRun
    from apps.agents.tasks import execute_agent_run
    from apps.workflows.tasks import execute_workflow_run

    for link in WorkflowChildLink.objects.filter(parent_run=run, status=ChildLinkStatus.ADMITTED):
        if link.child_kind == "workflow" and link.child_workflow_run_id:
            child = WorkflowRun.objects.get(pk=link.child_workflow_run_id)
            if child.status not in _TERMINAL:
                execute_workflow_run(child.id, child.organization_id)
        elif link.child_agent_run_id:
            agent_child = AgentRun.objects.get(pk=link.child_agent_run_id)
            if agent_child.status not in TERMINAL_RUN_STATUSES:
                execute_agent_run(agent_child.id, agent_child.organization_id)


def test_end_to_end_parent_runs_both_children(fx: Fixture) -> None:
    # Drive the full cascade deterministically on both backends: parent admits a child and pauses,
    # the child runs to completion, the parent resumes, validates the child output and continues.
    from apps.workflows.tasks import execute_workflow_run

    run = _parent_run(fx)
    run.status = WorkflowRunStatus.QUEUED
    run.save(update_fields=["status", "updated_at"])
    for _ in range(12):
        execute_workflow_run(run.id, fx.organization.id)
        run.refresh_from_db()
        if run.status in _TERMINAL:
            break
        _drive_pending_children(fx, run)
    assert run.status == WorkflowRunStatus.COMPLETED, run.error_code
    links = WorkflowChildLink.objects.filter(parent_run=run)
    assert links.count() == 2
    assert all(link.status == ChildLinkStatus.COMPLETED for link in links)
    output = run.redacted_state["output"]
    assert set(output) == {"answer", "sources"}


def test_child_completion_schedules_parent_resume(
    fx: Fixture, django_capture_on_commit_callbacks
) -> None:
    # The post-commit resume seam: when a pinned child reaches a terminal state, a parent
    # is scheduled after commit (a late/duplicate result cannot mutate an already-terminal parent).
    run = _parent_run(fx)
    run.status = WorkflowRunStatus.WAITING_CHILD
    run.awaiting_node = "clause_extraction"
    run.save(update_fields=["status", "awaiting_node", "updated_at"])
    link = _admit(fx, "subworkflow", run)
    child = _child_wf(link)
    with django_capture_on_commit_callbacks() as callbacks:
        child.status = WorkflowRunStatus.COMPLETED
        child.redacted_state = {"output": {"answer": "clauses", "sources": []}}
        child.save(update_fields=["status", "redacted_state", "updated_at"])
    assert len(callbacks) == 1  # exactly one parent-resume dispatch scheduled


@pytest.mark.skipif(connection.vendor != "postgresql", reason="FORCE RLS requires PostgreSQL")
def test_child_link_force_rls_blocks_cross_tenant(fx: Fixture) -> None:
    # The new tenant-owned link table enforces FORCE RLS: a non-owner role sees a link only
    # under the correct ``app.tenant_scope`` and never cross-tenant (superusers bypass RLS).
    run = _parent_run(fx)
    _admit(fx, "subworkflow", run)
    table = "workflows_workflowchildlink"
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'rls_probe_link'")
        if cursor.fetchone():
            cursor.execute("DROP OWNED BY rls_probe_link")
            cursor.execute("DROP ROLE rls_probe_link")
        cursor.execute("CREATE ROLE rls_probe_link NOSUPERUSER NOLOGIN")
        cursor.execute(f'GRANT SELECT ON "{table}" TO rls_probe_link')  # noqa: S608
        cursor.execute(
            "GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO rls_probe_link"
        )
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(fx.organization.id)])
        cursor.execute("SET ROLE rls_probe_link")
        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
        assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")

        cursor.execute(
            "SELECT set_config('app.tenant_scope', %s, true)", [str(fx.organization.id + 99_999)]
        )
        cursor.execute("SET ROLE rls_probe_link")
        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
        assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")
        cursor.execute("DROP OWNED BY rls_probe_link")
        cursor.execute("DROP ROLE rls_probe_link")


# --------------------------------------------------------------------------------------------------
# Compatibility: composition-free workflows are unaffected
# --------------------------------------------------------------------------------------------------
def test_non_composition_workflow_still_compiles(settings: Any) -> None:
    settings.WORKFLOW_COMPOSITION_ENABLED = False
    body = _leaf_workflow("leaf.v1")
    compiled = compile_workflow(body)
    assert {n["type"] for n in compiled.graph["nodes"]} == {"input", "format_output", "end"}
