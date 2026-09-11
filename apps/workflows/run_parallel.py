"""Durable branch/join transitions for the unified Run aggregate.

Celery is delivery only. Every public operation reinstalls tenant context, locks the Run
first and then its region rows, and derives policy from the immutable compiled graph.
"""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.releases.execution import run_workflow_graph
from apps.tenancy.context import set_tenant_context
from apps.workflows.compiler import (
    COMPILED_WORKFLOW_API_VERSION,
    MAX_BRANCH_STATE_BYTES,
    MAX_FOR_EACH_ITEMS,
    MAX_PARALLEL_CONCURRENCY,
    MAX_PARALLEL_DURATION_SECONDS,
    MAX_PARALLEL_STATE_BYTES,
)
from apps.workflows.models import (
    MAX_RUN_BRANCH_ATTEMPTS,
    RUN_CURSOR_KEY,
    RUN_TERMINAL_STATUSES,
    Run,
    RunBranch,
    RunBranchStatus,
    RunCancellationState,
    RunEventType,
    RunJoin,
    RunJoinStatus,
)
from apps.workflows.run_events import append_locked_run_event
from apps.workflows.state_mapping import (
    MappingError,
    apply_output_mapping,
    parse_pointer,
    resolve_pointer,
    set_pointer,
)

FOR_EACH_BRANCH_NAME = "for_each_items"
REGION_NODE_TYPES = frozenset({"parallel", "for_each"})
BRANCH_DELIVERY_LEASE_SECONDS = 30
BRANCH_CLAIM_LEASE_SECONDS = 60


class RunParallelError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RunBranchTransition:
    outcome: str
    join_status: str


@dataclass(frozen=True)
class RunBranchDelivery:
    branch_id: uuid.UUID
    delivery_token: uuid.UUID
    organization_id: int


@dataclass(frozen=True)
class RunParallelReconciliation:
    deliveries: tuple[RunBranchDelivery, ...]
    closed_regions: tuple[tuple[uuid.UUID, str], ...]
    regions_scanned: int


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _node(run: Run, node_id: str) -> dict[str, Any]:
    graph = run_workflow_graph(run)
    if graph.get("api_version") != COMPILED_WORKFLOW_API_VERSION:
        raise RunParallelError("RUN_EXECUTOR_GRAPH_VERSION_UNSUPPORTED")
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node
    raise RunParallelError("WORKFLOW_PARALLEL_REGION_INVALID")


def _business_state(run: Run) -> dict[str, Any]:
    """The Run's state without the server-owned resume cursor, which no node may observe."""

    # Branch workers are trusted runtime components and must receive the private
    # checkpoint. ``redacted_state`` exists only for operator/API projection; using
    # it here corrupts for-each items and can change workflow decisions.
    state = deepcopy(run.checkpoint)
    state.pop(RUN_CURSOR_KEY, None)
    return state


def _identities(run: Run, region: dict[str, Any], join_node: dict[str, Any]) -> list[tuple]:
    """Derive the closed branch/item set from the compiled graph and the Run's own state."""

    state = _business_state(run)
    if region["type"] == "parallel":
        return [(name, 0, deepcopy(state)) for name in join_node["config"]["branches"]]
    try:
        items = resolve_pointer(state, parse_pointer(region["config"]["items_path"]))
        item_path = parse_pointer(region["config"]["item_path"])
    except MappingError as exc:
        raise RunParallelError(exc.code) from None
    if (
        not item_path
        or not isinstance(items, list)
        or len(items) > min(region["config"]["max_items"], MAX_FOR_EACH_ITEMS)
    ):
        raise RunParallelError("WORKFLOW_BUDGET_EXCEEDED")
    identities: list[tuple] = []
    for ordinal, item in enumerate(items):
        item_state: dict[str, Any] = {}
        try:
            set_pointer(item_state, item_path, deepcopy(item))
        except MappingError as exc:
            raise RunParallelError(exc.code) from None
        identities.append((FOR_EACH_BRANCH_NAME, ordinal, item_state))
    return identities


