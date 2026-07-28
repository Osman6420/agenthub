"""P2.6.11 retention/purge: report vs commit, in-window protection, audit, idempotency.

Uses unified Run classes to prove report, purge, lineage and audit behavior.
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
from apps.catalog.models import AIProject, LifecycleStatus, Scenario
from apps.identity.models import Consumer, ConsumerProtocol
from apps.observability.retention import RETENTION_DAYS, run_retention
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.tenancy.models import Organization
from apps.workflows.models import (
    Run,
    RunBranch,
    RunBranchStatus,
    RunStatus,
    RunWait,
    RunWaitKind,
    RunWaitStatus,
    WorkflowVersion,
)

User = get_user_model()
pytestmark = pytest.mark.django_db

SECRET = "BULKY-STATE"  # noqa: S105  # marker, not a credential
OLD = timedelta(days=RETENTION_DAYS + 10)
RECENT = timedelta(days=RETENTION_DAYS - 10)


def _run() -> Run:
    org = Organization.objects.create(slug="ret-org", name="Ret Org")
    project = AIProject.objects.create(organization=org, slug="ops", name="Ops")
    scenario = Scenario.objects.create(
        project=project,
        slug="flow",
        name="Flow",
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
    run = Run.objects.create(
        organization=org,
        scenario=scenario,
        release=release,
        workflow_version=version,
        consumer=consumer,
        actor_id=consumer.subject,
        response_id=f"resp_{'b' * 32}",
        idempotency_key="k",
        compiled_checksum=version.checksum,
        compiler_version=version.compiler_version,
        execution_mode="background",
        checkpoint={"state": SECRET},
        input_checksum="d" * 64,
        execution_context={},
        redacted_state={"state": SECRET},
        status=RunStatus.FAILED,
        deadline_at=timezone.now() + timedelta(hours=1),
        finished_at=timezone.now() - OLD,
    )
    return run


def _branch(run: Run, name: str, age: timedelta) -> RunBranch:
    return RunBranch.objects.create(
        organization=run.organization,
        run=run,
        region_node_id="fan",
        branch_name=name,
        item_ordinal=0,
        compiled_checksum="e" * 64,
        status=RunBranchStatus.SUCCEEDED,
        input_state={"x": SECRET},
        result_state={"y": SECRET},
        finished_at=timezone.now() - age,
    )


def _wait(run: Run, node: str, age: timedelta) -> RunWait:
    wait = RunWait.objects.create(
        organization=run.organization,
        run=run,
        kind=RunWaitKind.HUMAN,
        node_id=node,
        status=RunWaitStatus.RESUMED,
        resume_token_hash=f"{node[:1]}{'a' * 63}",
        redacted_payload={"p": SECRET},
        pending_checksum="1" * 64,
        checkpoint_version_snapshot=1,
        release_id_snapshot=run.release_id,
        compiled_checksum="e" * 64,
        compiler_version="v4",
        requester_actor_id="requester",
        deadline_at=timezone.now() + timedelta(hours=1),
        consumed_at=timezone.now(),
        consumed_by="reviewer",
        resume_checksum="2" * 64,
        result_checkpoint_version=2,
    )
    RunWait.objects.filter(pk=wait.pk).update(updated_at=timezone.now() - age)
    return wait


def test_report_mode_counts_eligible_without_mutating() -> None:
    run = _run()
    old_branch = _branch(run, "old", OLD)
    _branch(run, "recent", RECENT)
    _wait(run, "old_wait", OLD)

    reports = {r.retention_class: r for r in run_retention(commit=False)}
    assert reports["branch_state"].eligible == 1
    assert reports["branch_state"].purged == 0
    assert reports["wait_payload"].eligible == 1
    assert reports["run_state"].eligible == 1
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
    assert reports["wait_payload"].purged == 1
    assert reports["run_state"].purged == 1

    old_branch.refresh_from_db()
    recent_branch.refresh_from_db()
    old_wait.refresh_from_db()
    recent_wait.refresh_from_db()
    # Out-of-window bulky state cleared; row + lineage retained.
    assert old_branch.input_state == {} and old_branch.result_state == {}
    assert old_branch.status == RunBranchStatus.SUCCEEDED  # lineage retained
    assert old_wait.redacted_payload == {}
    assert old_wait.resume_token_hash
    # In-window state protected.
    assert recent_branch.input_state == {"x": SECRET}
    assert recent_wait.resume_token_hash
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
    assert reports2["wait_payload"].purged == 0


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
