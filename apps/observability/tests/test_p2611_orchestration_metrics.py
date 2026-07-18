"""P2.6.11 orchestration-structure metrics and alert-rule syntax.

Asserts terminal branch/join/wait/retry/compensation/child transitions increment bounded
counters (labels restricted to kind/mode/outcome/phase/failure_class — never tenant, run or
artifact identifiers), and that the new alert rules are syntactically well-formed with the
expected metric references.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioType
from apps.identity.models import Consumer, ConsumerProtocol
from apps.observability.metrics import REGISTRY
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.tenancy.models import Organization
from apps.workflows.models import (
    WorkflowBranch,
    WorkflowBranchStatus,
    WorkflowChildLink,
    WorkflowCompensationEntry,
    WorkflowCompensationStatus,
    WorkflowJoin,
    WorkflowJoinStatus,
    WorkflowNodeAttempt,
    WorkflowNodeAttemptStatus,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowVersion,
    WorkflowWait,
    WorkflowWaitKind,
    WorkflowWaitStatus,
)

pytestmark = pytest.mark.django_db


def _workflow_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "m.v1"},
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


def _build_run() -> WorkflowRun:
    org = Organization.objects.create(slug="metric-org", name="Metric Org")
    project = AIProject.objects.create(organization=org, slug="ops", name="Ops")
    scenario = Scenario.objects.create(
        project=project,
        slug="flow",
        name="Flow",
        type=ScenarioType.WORKFLOW,
        status=LifecycleStatus.ACTIVE,
    )
    in_c = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="i",
        body={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
        created_by="e",
    )
    out_c = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="o",
        body={
            "type": "object",
            "required": ["answer", "sources"],
            "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
            "additionalProperties": False,
        },
        created_by="e",
    )
    wf = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="w",
        body=_workflow_body(),
        created_by="e",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("input_contract", in_c.type, in_c.logical_id, 1),
            ArtifactRef("output_contract", out_c.type, out_c.logical_id, 1),
            ArtifactRef("workflow_definition", wf.type, wf.logical_id, 1),
        ],
        runtime_version="workflow:1",
        created_by="e",
    )
    promote_release(release)
    version = WorkflowVersion.objects.filter(scenario=scenario).first()
    assert version is not None
    consumer = Consumer.objects.create(
        organization=org, subject="c", name="C", protocol=ConsumerProtocol.REST
    )
    return WorkflowRun.objects.create(
        organization=org,
        scenario=scenario,
        release=release,
        workflow_version=version,
        consumer=consumer,
        idempotency_key="k",
        input_checksum="d" * 64,
        execution_context={},
        status=WorkflowRunStatus.RUNNING,
        deadline_at=timezone.now() + timedelta(hours=1),
    )


def _value(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_orchestration_terminal_transitions_increment_bounded_counters() -> None:
    run = _build_run()
    org = run.organization
    before = {
        "branch": _value("agenthub_workflow_branches_total", {"outcome": "succeeded"}),
        "join": _value("agenthub_workflow_joins_total", {"mode": "all", "outcome": "succeeded"}),
        "wait_created": _value(
            "agenthub_workflow_waits_total", {"kind": "human", "phase": "created"}
        ),
        "retry": _value("agenthub_workflow_retries_total", {"failure_class": "transient"}),
        "comp": _value("agenthub_workflow_compensations_total", {"outcome": "blocked"}),
        "child": _value(
            "agenthub_workflow_children_total", {"kind": "workflow", "status": "completed"}
        ),
    }

    WorkflowBranch.objects.create(
        organization=org,
        run=run,
        region_node_id="fan",
        branch_name="left",
        item_ordinal=0,
        workflow_checksum="e" * 64,
        transition_version="t",
        status=WorkflowBranchStatus.SUCCEEDED,
    )
    WorkflowJoin.objects.create(
        organization=org,
        run=run,
        region_node_id="fan",
        join_node_id="join",
        workflow_checksum="e" * 64,
        transition_version="t",
        mode="all",
        required_count=1,
        branch_count=1,
        status=WorkflowJoinStatus.SUCCEEDED,
    )
    WorkflowWait.objects.create(
        organization=org,
        run=run,
        kind=WorkflowWaitKind.HUMAN,
        node_id="approve",
        status=WorkflowWaitStatus.PENDING,
        pending_checksum="1" * 64,
        workflow_checksum="e" * 64,
        release_id_snapshot=run.release_id,
        compiler_version="v4",
        deadline_at=timezone.now() + timedelta(hours=1),
    )
    WorkflowNodeAttempt.objects.create(
        organization=org,
        run=run,
        node_id="format",
        ordinal=1,
        status=WorkflowNodeAttemptStatus.RETRY_WAIT,
        failure_class="transient",
    )
    WorkflowCompensationEntry.objects.create(
        organization=org,
        run=run,
        sequence=1,
        source_node_id="format",
        compensation_node_id="undo",
        status=WorkflowCompensationStatus.BLOCKED,
        input_checksum="9" * 64,
    )
    WorkflowChildLink.objects.create(
        organization=org,
        parent_run=run,
        call_site="c",
        child_kind="workflow",
        child_scenario=run.scenario,
        child_release=run.release,
        child_release_checksum="a" * 64,
        child_artifact_checksum="b" * 64,
        effective_capability_checksum="c" * 64,
        depth=1,
        status="completed",
    )

    assert (
        _value("agenthub_workflow_branches_total", {"outcome": "succeeded"}) == before["branch"] + 1
    )
    assert (
        _value("agenthub_workflow_joins_total", {"mode": "all", "outcome": "succeeded"})
        == before["join"] + 1
    )
    assert (
        _value("agenthub_workflow_waits_total", {"kind": "human", "phase": "created"})
        == before["wait_created"] + 1
    )
    assert (
        _value("agenthub_workflow_retries_total", {"failure_class": "transient"})
        == before["retry"] + 1
    )
    assert (
        _value("agenthub_workflow_compensations_total", {"outcome": "blocked"})
        == before["comp"] + 1
    )
    assert (
        _value("agenthub_workflow_children_total", {"kind": "workflow", "status": "completed"})
        == before["child"] + 1
    )


def test_new_alert_rules_are_wellformed() -> None:
    rules = yaml.safe_load(Path("deploy/monitoring/prometheus-rules.yaml").read_text())
    alerts = {
        rule["alert"] for group in rules["groups"] for rule in group["rules"] if "alert" in rule
    }
    assert {
        "AgentHubQueueSaturation",
        "AgentHubStuckWaits",
        "AgentHubRetryStorm",
        "AgentHubCompensationFailure",
        "AgentHubBudgetKillSwitch",
    } <= alerts
    for group in rules["groups"]:
        for rule in group["rules"]:
            assert rule["expr"].strip()
            assert rule["annotations"]["summary"]