@transaction.atomic
def open_run_region(*, organization_id: int, run_id: uuid.UUID, region_node_id: str) -> RunJoin:
    """Materialise one region's durable branches exactly once, idempotently."""

    set_tenant_context(organization_id)
    run = (
        Run.objects.select_for_update()
        .select_related("workflow_version")
        .get(pk=run_id, organization_id=organization_id)
    )
    if run.status in RUN_TERMINAL_STATUSES:
        raise RunParallelError("RUN_TERMINAL")
    region = _node(run, region_node_id)
    if region["type"] not in REGION_NODE_TYPES:
        raise RunParallelError("WORKFLOW_PARALLEL_REGION_INVALID")
    existing = RunJoin.objects.filter(run=run, region_node_id=region_node_id).first()
    if existing is not None:
        return existing
    join_node = _node(run, region["config"]["join"])
    identities = _identities(run, region, join_node)
    if not identities:
        raise RunParallelError("WORKFLOW_PARALLEL_REGION_INVALID")
    required = int(join_node["config"].get("required", len(identities)))
    if not 1 <= required <= len(identities):
        raise RunParallelError("WORKFLOW_PARALLEL_REGION_INVALID")
    checksum = run.workflow_version.checksum
    max_concurrency = min(
        int(region["config"]["max_concurrency"]),
        len(identities),
        MAX_PARALLEL_CONCURRENCY,
    )
    max_duration_seconds = min(
        int(region["config"].get("max_duration_seconds", MAX_PARALLEL_DURATION_SECONDS)),
        MAX_PARALLEL_DURATION_SECONDS,
    )
    max_state_bytes = min(
        int(region["config"].get("max_state_bytes", MAX_PARALLEL_STATE_BYTES)),
        MAX_PARALLEL_STATE_BYTES,
    )
    if any(_json_size(value) > max_state_bytes for _name, _ordinal, value in identities):
        raise RunParallelError("WORKFLOW_BUDGET_EXCEEDED")
    deadline_at = min(run.deadline_at, timezone.now() + timedelta(seconds=max_duration_seconds))
    join = RunJoin.objects.create(
        organization_id=organization_id,
        run=run,
        region_node_id=region_node_id,
        join_node_id=join_node["id"],
        compiled_checksum=checksum,
        mode=join_node["config"]["mode"],
        required_count=required,
        branch_count=len(identities),
        max_concurrency=max_concurrency,
        max_duration_seconds=max_duration_seconds,
        max_state_bytes=max_state_bytes,
        deadline_at=deadline_at,
    )
    RunBranch.objects.bulk_create(
        [
            RunBranch(
                organization_id=organization_id,
                run=run,
                region_node_id=region_node_id,
                branch_name=name,
                item_ordinal=ordinal,
                compiled_checksum=checksum,
                input_state=value,
            )
            for name, ordinal, value in identities
        ]
    )
    append_locked_run_event(
        run=run,
        event_type=RunEventType.BRANCHES_OPENED,
        node_id=region_node_id,
        outcome="open",
        payload={"branch_count": len(identities), "required_count": required},
    )
    run.save(update_fields=["next_event_sequence", "updated_at"])
    return join


def _clear_delivery(branch: RunBranch) -> None:
    branch.delivery_token = None
    branch.delivery_expires_at = None
    branch.claim_expires_at = None


