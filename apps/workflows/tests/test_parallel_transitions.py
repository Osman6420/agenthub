from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.workflows.compiler import compile_workflow
from apps.workflows.models import (
    WorkflowBranch,
    WorkflowJoinStatus,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowVersion,
)
from apps.workflows.parallel import claim_branch, complete_branch, open_parallel_region
from apps.workflows.services import cancel_workflow_run
from apps.workflows.tests.conftest import WorkflowFixture
from apps.workflows.tests.test_parallel_compiler import parallel_workflow


def _run(fixture: WorkflowFixture, key: str) -> WorkflowRun:
    version = WorkflowVersion.objects.get(scenario=fixture.scenario)
    compiled = compile_workflow(parallel_workflow())
    WorkflowVersion.objects.filter(pk=version.pk).update(
        compiled_graph=compiled.graph,
        checksum=compiled.checksum,
        compiler_version="workflow-compiler/v3",
    )
    version.refresh_from_db()
    return WorkflowRun.objects.create(
        organization=fixture.organization,
        scenario=fixture.scenario,
        release=fixture.release,
        workflow_version=version,
        consumer=fixture.consumer,
        idempotency_key=key,
        input_checksum="0" * 64,
        execution_context={},
        redacted_state={"input": {"query": "safe"}},
        status=WorkflowRunStatus.RUNNING,
        deadline_at=timezone.now() + timedelta(seconds=300),
    )


@pytest.mark.django_db
def test_join_is_deterministic_under_reverse_completion_and_duplicate_delivery(
    workflow_fixture: WorkflowFixture,
) -> None:
    run = _run(workflow_fixture, "parallel-reverse")
    join = open_parallel_region(
        organization_id=run.organization_id, run_id=run.id, region_node_id="split"
    )
    branches = {branch.branch_name: branch for branch in WorkflowBranch.objects.filter(run=run)}
    assert (
        claim_branch(organization_id=run.organization_id, branch_id=branches["b"].id) == "claimed"
    )
    assert (
        complete_branch(
            organization_id=run.organization_id,
            branch_id=branches["b"].id,
            idempotency_key="b-1",
            result_state=["second"],
        ).join_status
        == WorkflowJoinStatus.OPEN
    )
    assert (
        claim_branch(organization_id=run.organization_id, branch_id=branches["a"].id) == "claimed"
    )
    closed = complete_branch(
        organization_id=run.organization_id,
        branch_id=branches["a"].id,
        idempotency_key="a-1",
        result_state=["first"],
    )
    assert closed.join_status == WorkflowJoinStatus.SUCCEEDED
    join.refresh_from_db()
    assert join.merged_state["evidence"] == {"a": ["first"], "b": ["second"]}
    assert (
        complete_branch(
            organization_id=run.organization_id,
            branch_id=branches["a"].id,
            idempotency_key="a-duplicate",
            result_state=["changed"],
        ).outcome
        == "late"
    )
    join.refresh_from_db()
    assert join.merged_state["evidence"]["a"] == ["first"]


@pytest.mark.django_db
def test_terminal_run_and_foreign_tenant_cannot_claim_or_resurrect(
    workflow_fixture: WorkflowFixture,
) -> None:
    run = _run(workflow_fixture, "parallel-terminal")
    open_parallel_region(organization_id=run.organization_id, run_id=run.id, region_node_id="split")
    branch = WorkflowBranch.objects.filter(run=run).first()
    assert branch is not None
    with pytest.raises(WorkflowBranch.DoesNotExist):
        claim_branch(organization_id=run.organization_id + 99_999, branch_id=branch.id)
    cancel_workflow_run(run=run, consumer=workflow_fixture.consumer)
    assert claim_branch(organization_id=run.organization_id, branch_id=branch.id) == "terminal"
    result = complete_branch(
        organization_id=run.organization_id,
        branch_id=branch.id,
        idempotency_key="late",
        result_state={"forbidden": True},
    )
    assert result.outcome == "late"
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.CANCELLED
    branch.refresh_from_db()
    assert branch.status == "cancelled"
