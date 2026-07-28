from __future__ import annotations

from uuid import uuid4

import pytest

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import Scenario
from apps.gateway.execution_context import issue_execution_context
from apps.identity.models import ConsumerBinding
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.workflows.models import RunChildLink, RunChildStatus, WorkflowVersion
from apps.workflows.run_children import converge_run_child
from apps.workflows.services import request_unified_run
from apps.workflows.tests.test_unified_run import _execute_queued


def _parent_workflow() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "parent.v1"},
        "spec": {
            "input_node": "start",
            "nodes": [
                {"id": "start", "type": "input"},
                {
                    "id": "child",
                    "type": "subworkflow",
                    "config": {"workflow_role": "simple_child", "max_depth": 1},
                    "input_mapping": [{"from": "/input", "to": "/input"}],
                    "output_mapping": [{"from": "/output", "to": "/output"}],
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "start", "to": "child"},
                {"from": "child", "to": "done"},
            ],
        },
    }


def _parent_run(workflow_fixture):
    scenario = Scenario.objects.create(
        project=workflow_fixture.scenario.project,
        slug="parent",
        name="Parent",
        status="active",
    )
    workflow = create_artifact_version(
        organization=workflow_fixture.organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="parent_flow",
        body=_parent_workflow(),
        created_by="editor",
    )
    child_workflow = ArtifactVersion.objects.get(
        organization=workflow_fixture.organization,
        type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="simple",
        version=1,
    )
    input_contract = ArtifactVersion.objects.get(
        organization=workflow_fixture.organization,
        type=ArtifactType.INPUT_CONTRACT,
        logical_id="workflow_input",
        version=1,
    )
    output_contract = ArtifactVersion.objects.get(
        organization=workflow_fixture.organization,
        type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="workflow_output",
        version=1,
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                "workflow_definition", workflow.type, workflow.logical_id, workflow.version
            ),
            ArtifactRef(
                "child_workflow.simple_child",
                child_workflow.type,
                child_workflow.logical_id,
                child_workflow.version,
            ),
            ArtifactRef(
                "input_contract",
                input_contract.type,
                input_contract.logical_id,
                input_contract.version,
            ),
            ArtifactRef(
                "output_contract",
                output_contract.type,
                output_contract.logical_id,
                output_contract.version,
            ),
        ],
        runtime_version="workflow:child",
        created_by="editor",
    )
    promote_release(release)
    ConsumerBinding.objects.create(
        consumer=workflow_fixture.consumer,
        scenario=scenario,
        capabilities=["workflow_run"],
    )
    context = issue_execution_context(
        organization_id=workflow_fixture.organization.id,
        project_id=scenario.project_id,
        scenario_id=scenario.id,
        scenario_alias="parent",
        consumer_id=workflow_fixture.consumer.id,
        capabilities=["workflow_run"],
        release_id=release.id,
        request_id=str(uuid4()),
    )
    run, _created = request_unified_run(
        release=release,
        consumer=workflow_fixture.consumer,
        workflow_version=WorkflowVersion.objects.get(scenario=scenario),
        execution_context=context,
        input_payload={"query": "hello"},
        idempotency_key=f"parent:{uuid4()}",
        execution_mode="background",
    )
    return run


@pytest.mark.django_db
def test_subworkflow_uses_a_separate_canonical_run_and_resumes_parent(
    workflow_fixture, monkeypatch
) -> None:
    monkeypatch.setattr(
        "apps.workflows.tasks.dispatch_unified_background_run", lambda **_kwargs: None
    )
    parent = _parent_run(workflow_fixture)

    assert _execute_queued(parent).status == "waiting_child"
    link = RunChildLink.objects.select_related("child_run").get(parent_run=parent)
    assert link.status == RunChildStatus.ADMITTED
    assert link.organization_id == parent.organization_id
    assert link.child_run.scenario_id == workflow_fixture.scenario.id
    assert link.child_run_id != parent.id

    assert _execute_queued(link.child_run).status == "completed"
    assert converge_run_child(
        child_run_id=link.child_run_id,
        organization_id=parent.organization_id,
    )
    parent.refresh_from_db()
    assert parent.status == "queued"
    assert _execute_queued(parent).status == "completed"
    parent.refresh_from_db()
    assert parent.checkpoint["output"] == {"answer": "ok", "sources": []}
    link.refresh_from_db()
    assert link.status == RunChildStatus.COMPLETED


@pytest.mark.django_db
def test_subworkflow_fails_closed_without_live_child_binding(workflow_fixture, monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.workflows.tasks.dispatch_unified_background_run", lambda **_kwargs: None
    )
    parent = _parent_run(workflow_fixture)
    ConsumerBinding.objects.filter(
        consumer=workflow_fixture.consumer,
        scenario=workflow_fixture.scenario,
    ).delete()

    assert _execute_queued(parent).status == "failed"
    parent.refresh_from_db()
    assert parent.error_code == "COMPOSITION_AUTHORITY_DENIED"
    assert not RunChildLink.objects.filter(parent_run=parent).exists()