def _close_run_join(
    *,
    run: Run,
    join: RunJoin,
    status: str | RunJoinStatus,
    reason_code: str,
    succeeded: list[RunBranch],
    failed: list[RunBranch],
    cancelled: list[RunBranch],
    now: datetime,
) -> None:
    """Persist one terminal join and revoke all unfinished branch authorities."""

    join.status = status
    join.reason_code = reason_code[:64]
    join.closed_at = now
    join.save(update_fields=["status", "merged_state", "reason_code", "closed_at", "updated_at"])
    RunBranch.objects.filter(
        run=run,
        region_node_id=join.region_node_id,
        status__in=[RunBranchStatus.PENDING, RunBranchStatus.RUNNING],
    ).update(
        status=RunBranchStatus.CANCELLED,
        reason_code=(reason_code or "WORKFLOW_JOIN_CLOSED")[:64],
        finished_at=now,
        delivery_token=None,
        delivery_expires_at=None,
        claim_expires_at=None,
    )
    append_locked_run_event(
        run=run,
        event_type=RunEventType.JOIN_CLOSED,
        node_id=join.join_node_id,
        outcome=str(join.status),
        reason_code=reason_code,
        state_checksum=compute_checksum(join.merged_state)
        if status == RunJoinStatus.SUCCEEDED
        else "",
        payload={
            "succeeded_count": len(succeeded),
            "failed_count": len(failed),
            "cancelled_count": len(cancelled),
        },
    )
    run.save(update_fields=["next_event_sequence", "updated_at"])


def _expire_running_branches(
    *, run: Run, join: RunJoin, branches: list[RunBranch], now: datetime
) -> bool:
    """Make an abandoned branch attempt a durable failure before admitting more work."""

    expired = False
    for branch in branches:
        if (
            branch.status == RunBranchStatus.RUNNING
            and branch.claim_expires_at is not None
            and branch.claim_expires_at <= now
        ):
            branch.status = RunBranchStatus.FAILED
            branch.reason_code = "WORKFLOW_BRANCH_RECOVERY_REQUIRED"
            branch.finished_at = now
            _clear_delivery(branch)
            branch.save(
                update_fields=[
                    "status",
                    "reason_code",
                    "finished_at",
                    "delivery_token",
                    "delivery_expires_at",
                    "claim_expires_at",
                    "updated_at",
                ]
            )
            expired = True
    return expired


def _evaluate_run_join(
    run: Run,
    join: RunJoin,
    *,
    now: datetime | None = None,
    branches: list[RunBranch] | None = None,
) -> bool:
    """Close a join only when its immutable policy has a final outcome.

    Callers hold the Run and join locks. The branch row lock is taken here (or supplied by the
    caller) so a concurrent completion cannot observe an intermediate terminal decision.
    """

    if join.status != RunJoinStatus.OPEN:
        return False
    closed_at = now or timezone.now()
    locked_branches = branches
    if locked_branches is None:
        locked_branches = list(
            RunBranch.objects.select_for_update().filter(
                run=run, region_node_id=join.region_node_id
            )
        )
    succeeded = [item for item in locked_branches if item.status == RunBranchStatus.SUCCEEDED]
    failed = [item for item in locked_branches if item.status == RunBranchStatus.FAILED]
    cancelled = [item for item in locked_branches if item.status == RunBranchStatus.CANCELLED]
    outstanding = len(locked_branches) - len(succeeded) - len(failed) - len(cancelled)
    deadline_exceeded = closed_at >= join.deadline_at
    should_succeed = not deadline_exceeded and len(succeeded) >= join.required_count
    should_fail = (
        deadline_exceeded
        or (join.mode == "fail_fast" and bool(failed or cancelled))
        or len(succeeded) + outstanding < join.required_count
    )
    if not should_succeed and not should_fail:
        return False
    reason_code = ""
    if should_succeed:
        try:
            join.merged_state = _merged_branch_state(run, join, succeeded)
        except RunParallelError as exc:
            should_succeed = False
            reason_code = exc.code
    if not should_succeed:
        reason_code = reason_code or (
            "WORKFLOW_PARALLEL_DEADLINE_EXCEEDED" if deadline_exceeded else "WORKFLOW_JOIN_FAILED"
        )
    _close_run_join(
        run=run,
        join=join,
        status=RunJoinStatus.SUCCEEDED if should_succeed else RunJoinStatus.FAILED,
        reason_code=reason_code,
        succeeded=succeeded,
        failed=failed,
        cancelled=cancelled,
        now=closed_at,
    )
    return True


