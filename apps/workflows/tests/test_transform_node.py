"""Governed workflow ``transform`` node + typed mapping runtime integration (P2.6.1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioType
from apps.gateway.execution_context import issue_execution_context
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.releases.compiler import ArtifactRef, CompileError, compile_release, promote_release
from apps.tenancy.models import Organization
from apps.workflows.models import WorkflowRunStatus
from apps.workflows.runtime import WorkflowRuntimeError, _run_transform_node, execute_graph
from apps.workflows.services import request_workflow_run, resolve_release_workflow
from apps.workflows.tasks import execute_workflow_run

ORG_SLUG = "transform-org"


def _transform_profile_body() -> dict:
    return {
        "api_version": "agenthub/transform/v1",
        "kind": "DocumentTransform",
        "spec": {
            "steps": [
                {"op": "records.select", "pointer": "/rows"},
                {"op": "records.filter", "where": {"field": "/active", "eq": True}},
                {"op": "fields.default", "pointer": "/reviewed", "value": True},
            ]
        },
    }


def _workflow_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "transform_flow.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "normalize",
                    "type": "transform",
                    "config": {"transform_profile_ref": "transform_profile.normalize"},
                    "input_mapping": [{"from": "/input/rows", "to": "/rows"}],
                    "output_mapping": [{"from": "/result", "to": "/evidence/normalized"}],
                },
                {"id": "format", "type": "format_output", "config": {"template_ref": "ok"}},
                {"id": "check", "type": "validate_contract"},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "normalize"},
                {"from": "normalize", "to": "format"},
                {"from": "format", "to": "check"},
                {"from": "check", "to": "done"},
            ],
        },
    }


def _setup(*, pin_transform: bool = True):
    org = Organization.objects.create(slug=ORG_SLUG, name="Transform Org")
    project = AIProject.objects.create(organization=org, slug="ops", name="Ops")
    scenario = Scenario.objects.create(
        project=project,
        slug="flow",
        name="Flow",
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
    output_contract = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="wf_out",
        body={
            "type": "object",
            "required": ["answer", "sources"],
            "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
            "additionalProperties": False,
        },
        created_by="editor",
    )
    transform = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TRANSFORM_PROFILE,
        logical_id="normalize",
        body=_transform_profile_body(),
        created_by="platform",
    )
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="transform_flow",
        body=_workflow_body(),
        created_by="editor",
    )
    refs = [
        ArtifactRef("output_contract", output_contract.type, "wf_out", 1),
        ArtifactRef("workflow_definition", workflow.type, "transform_flow", 1),
    ]
    if pin_transform:
        refs.append(ArtifactRef("transform_profile.normalize", transform.type, "normalize", 1))
    release = compile_release(
        scenario=scenario, refs=refs, runtime_version="rt:1", created_by="editor"
    )
    return org, scenario, release


@pytest.mark.django_db
def test_release_fails_closed_when_transform_profile_not_pinned() -> None:
    with pytest.raises(CompileError, match="unpinned transform_profile role"):
        _setup(pin_transform=False)


@pytest.mark.django_db
def test_transform_node_runs_pinned_profile_and_maps_output() -> None:
    org, scenario, release = _setup()
    promote_release(release)
    consumer = Consumer.objects.create(
        organization=org, subject="c1", name="Client", protocol=ConsumerProtocol.REST
    )
    ConsumerBinding.objects.create(
        consumer=consumer, scenario=scenario, capabilities=[Capability.WORKFLOW_RUN]
    )
    context = issue_execution_context(
        organization_id=org.id,
        project_id=scenario.project_id,
        scenario_id=scenario.id,
        scenario_alias="flow",
        consumer_id=consumer.id,
        capabilities=[Capability.WORKFLOW_RUN],
        release_id=release.id,
        request_id="req-1",
    )
    run, _created = request_workflow_run(
        release=release,
        consumer=consumer,
        workflow_version=resolve_release_workflow(release),
        execution_context=context,
        input_payload={
            "rows": [{"active": True, "n": 1}, {"active": False, "n": 2}],
        },
        idempotency_key="transform-1",
    )
    assert execute_workflow_run(run.id) == WorkflowRunStatus.COMPLETED
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.COMPLETED
    # Only the active row survives the filter and gains the default; booleans/ints are not
    # redacted, so we can assert the governed transform actually ran and its output mapped.
    assert run.redacted_state["evidence"]["normalized"] == [
        {"active": True, "n": 1, "reviewed": True}
    ]


@pytest.mark.django_db
def test_transform_node_unresolved_profile_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.workflows.runtime.get_artifact_body_for_role", lambda release, role: None
    )
    with pytest.raises(WorkflowRuntimeError, match="WORKFLOW_TRANSFORM_PROFILE_UNRESOLVED"):
        _run_transform_node(
            config={"transform_profile_ref": "transform_profile.missing"},
            input_env={"rows": []},
            release=object(),
        )


@pytest.mark.django_db
def test_runtime_rejects_stale_compiled_contract_version() -> None:
    org, scenario, release = _setup()
    version = resolve_release_workflow(release)
    stale_graph = dict(version.compiled_graph)
    stale_graph["api_version"] = "agenthub/compiled-workflow/v1"
    run = SimpleNamespace(
        workflow_version=SimpleNamespace(compiled_graph=stale_graph),
        release=release,
        redacted_state={"input": {}},
        status=WorkflowRunStatus.RUNNING,
        deadline_at=release.created_at,
        consumer_id=None,
        refresh_from_db=lambda **kwargs: None,
    )
    with pytest.raises(WorkflowRuntimeError, match="WORKFLOW_COMPILER_VERSION_UNSUPPORTED"):
        execute_graph(run=run, verify_context=False)
