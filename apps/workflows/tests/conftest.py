from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias, ScenarioType
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.tokens import create_token
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization


@dataclass
class WorkflowFixture:
    organization: Organization
    scenario: Scenario
    consumer: Consumer
    token: str
    alias: str
    release: ScenarioRelease


def simple_workflow() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "simple.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "format", "type": "format_output", "config": {"template_ref": "ok"}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "format"},
                {"from": "format", "to": "done"},
            ],
        },
    }


@pytest.fixture
def workflow_fixture(db: object) -> WorkflowFixture:
    organization = Organization.objects.create(slug="workflow-org", name="Workflow Org")
    project = AIProject.objects.create(organization=organization, slug="ops", name="Ops")
    scenario = Scenario.objects.create(
        project=project,
        slug="flow",
        name="Flow",
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
    alias = "workflow-flow"
    ScenarioAlias.objects.create(
        organization=organization,
        alias=alias,
        scenario=scenario,
    )
    input_contract = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="workflow_input",
        body={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
        created_by="editor",
    )
    output_contract = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="workflow_output",
        body={
            "type": "object",
            "required": ["answer", "sources"],
            "properties": {
                "answer": {"type": "string"},
                "sources": {"type": "array"},
            },
            "additionalProperties": False,
        },
        created_by="editor",
    )
    workflow = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="simple",
        body=simple_workflow(),
        created_by="editor",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("input_contract", input_contract.type, input_contract.logical_id, 1),
            ArtifactRef("output_contract", output_contract.type, output_contract.logical_id, 1),
            ArtifactRef("workflow_definition", workflow.type, workflow.logical_id, 1),
        ],
        runtime_version="workflow:1",
        created_by="editor",
    )
    promote_release(release)
    consumer = Consumer.objects.create(
        organization=organization,
        subject="workflow-client",
        name="Workflow Client",
        protocol=ConsumerProtocol.REST,
    )
    ConsumerBinding.objects.create(
        consumer=consumer,
        scenario=scenario,
        capabilities=["workflow_run"],
    )
    _, raw_token = create_token(consumer=consumer, name="test")
    return WorkflowFixture(organization, scenario, consumer, raw_token, alias, release)