@transaction.atomic
def claim_run_branch(
    *, organization_id: int, branch_id: uuid.UUID, delivery_token: uuid.UUID
) -> str:
    """Claim an admitted branch only with its exact, unexpired delivery capability."""

    if not isinstance(delivery_token, uuid.UUID):
        raise RunParallelError("WORKFLOW_BRANCH_DELIVERY_INVALID")
    set_tenant_context(organization_id)
    locator = RunBranch.objects.only("run_id", "region_node_id").get(
        pk=branch_id, organization_id=organization_id
    )
    # All parallel transitions take locks in Run -> RunJoin -> RunBranch order.
    run = (
        Run.objects.select_for_update()
        .select_related("workflow_version")
        .get(pk=locator.run_id, organization_id=organization_id)
    )
    join = RunJoin.objects.select_for_update().get(
        run=run, region_node_id=locator.region_node_id, organization_id=organization_id
    )
    branch = RunBranch.objects.select_for_update().get(
        pk=branch_id, organization_id=organization_id
    )
    now = timezone.now()
    if branch.status in {RunBranchStatus.SUCCEEDED, RunBranchStatus.FAILED}:
        return "duplicate" if branch.delivery_token == delivery_token else "stale"
    if run.status in RUN_TERMINAL_STATUSES or join.status != RunJoinStatus.OPEN:
        return "terminal"
    if run.cancellation_state == RunCancellationState.REQUESTED:
        _cancel_locked_run_parallel_work(run=run, now=now)
        return "terminal"
    if _evaluate_run_join(run, join, now=now):
        return "terminal"
    if branch.status == RunBranchStatus.CANCELLED:
        return "terminal"
    if branch.status == RunBranchStatus.RUNNING:
        return "duplicate" if branch.delivery_token == delivery_token else "stale"
    if (
        branch.delivery_token != delivery_token
        or branch.delivery_expires_at is None
        or branch.delivery_expires_at <= now
    ):
        return "stale"
    if branch.attempt_count >= MAX_RUN_BRANCH_ATTEMPTS:
        branch.status = RunBranchStatus.FAILED
        branch.reason_code = "WORKFLOW_BUDGET_EXCEEDED"
        branch.finished_at = now
        _clear_delivery(branch)
        branch.save(
            update_fields=[
                "status",
                "reason_code",
                "finished_at",
                "delivery_token",
                "delivery_expires_at",
                "claim_expires_at",
                "updated_at",
            ]
        )
        _evaluate_run_join(run, join, now=now)
        return "budget_exhausted"
    branch.status = RunBranchStatus.RUNNING
    branch.attempt_count += 1
    branch.started_at = branch.started_at or now
    branch.delivery_expires_at = None
    branch.claim_expires_at = min(
        join.deadline_at, now + timedelta(seconds=BRANCH_CLAIM_LEASE_SECONDS)
    )
    branch.save(
        update_fields=[
            "status",
            "attempt_count",
            "started_at",
            "delivery_expires_at",
            "claim_expires_at",
            "updated_at",
        ]
    )
    return "claimed"


