"""P2.6.11 retention/purge: report vs commit, in-window protection, audit, idempotency.

Uses the buildable workflow classes (branch working state, wait correlation) to prove the
shared purge mechanics; ``agent_checkpoint`` funnels through the same ``_purge_class`` path.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioType
from apps.identity.models import Consumer, ConsumerProtocol
from apps.observability.retention import RETENTION_DAYS, run_retention
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.tenancy.models import Organization
from apps.workflows.models import (
    WorkflowBranch,
    WorkflowBranchStatus,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowVersion,
    WorkflowWait,
    WorkflowWaitKind,
    WorkflowWaitStatus,
)

User = get_user_model()
pytestmark = pytest.mark.django_db

SECRET = "BULKY-STATE"  # noqa: S105  # marker, not a credential
OLD = timedelta(days=RETENTION_DAYS + 10)
RECENT = timedelta(days=RETENTION_DAYS - 10)


def _run() -> WorkflowRun:
    org = Organization.objects.create(slug="ret-org", name="Ret Org")
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
        body={
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
                "edges": [{"from": "request", "to": "format"}, {"from": "format", "to": "done"}],
            },
        },
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
        status=WorkflowRunStatus.FAILED,
        deadline_at=timezone.now() + timedelta(hours=1),
    )


def _branch(run: WorkflowRun, name: str, age: timedelta) -> WorkflowBranch:
    return WorkflowBranch.objects.create(
        organization=run.organization,
        run=run,
        region_node_id="fan",
        branch_name=name,
        item_ordinal=0,
        workflow_checksum="e" * 64,
        transition_version="t",
        status=WorkflowBranchStatus.SUCCEEDED,
        input_state={"x": SECRET},
        result_state={"y": SECRET},
        finished_at=timezone.now() - age,
    )


def _wait(run: WorkflowRun, node: str, age: timedelta) -> WorkflowWait:
    wait = WorkflowWait.objects.create(
        organization=run.organization,
        run=run,
        kind=WorkflowWaitKind.HUMAN,
        node_id=node,
        status=WorkflowWaitStatus.RESUMED,
        correlation_hash="ab" * 16,
        redacted_payload={"p": SECRET},
        pending_checksum="1" * 64,
        workflow_checksum="e" * 64,
        release_id_snapshot=run.release_id,
        compiler_version="v4",
        deadline_at=timezone.now() + timedelta(hours=1),
    )
    WorkflowWait.objects.filter(pk=wait.pk).update(updated_at=timezone.now() - age)
    return wait


def test_report_mode_counts_eligible_without_mutating() -> None:
    run = _run()
    old_branch = _branch(run, "old", OLD)
    _branch(run, "recent", RECENT)
    _wait(run, "old_wait", OLD)

    reports = {r.retention_class: r for r in run_retention(commit=False)}
    assert reports["branch_state"].eligible == 1
    assert reports["branch_state"].purged == 0
    assert reports["wait_correlation"].eligible == 1
    assert "agent_checkpoint" in reports
    # Nothing mutated in report mode.
    old_branch.refresh_from_db()
    assert old_branch.input_state == {"x": SECRET}
    assert not AuditEvent.objects.filter(action="retention.purge").exists()


def test_commit_purges_only_out_of_window_state_and_audits() -> None:
    run = _run()
    old_branch = _branch(run, "old", OLD)
    recent_branch = _branch(run, "recent", RECENT)
    old_wait = _wait(run, "old_wait", OLD)
    recent_wait = _wait(run, "recent_wait", RECENT)

    reports = {r.retention_class: r for r in run_retention(commit=True, actor="root")}
    assert reports["branch_state"].purged == 1
    assert reports["wait_correlation"].purged == 1

    old_branch.refresh_from_db()
    recent_branch.refresh_from_db()
    old_wait.refresh_from_db()
    recent_wait.refresh_from_db()
    # Out-of-window bulky state cleared; row + lineage retained.
    assert old_branch.input_state == {} and old_branch.result_state == {}
    assert old_branch.status == WorkflowBranchStatus.SUCCEEDED  # lineage retained
    assert old_wait.correlation_hash == "" and old_wait.redacted_payload == {}
    # In-window state protected.
    assert recent_branch.input_state == {"x": SECRET}
    assert recent_wait.correlation_hash != ""
    # Audit records the class/window/count, never row contents.
    audits = AuditEvent.objects.filter(action="retention.purge")
    assert audits.exists()
    for event in audits:
        after = event.after or {}
        assert SECRET not in str(after)
        assert after["window_days"] == RETENTION_DAYS

    # Idempotent: a second commit purges nothing more.
    reports2 = {r.retention_class: r for r in run_retention(commit=True, actor="root")}
    assert reports2["branch_state"].purged == 0
    assert reports2["wait_correlation"].purged == 0


def test_retention_console_requires_platform_admin(client: Client) -> None:
    member = User.objects.create_user("member", password="x")  # noqa: S106
    client.force_login(member)
    assert client.get(reverse("console:retention_operations")).status_code == 403

    admin = User.objects.create_superuser("root", password="x")  # noqa: S106
    client.force_login(admin)
    report = client.get(reverse("console:retention_operations"))
    assert report.status_code == 200
    assert "branch_state" in report.content.decode()
    # A GET is report-only: no purge audit is written.
    assert not AuditEvent.objects.filter(action="retention.purge").exists()
