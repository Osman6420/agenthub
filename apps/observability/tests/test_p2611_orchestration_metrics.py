"""Unified Run metric labels are bounded and content-free."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario
from apps.gateway.execution_context import issue_execution_context
from apps.identity.models import Consumer, ConsumerProtocol
from apps.observability.metrics import REGISTRY, render_metrics
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization
from apps.workflows.models import WorkflowVersion
from apps.workflows.services import request_unified_run

pytestmark = pytest.mark.django_db


def _fixture() -> tuple[ScenarioRelease, Consumer, WorkflowVersion]:
    org = Organization.objects.create(slug="metric-org", name="Metric Org")
    project = AIProject.objects.create(organization=org, slug="ops", name="Ops")
    scenario = Scenario.objects.create(
        project=project,
        slug="flow",
        name="Flow",
        status=LifecycleStatus.ACTIVE,
    )
    input_contract = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="i",
        body={"type": "object"},
        created_by="e",
    )
    output_contract = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="o",
        body={"type": "object"},
        created_by="e",
    )
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="w",
        body={
            "api_version": "agenthub/v1",
            "kind": "Workflow",
            "metadata": {"id": "m.v1"},
            "spec": {
                "input_node": "request",
                "nodes": [
                    {"id": "request", "type": "input"},
                    {
                        "id": "format",
                        "type": "format_output",
                        "config": {"template_ref": "ok"},
                    },
                    {"id": "done", "type": "end"},
                ],
                "edges": [
                    {"from": "request", "to": "format"},
                    {"from": "format", "to": "done"},
                ],
            },
        },
        created_by="e",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("input_contract", input_contract.type, input_contract.logical_id, 1),
            ArtifactRef("output_contract", output_contract.type, output_contract.logical_id, 1),
            ArtifactRef("workflow_definition", workflow.type, workflow.logical_id, 1),
        ],
        runtime_version="workflow:1",
        created_by="e",
    )
    promote_release(release)
    version = WorkflowVersion.objects.get(scenario=scenario)
    consumer = Consumer.objects.create(
        organization=org,
        subject="c",
        name="C",
        protocol=ConsumerProtocol.REST,
    )
    return release, consumer, version


def _value(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_unified_run_metrics_use_only_bounded_content_free_labels() -> None:
    release, consumer, version = _fixture()
    before = {
        "admission": _value(
            "agenthub_unified_run_admissions_total",
            {"execution_mode": "background"},
        ),
        "requested": _value(
            "agenthub_unified_run_events_total",
            {"event_type": "run.requested"},
        ),
        "queued": _value(
            "agenthub_unified_run_events_total",
            {"event_type": "run.queued"},
        ),
    }
    context = issue_execution_context(
        organization_id=consumer.organization_id,
        project_id=release.scenario.project_id,
        scenario_id=release.scenario_id,
        scenario_alias=release.scenario.slug,
        consumer_id=consumer.id,
        capabilities=["workflow_run"],
        release_id=release.id,
        request_id="unified-metrics",
    )
    run, created = request_unified_run(
        release=release,
        consumer=consumer,
        workflow_version=version,
        execution_context=context,
        input_payload={"query": "private metrics marker"},
        idempotency_key="unified-metrics",
        execution_mode="background",
    )

    assert created is True
    assert (
        _value(
            "agenthub_unified_run_admissions_total",
            {"execution_mode": "background"},
        )
        == before["admission"] + 1
    )
    assert (
        _value(
            "agenthub_unified_run_events_total",
            {"event_type": "run.requested"},
        )
        == before["requested"] + 1
    )
    assert (
        _value(
            "agenthub_unified_run_events_total",
            {"event_type": "run.queued"},
        )
        == before["queued"] + 1
    )
    rendered = "\n".join(
        line
        for line in render_metrics().decode().splitlines()
        if line.startswith("agenthub_unified_run_")
    )
    assert str(run.id) not in rendered
    assert "consumer=" not in rendered
    assert "organization=" not in rendered
    assert "run_id=" not in rendered
    assert "private metrics marker" not in rendered


def test_alert_rules_are_wellformed() -> None:
    rules = yaml.safe_load(Path("deploy/monitoring/prometheus-rules.yaml").read_text())
    for group in rules["groups"]:
        for rule in group["rules"]:
            assert rule["expr"].strip()
            assert rule["annotations"]["summary"]