@transaction.atomic
def renew_run_branch_claim(
    *, organization_id: int, branch_id: uuid.UUID, delivery_token: uuid.UUID
) -> None:
    """Extend a live branch claim only at a worker's safe node boundary.

    The exact delivery capability remains the authority throughout execution.  A
    branch can contain multiple bounded nodes, so its original claim lease must
    not make an otherwise healthy worker look lost between those nodes.
    """

    if not isinstance(delivery_token, uuid.UUID):
        raise RunParallelError("WORKFLOW_BRANCH_DELIVERY_INVALID")
    set_tenant_context(organization_id)
    locator = RunBranch.objects.only("run_id", "region_node_id").get(
        pk=branch_id, organization_id=organization_id
    )
    # Keep the same Run -> RunJoin -> RunBranch lock order as claim/completion.
    run = Run.objects.select_for_update().get(pk=locator.run_id, organization_id=organization_id)
    join = RunJoin.objects.select_for_update().get(
        run=run, region_node_id=locator.region_node_id, organization_id=organization_id
    )
    branch = RunBranch.objects.select_for_update().get(
        pk=branch_id, organization_id=organization_id
    )
    now = timezone.now()
    if (
        run.status in RUN_TERMINAL_STATUSES
        or run.cancellation_state == RunCancellationState.REQUESTED
        or join.status != RunJoinStatus.OPEN
        or branch.status != RunBranchStatus.RUNNING
        or branch.delivery_token != delivery_token
        or branch.claim_expires_at is None
        or branch.claim_expires_at <= now
    ):
        raise RunParallelError("WORKFLOW_BRANCH_CLAIM_INVALID")
    renewed_until = min(join.deadline_at, now + timedelta(seconds=BRANCH_CLAIM_LEASE_SECONDS))
    if renewed_until <= now:
        # Do not grant a claim at or after the region's immutable deadline.
        _evaluate_run_join(run, join, now=now)
        raise RunParallelError("WORKFLOW_BRANCH_CLAIM_INVALID")
    branch.claim_expires_at = renewed_until
    branch.save(update_fields=["claim_expires_at", "updated_at"])


@transaction.atomic
def complete_run_branch(
    *,
    organization_id: int,
    branch_id: uuid.UUID,
    delivery_token: uuid.UUID,
    idempotency_key: str,
    result_state: Any = None,
    reason_code: str = "",
) -> RunBranchTransition:
    """Record an exact branch attempt outcome and re-evaluate its locked join."""

    if not isinstance(delivery_token, uuid.UUID):
        raise RunParallelError("WORKFLOW_BRANCH_DELIVERY_INVALID")
    set_tenant_context(organization_id)
    locator = RunBranch.objects.only("run_id", "region_node_id").get(
        pk=branch_id, organization_id=organization_id
    )
    run = (
        Run.objects.select_for_update()
        .select_related("workflow_version")
        .get(pk=locator.run_id, organization_id=organization_id)
    )
    join = RunJoin.objects.select_for_update().get(
        run=run, region_node_id=locator.region_node_id, organization_id=organization_id
    )
    branch = RunBranch.objects.select_for_update().get(
        pk=branch_id, organization_id=organization_id
    )
    now = timezone.now()
    if branch.delivery_token != delivery_token:
        return RunBranchTransition("stale", str(join.status))
    if branch.status in {RunBranchStatus.SUCCEEDED, RunBranchStatus.FAILED}:
        return RunBranchTransition("duplicate", str(join.status))
    if run.status in RUN_TERMINAL_STATUSES or join.status != RunJoinStatus.OPEN:
        return RunBranchTransition("late", str(join.status))
    if run.cancellation_state == RunCancellationState.REQUESTED:
        _cancel_locked_run_parallel_work(run=run, now=now)
        return RunBranchTransition("late", str(join.status))
    if _evaluate_run_join(run, join, now=now):
        return RunBranchTransition("late", str(join.status))
    if branch.status != RunBranchStatus.RUNNING:
        raise RunParallelError("WORKFLOW_BRANCH_STATE_INVALID")
    if branch.claim_expires_at is None or branch.claim_expires_at <= now:
        return RunBranchTransition("stale", str(join.status))
    result = deepcopy(result_state if result_state is not None else {})
    if _json_size(result) > min(MAX_BRANCH_STATE_BYTES, join.max_state_bytes):
        reason_code = "WORKFLOW_BUDGET_EXCEEDED"
    branch.status = RunBranchStatus.FAILED if reason_code else RunBranchStatus.SUCCEEDED
    branch.result_state = {} if reason_code else result
    branch.result_checksum = compute_checksum(branch.result_state)
    branch.idempotency_key = idempotency_key[:128]
    branch.reason_code = reason_code[:64]
    branch.finished_at = now
    branch.delivery_expires_at = None
    branch.claim_expires_at = None
    branch.save(
        update_fields=[
            "status",
            "result_state",
            "result_checksum",
            "idempotency_key",
            "reason_code",
            "finished_at",
            "delivery_expires_at",
            "claim_expires_at",
            "updated_at",
        ]
    )
    _evaluate_run_join(run, join, now=now)
    return RunBranchTransition("committed", str(join.status))


