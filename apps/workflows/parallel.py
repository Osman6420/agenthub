"""Durable bounded parallel/join transition seam (P2.6.2).

Celery is delivery only. Every public operation reinstalls tenant context, locks the
authoritative rows and derives policy from the immutable compiled graph.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.tenancy.context import set_tenant_context
from apps.workflows.compiler import (
    COMPILED_WORKFLOW_API_VERSION,
    MAX_BRANCH_STATE_BYTES,
    MAX_FOR_EACH_ITEMS,
    MAX_PARALLEL_STATE_BYTES,
)
from apps.workflows.models import (
    WorkflowBranch,
    WorkflowBranchStatus,
    WorkflowJoin,
    WorkflowJoinStatus,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStatus,
)
from apps.workflows.services import _next_sequence
from apps.workflows.state_mapping import (
    MappingError,
    apply_output_mapping,
    parse_pointer,
    resolve_pointer,
)

TRANSITION_VERSION = "parallel-transition/v1"
TERMINAL_RUN_STATUSES = {
    WorkflowRunStatus.COMPLETED,
    WorkflowRunStatus.FAILED,
    WorkflowRunStatus.TIMED_OUT,
    WorkflowRunStatus.CANCELLED,
}


class ParallelTransitionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BranchTransitionResult:
    outcome: str
    join_status: str


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _node(run: WorkflowRun, node_id: str) -> dict[str, Any]:
    graph = run.workflow_version.compiled_graph
    if graph.get("api_version") != COMPILED_WORKFLOW_API_VERSION:
        raise ParallelTransitionError("WORKFLOW_COMPILER_VERSION_UNSUPPORTED")
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node
    raise ParallelTransitionError("WORKFLOW_PARALLEL_REGION_INVALID")


@transaction.atomic
def open_parallel_region(*, organization_id: int, run_id: int, region_node_id: str) -> WorkflowJoin:
    set_tenant_context(organization_id)
    run = (
        WorkflowRun.objects.select_for_update()
        .select_related("workflow_version")
        .get(pk=run_id, organization_id=organization_id)
    )
    if run.status in TERMINAL_RUN_STATUSES:
        raise ParallelTransitionError("WORKFLOW_TERMINAL")
    region = _node(run, region_node_id)
    if region["type"] not in {"parallel", "for_each"}:
        raise ParallelTransitionError("WORKFLOW_PARALLEL_REGION_INVALID")
    join_node = _node(run, region["config"]["join"])
    existing = WorkflowJoin.objects.filter(run=run, region_node_id=region_node_id).first()
    if existing is not None:
        return existing

    identities: list[tuple[str, int, Any]] = []
    if region["type"] == "parallel":
        identities = [
            (name, 0, deepcopy(run.redacted_state)) for name in join_node["config"]["branches"]
        ]
    else:
        try:
            items = resolve_pointer(
                run.redacted_state, parse_pointer(region["config"]["items_path"])
            )
        except MappingError as exc:
            raise ParallelTransitionError(exc.code) from None
        if not isinstance(items, list) or len(items) > min(
            region["config"]["max_items"], MAX_FOR_EACH_ITEMS
        ):
            raise ParallelTransitionError("WORKFLOW_BUDGET_EXCEEDED")
        identities = [
            ("for_each_items", ordinal, {"item": deepcopy(item)})
            for ordinal, item in enumerate(items)
        ]
    if not identities:
        raise ParallelTransitionError("WORKFLOW_PARALLEL_REGION_INVALID")
    required = join_node["config"].get("required", len(identities))
    join = WorkflowJoin.objects.create(
        organization_id=organization_id,
        run=run,
        region_node_id=region_node_id,
        join_node_id=join_node["id"],
        workflow_checksum=run.workflow_version.checksum,
        transition_version=TRANSITION_VERSION,
        mode=join_node["config"]["mode"],
        required_count=required,
        branch_count=len(identities),
    )
    WorkflowBranch.objects.bulk_create(
        [
            WorkflowBranch(
                organization_id=organization_id,
                run=run,
                region_node_id=region_node_id,
                branch_name=name,
                item_ordinal=ordinal,
                workflow_checksum=run.workflow_version.checksum,
                transition_version=TRANSITION_VERSION,
                input_state=value,
            )
            for name, ordinal, value in identities
        ]
    )
    WorkflowRunEvent.objects.create(
        run=run,
        sequence=_next_sequence(run),
        event_type="parallel_region_opened",
        node_id=region_node_id,
        outcome="open",
    )
    return join


@transaction.atomic
def claim_branch(*, organization_id: int, branch_id: int) -> str:
    set_tenant_context(organization_id)
    branch = (
        WorkflowBranch.objects.select_for_update()
        .select_related("run")
        .get(pk=branch_id, organization_id=organization_id)
    )
    if (
        branch.run.status in TERMINAL_RUN_STATUSES
        or branch.status == WorkflowBranchStatus.CANCELLED
    ):
        return "terminal"
    if branch.status == WorkflowBranchStatus.SUCCEEDED:
        return "duplicate"
    if branch.status == WorkflowBranchStatus.RUNNING:
        return "duplicate"
    if branch.attempt_count >= 3:
        branch.status = WorkflowBranchStatus.FAILED
        branch.reason_code = "WORKFLOW_BUDGET_EXCEEDED"
        branch.finished_at = timezone.now()
        branch.save(update_fields=["status", "reason_code", "finished_at", "updated_at"])
        return "budget_exhausted"
    branch.status = WorkflowBranchStatus.RUNNING
    branch.attempt_count += 1
    branch.started_at = branch.started_at or timezone.now()
    branch.save(update_fields=["status", "attempt_count", "started_at", "updated_at"])
    return "claimed"


@transaction.atomic
def complete_branch(
    *,
    organization_id: int,
    branch_id: int,
    idempotency_key: str,
    result_state: Any = None,
    reason_code: str = "",
) -> BranchTransitionResult:
    set_tenant_context(organization_id)
    branch = (
        WorkflowBranch.objects.select_for_update()
        .select_related("run__workflow_version")
        .get(pk=branch_id, organization_id=organization_id)
    )
    join = WorkflowJoin.objects.select_for_update().get(
        run=branch.run, region_node_id=branch.region_node_id, organization_id=organization_id
    )
    if branch.run.status in TERMINAL_RUN_STATUSES or join.status != WorkflowJoinStatus.OPEN:
        return BranchTransitionResult("late", str(join.status))
    if branch.status in {WorkflowBranchStatus.SUCCEEDED, WorkflowBranchStatus.FAILED}:
        return BranchTransitionResult("duplicate", str(join.status))
    if branch.status != WorkflowBranchStatus.RUNNING:
        raise ParallelTransitionError("WORKFLOW_BRANCH_STATE_INVALID")
    result = deepcopy(result_state or {})
    if _json_size(result) > MAX_BRANCH_STATE_BYTES:
        reason_code = "WORKFLOW_BUDGET_EXCEEDED"
    branch.status = WorkflowBranchStatus.FAILED if reason_code else WorkflowBranchStatus.SUCCEEDED
    branch.result_state = result if not reason_code else {}
    branch.result_checksum = compute_checksum(branch.result_state)
    branch.idempotency_key = idempotency_key[:128]
    branch.reason_code = reason_code
    branch.finished_at = timezone.now()
    branch.save(
        update_fields=[
            "status",
            "result_state",
            "result_checksum",
            "idempotency_key",
            "reason_code",
            "finished_at",
            "updated_at",
        ]
    )
    _evaluate_join(branch.run, join)
    return BranchTransitionResult("committed", str(join.status))


def _evaluate_join(run: WorkflowRun, join: WorkflowJoin) -> None:
    branches = list(
        WorkflowBranch.objects.select_for_update().filter(
            run=run, region_node_id=join.region_node_id
        )
    )
    succeeded = [item for item in branches if item.status == WorkflowBranchStatus.SUCCEEDED]
    failed = [item for item in branches if item.status == WorkflowBranchStatus.FAILED]
    terminal = (
        len(succeeded)
        + len(failed)
        + sum(item.status == WorkflowBranchStatus.CANCELLED for item in branches)
    )
    should_succeed = len(succeeded) >= join.required_count
    should_fail = bool(failed) and join.mode == "fail_fast"
    should_fail = should_fail or (
        join.mode in {"all", "threshold"}
        and len(succeeded) + (len(branches) - terminal) < join.required_count
    )
    if not should_succeed and not should_fail:
        return
    if should_succeed:
        node = _node(run, join.join_node_id)
        branch_state: dict[str, Any] = {"branches": {}}
        for name in node["config"]["branches"]:
            matching = sorted(
                (item for item in succeeded if item.branch_name == name),
                key=lambda item: item.item_ordinal,
            )
            if matching:
                branch_state["branches"][name] = {
                    "output": [item.result_state for item in matching]
                    if len(matching) > 1
                    else matching[0].result_state
                }
        if _json_size(branch_state) > MAX_PARALLEL_STATE_BYTES:
            should_succeed = False
        else:
            try:
                merged = apply_output_mapping(
                    run.redacted_state, branch_state, node["config"]["merge"]
                )
            except MappingError as exc:
                raise ParallelTransitionError(exc.code) from None
            join.merged_state = merged
    join.status = WorkflowJoinStatus.SUCCEEDED if should_succeed else WorkflowJoinStatus.FAILED
    join.closed_at = timezone.now()
    join.save(update_fields=["status", "merged_state", "closed_at", "updated_at"])
    WorkflowBranch.objects.filter(
        run=run,
        region_node_id=join.region_node_id,
        status__in=[WorkflowBranchStatus.PENDING, WorkflowBranchStatus.RUNNING],
    ).update(status=WorkflowBranchStatus.CANCELLED, finished_at=timezone.now())
    WorkflowRunEvent.objects.create(
        run=run,
        sequence=_next_sequence(run),
        event_type="join_closed",
        node_id=join.join_node_id,
        outcome=str(join.status),
        state_checksum=compute_checksum(join.merged_state) if should_succeed else "",
    )


@transaction.atomic
def cancel_parallel_work(*, organization_id: int, run_id: int) -> int:
    set_tenant_context(organization_id)
    WorkflowRun.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    now = timezone.now()
    count = WorkflowBranch.objects.filter(
        run_id=run_id,
        organization_id=organization_id,
        status__in=[WorkflowBranchStatus.PENDING, WorkflowBranchStatus.RUNNING],
    ).update(status=WorkflowBranchStatus.CANCELLED, finished_at=now)
    WorkflowJoin.objects.filter(
        run_id=run_id, organization_id=organization_id, status=WorkflowJoinStatus.OPEN
    ).update(status=WorkflowJoinStatus.CANCELLED, closed_at=now)
    return count


def pending_branch_ids(*, organization_id: int, limit: int = 100) -> list[int]:
    if not 1 <= limit <= 100:
        raise ParallelTransitionError("WORKFLOW_BUDGET_EXCEEDED")
    with transaction.atomic():
        set_tenant_context(organization_id)
        return list(
            WorkflowBranch.objects.filter(
                organization_id=organization_id, status=WorkflowBranchStatus.PENDING
            )
            .order_by("created_at", "id")
            .values_list("id", flat=True)[:limit]
        )