def _merged_branch_state(run: Run, join: RunJoin, succeeded: list[RunBranch]) -> dict[str, Any]:
    """Project the succeeded branch results through the authored join merge mapping."""

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
    if _json_size(branch_state) > join.max_state_bytes:
        raise RunParallelError("WORKFLOW_BUDGET_EXCEEDED")
    try:
        merged = apply_output_mapping(_business_state(run), branch_state, node["config"]["merge"])
    except MappingError as exc:
        raise RunParallelError(exc.code) from None
    if _json_size(merged) > join.max_state_bytes:
        raise RunParallelError("WORKFLOW_BUDGET_EXCEEDED")
    return merged


def _cancel_locked_run_parallel_work(*, run: Run, now: datetime) -> int:
    """Revoke unfinished branch capabilities while the caller owns the Run lock."""

    joins = list(
        RunJoin.objects.select_for_update()
        .filter(run=run, status=RunJoinStatus.OPEN)
        .order_by("created_at", "id")
    )
    cancelled_count = 0
    for join in joins:
        branches = list(
            RunBranch.objects.select_for_update()
            .filter(run=run, region_node_id=join.region_node_id)
            .order_by("created_at", "id")
        )
        succeeded = [item for item in branches if item.status == RunBranchStatus.SUCCEEDED]
        failed = [item for item in branches if item.status == RunBranchStatus.FAILED]
        cancelled = [item for item in branches if item.status == RunBranchStatus.CANCELLED]
        cancelled_count += sum(
            item.status in {RunBranchStatus.PENDING, RunBranchStatus.RUNNING} for item in branches
        )
        _close_run_join(
            run=run,
            join=join,
            status=RunJoinStatus.CANCELLED,
            reason_code="RUN_CANCELLATION_REQUESTED",
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
            now=now,
        )
    return cancelled_count


def _admit_locked_run_branch_deliveries(
    *, run: Run, join: RunJoin, branches: list[RunBranch], now: datetime, limit: int
) -> tuple[RunBranchDelivery, ...]:
    """Reserve only the available branch slots; publication happens after commit."""

    if join.status != RunJoinStatus.OPEN:
        return ()
    _expire_running_branches(run=run, join=join, branches=branches, now=now)
    if _evaluate_run_join(run, join, now=now, branches=branches):
        return ()
    for branch in branches:
        if (
            branch.status == RunBranchStatus.PENDING
            and branch.delivery_expires_at is not None
            and branch.delivery_expires_at <= now
        ):
            _clear_delivery(branch)
            branch.save(
                update_fields=[
                    "delivery_token",
                    "delivery_expires_at",
                    "claim_expires_at",
                    "updated_at",
                ]
            )
    running = sum(item.status == RunBranchStatus.RUNNING for item in branches)
    reserved = sum(
        item.status == RunBranchStatus.PENDING
        and item.delivery_token is not None
        and item.delivery_expires_at is not None
        and item.delivery_expires_at > now
        for item in branches
    )
    slots = min(limit, max(0, join.max_concurrency - running - reserved))
    if not slots:
        return ()
    expires_at = min(join.deadline_at, now + timedelta(seconds=BRANCH_DELIVERY_LEASE_SECONDS))
    deliveries: list[RunBranchDelivery] = []
    for branch in branches:
        if slots == 0:
            break
        if branch.status != RunBranchStatus.PENDING or branch.delivery_token is not None:
            continue
        token = uuid.uuid4()
        branch.delivery_token = token
        branch.delivery_expires_at = expires_at
        branch.save(update_fields=["delivery_token", "delivery_expires_at", "updated_at"])
        deliveries.append(
            RunBranchDelivery(
                branch_id=branch.id,
                delivery_token=token,
                organization_id=run.organization_id,
            )
        )
        slots -= 1
    return tuple(deliveries)


@transaction.atomic
def admit_run_branch_deliveries(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    region_node_id: str,
    limit: int = 100,
) -> tuple[RunBranchDelivery, ...]:
    """Durably reserve bounded branch deliveries for one region."""

    if not 1 <= limit <= 100:
        raise RunParallelError("WORKFLOW_BUDGET_EXCEEDED")
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    join = RunJoin.objects.select_for_update().get(
        run=run, region_node_id=region_node_id, organization_id=organization_id
    )
    now = timezone.now()
    if (
        run.status in RUN_TERMINAL_STATUSES
        or run.cancellation_state == RunCancellationState.REQUESTED
    ):
        if run.cancellation_state == RunCancellationState.REQUESTED:
            _cancel_locked_run_parallel_work(run=run, now=now)
        return ()
    branches = list(
        RunBranch.objects.select_for_update()
        .filter(run=run, region_node_id=region_node_id)
        .order_by("branch_name", "item_ordinal", "id")
    )
    return _admit_locked_run_branch_deliveries(
        run=run, join=join, branches=branches, now=now, limit=limit
    )


@transaction.atomic
def cancel_run_parallel_work(*, organization_id: int, run_id: uuid.UUID) -> int:
    """Stop every unfinished branch of a converging Run without reopening closed joins."""

    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    return _cancel_locked_run_parallel_work(run=run, now=timezone.now())


@transaction.atomic
def _reconcile_run_region(
    *, organization_id: int, run_id: uuid.UUID, region_node_id: str, limit: int
) -> tuple[tuple[RunBranchDelivery, ...], bool]:
    """Recover one region after a missed delivery or lost worker attempt."""

    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    join = RunJoin.objects.select_for_update().get(
        run=run, region_node_id=region_node_id, organization_id=organization_id
    )
    was_open = join.status == RunJoinStatus.OPEN
    now = timezone.now()
    if (
        run.status in RUN_TERMINAL_STATUSES
        or run.cancellation_state == RunCancellationState.REQUESTED
    ):
        if run.cancellation_state == RunCancellationState.REQUESTED:
            _cancel_locked_run_parallel_work(run=run, now=now)
        return (), False
    branches = list(
        RunBranch.objects.select_for_update()
        .filter(run=run, region_node_id=region_node_id)
        .order_by("branch_name", "item_ordinal", "id")
    )
    deliveries = _admit_locked_run_branch_deliveries(
        run=run, join=join, branches=branches, now=now, limit=limit
    )
    return deliveries, was_open and join.status != RunJoinStatus.OPEN


def reconcile_run_parallel_work(
    *, organization_id: int, limit: int = 100
) -> RunParallelReconciliation:
    """Boundedly repair expired reservations, worker loss and elapsed region deadlines."""

    if not 1 <= limit <= 100:
        raise RunParallelError("WORKFLOW_BUDGET_EXCEEDED")
    with transaction.atomic():
        set_tenant_context(organization_id)
        candidates = list(
            RunJoin.objects.filter(organization_id=organization_id, status=RunJoinStatus.OPEN)
            .order_by("deadline_at", "created_at", "id")
            .values_list("run_id", "region_node_id")[:limit]
        )
    deliveries: list[RunBranchDelivery] = []
    closed_regions: list[tuple[uuid.UUID, str]] = []
    for run_id, region_node_id in candidates:
        remaining = limit - len(deliveries)
        if remaining <= 0:
            break
        try:
            admitted, closed = _reconcile_run_region(
                organization_id=organization_id,
                run_id=run_id,
                region_node_id=region_node_id,
                limit=remaining,
            )
        except (Run.DoesNotExist, RunJoin.DoesNotExist):
            continue
        deliveries.extend(admitted)
        if closed:
            closed_regions.append((run_id, region_node_id))
    return RunParallelReconciliation(tuple(deliveries), tuple(closed_regions), len(candidates))
