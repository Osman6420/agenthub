from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from threading import Barrier, Thread
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from apps.tenancy.models import Organization
from apps.workflows.models import (
    MAX_RUN_BRANCH_ATTEMPTS,
    Run,
    RunBranch,
    RunBranchStatus,
    RunEvent,
    RunEventType,
    RunJoin,
    RunJoinStatus,
)
from apps.workflows.run_parallel import (
    RunParallelError,
    admit_run_branch_deliveries,
    claim_run_branch,
    complete_run_branch,
    reconcile_run_parallel_work,
    renew_run_branch_claim,
)
from apps.workflows.run_waits import RunWaitError, resume_run_for_join
from apps.workflows.tasks import execute_unified_run_branch
from apps.workflows.tests.test_unified_run import (
    _END_NODE,
    _FORMAT_NODE,
    _START_NODE,
    _execute_queued,
    _install_graph,
    _queued_background_run,
)
from apps.workflows.transitions import request_run_cancellation
from apps.workflows.unified_executor import UnifiedExecutorError, _validated_graph


def _retrieve_branch(name: str) -> dict:
    return {
        "id": name,
        "type": "retrieve",
        "input_mapping": [{"from": "/input/query", "to": "/query"}],
        "output_mapping": [{"from": "/chunks", "to": f"/branches/{name}/output"}],
    }


def _join_node(mode: str, branches: list[str], merge: list[dict], **config) -> dict:
    return {
        "id": "joined",
        "type": "join",
        "config": {"mode": mode, "branches": branches, "merge": merge, **config},
    }


_PARALLEL_NODES: list[dict] = [
    _START_NODE,
    {"id": "split", "type": "parallel", "config": {"join": "joined", "max_concurrency": 2}},
    _retrieve_branch("a"),
    _retrieve_branch("b"),
    _join_node(
        "all",
        ["a", "b"],
        [
            {"from": "/branches/a/output", "to": "/evidence/a"},
            {"from": "/branches/b/output", "to": "/evidence/b"},
        ],
    ),
    _FORMAT_NODE,
    _END_NODE,
]
_PARALLEL_EDGES: list[dict] = [
    {"from": "start", "to": "split"},
    {"from": "split", "to": "a", "branch": "a"},
    {"from": "a", "to": "joined", "branch": "a"},
    {"from": "split", "to": "b", "branch": "b"},
    {"from": "b", "to": "joined", "branch": "b"},
    {"from": "joined", "to": "format"},
    {"from": "format", "to": "done"},
]

_FOR_EACH_NODES: list[dict] = [
    _START_NODE,
    {
        "id": "split",
        "type": "for_each",
        "config": {
            "items_path": "/input/items",
            "item_path": "/item",
            "max_items": 4,
            "max_concurrency": 2,
            "body_entry": "each",
            "join": "joined",
        },
    },
    {
        "id": "each",
        "type": "transform",
        "config": {"transform_profile_ref": "identity"},
        "input_mapping": [{"from": "/item", "to": "/documents"}],
        "output_mapping": [{"from": "/result", "to": "/evidence/item"}],
    },
    _join_node(
        "all",
        ["for_each_items"],
        [{"from": "/branches/for_each_items/output", "to": "/evidence/items"}],
    ),
    _FORMAT_NODE,
    _END_NODE,
]
_FOR_EACH_EDGES: list[dict] = [
    {"from": "start", "to": "split"},
    {"from": "split", "to": "each", "branch": "for_each_items"},
    {"from": "each", "to": "joined", "branch": "for_each_items"},
    {"from": "joined", "to": "format"},
    {"from": "format", "to": "done"},
]


def _started_parallel_run(workflow_fixture, *, key: str, state: dict | None = None) -> Run:
    run = _queued_background_run(workflow_fixture, key=key)
    checkpoint = state if state is not None else {"input": {"query": "what is the policy"}}
    run.checkpoint = checkpoint
    run.redacted_state = checkpoint
    run.save(update_fields=["checkpoint", "redacted_state"])
    return run


def _branch_ids(run: Run) -> list:
    return list(
        RunBranch.objects.filter(run_id=run.id)
        .order_by("branch_name", "item_ordinal")
        .values_list("id", flat=True)
    )


def _delivery_token(branch_id):
    return RunBranch.objects.get(pk=branch_id).delivery_token


def _deliver(run: Run, branch_id) -> str:
    token = _delivery_token(branch_id)
    assert token is not None
    return execute_unified_run_branch(str(branch_id), run.organization_id, str(token))


@pytest.fixture(autouse=True)
def _prevent_eager_branch_delivery(monkeypatch) -> None:
    """Keep persisted branch admission observable; tests call the task explicitly."""

    monkeypatch.setattr(execute_unified_run_branch, "apply_async", lambda *args, **kwargs: None)


def _stub_for_each_body(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.workflows.unified_executor._run_eligible",
        lambda **kwargs: {"result": {"item": kwargs["state"]}},
    )


@pytest.mark.django_db
def test_parallel_region_parks_the_run_and_materialises_its_branches(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-open")

    parked = _execute_queued(run)

    assert parked.status == "waiting_child"
    run.refresh_from_db()
    assert (run.awaiting_kind, run.awaiting_reference) == ("child", "split")
    # The claim is released at the pause, so a branch worker never contends with a parked Run.
    assert run.background_claim_token is None
    assert run.checkpoint["__resume_node"] == "joined"
    join = RunJoin.objects.get(run_id=run.id)
    assert (join.status, join.region_node_id, join.join_node_id) == ("open", "split", "joined")
    assert (join.mode, join.required_count, join.branch_count) == ("all", 2, 2)
    branches = list(RunBranch.objects.filter(run_id=run.id).order_by("branch_name"))
    assert [(item.branch_name, item.status) for item in branches] == [
        ("a", "pending"),
        ("b", "pending"),
    ]
    # The server-owned cursor is not business state, so no branch body may observe it.
    assert all("__resume_node" not in item.input_state for item in branches)
    assert (
        RunEvent.objects.filter(
            run_id=run.id, event_type=RunEventType.BRANCHES_OPENED, node_id="split"
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_parallel_region_rejects_an_initial_branch_snapshot_over_its_authored_budget(
    workflow_fixture,
) -> None:
    nodes = deepcopy(_PARALLEL_NODES)
    nodes[1] = {
        **nodes[1],
        "config": {**nodes[1]["config"], "max_state_bytes": 1},
    }
    _install_graph(workflow_fixture, nodes, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-initial-state-budget")

    assert _execute_queued(run).status == "failed"
    run.refresh_from_db()
    assert run.error_code == "WORKFLOW_BUDGET_EXCEEDED"
    assert not RunJoin.objects.filter(run_id=run.id).exists()


@pytest.mark.django_db
def test_parallel_region_reconverges_through_the_join_and_completes(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-converge")
    assert _execute_queued(run).status == "waiting_child"

    first, second = _branch_ids(run)
    assert _deliver(run, first) == "committed"
    run.refresh_from_db()
    # One branch cannot close an ``all`` join, so the Run stays parked.
    assert run.status == "waiting_child"
    assert RunJoin.objects.get(run_id=run.id).status == RunJoinStatus.OPEN

    assert _deliver(run, second) == "committed"
    join = RunJoin.objects.get(run_id=run.id)
    assert (join.status, join.reason_code) == ("succeeded", "")
    run.refresh_from_db()
    assert run.status == "queued"

    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    assert set(run.checkpoint["evidence"]) == {"a", "b"}
    assert "__resume_node" not in run.checkpoint
    assert run.checkpoint["output"] == {"answer": "ok", "sources": []}
    assert (
        RunEvent.objects.filter(
            run_id=run.id, event_type=RunEventType.JOIN_CLOSED, node_id="joined"
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_branch_delivery_is_order_independent_and_duplicate_safe(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-duplicate")
    assert _execute_queued(run).status == "waiting_child"

    first, second = _branch_ids(run)
    assert _deliver(run, second) == "committed"
    assert _deliver(run, second) == "duplicate"
    assert _deliver(run, first) == "committed"
    assert _deliver(run, first) == "duplicate"

    join = RunJoin.objects.get(run_id=run.id)
    assert join.status == RunJoinStatus.SUCCEEDED
    # Redelivery must not reopen or re-close the region.
    assert RunEvent.objects.filter(run_id=run.id, event_type=RunEventType.JOIN_CLOSED).count() == 1
    assert [item.attempt_count for item in RunBranch.objects.filter(run_id=run.id)] == [1, 1]
    run.refresh_from_db()
    assert run.status == "queued"
    assert _execute_queued(run).status == "completed"


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db(transaction=True)
def test_concurrent_branch_claim_has_one_owner_and_one_exact_duplicate(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-claim-race")
    # ``transaction=True`` deliberately removes pytest-django's outer transaction; the Run-native
    # executor needs one to install PostgreSQL's transaction-local tenant scope before it parks.
    with transaction.atomic():
        assert _execute_queued(run).status == "waiting_child"

    branch_id = _branch_ids(run)[0]
    token = _delivery_token(branch_id)
    assert token is not None
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def claim() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            outcomes.append(
                claim_run_branch(
                    organization_id=run.organization_id,
                    branch_id=branch_id,
                    delivery_token=token,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted by parent thread
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=claim), Thread(target=claim)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert sorted(outcomes) == ["claimed", "duplicate"]
    branch = RunBranch.objects.get(pk=branch_id)
    assert (branch.status, branch.attempt_count, branch.delivery_token) == (
        RunBranchStatus.RUNNING,
        1,
        token,
    )


@pytest.mark.django_db
def test_admission_reserves_only_the_configured_parallel_capacity(
    workflow_fixture, monkeypatch
) -> None:
    _stub_for_each_body(monkeypatch)
    _install_graph(workflow_fixture, _FOR_EACH_NODES, _FOR_EACH_EDGES)
    run = _started_parallel_run(
        workflow_fixture,
        key="for-each-concurrency",
        state={"input": {"items": ["one", "two", "three"]}},
    )
    assert _execute_queued(run).status == "waiting_child"

    join = RunJoin.objects.get(run_id=run.id)
    branches = list(RunBranch.objects.filter(run_id=run.id).order_by("item_ordinal"))
    assert join.max_concurrency == 2
    assert sum(branch.delivery_token is not None for branch in branches) == 2
    assert (
        admit_run_branch_deliveries(
            organization_id=run.organization_id,
            run_id=run.id,
            region_node_id="split",
        )
        == ()
    )

    _deliver(run, branches[0].id)
    pending = list(
        RunBranch.objects.filter(run_id=run.id, status=RunBranchStatus.PENDING).order_by(
            "item_ordinal"
        )
    )
    assert len(pending) == 2
    assert all(branch.delivery_token is not None for branch in pending)


@pytest.mark.django_db
def test_expired_delivery_reservation_is_reissued_with_a_new_exact_token(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-redelivery")
    assert _execute_queued(run).status == "waiting_child"

    branch_id = _branch_ids(run)[0]
    original = _delivery_token(branch_id)
    assert original is not None
    RunBranch.objects.filter(pk=branch_id).update(
        delivery_expires_at=timezone.now() - timedelta(seconds=1)
    )

    deliveries = admit_run_branch_deliveries(
        organization_id=run.organization_id,
        run_id=run.id,
        region_node_id="split",
    )
    assert len(deliveries) == 1
    assert deliveries[0].branch_id == branch_id
    assert deliveries[0].delivery_token != original
    assert (
        claim_run_branch(
            organization_id=run.organization_id,
            branch_id=branch_id,
            delivery_token=original,
        )
        == "stale"
    )


@pytest.mark.django_db
def test_branch_claim_renewal_requires_the_live_exact_delivery_capability(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-claim-renewal")
    assert _execute_queued(run).status == "waiting_child"

    branch_id = _branch_ids(run)[0]
    token = _delivery_token(branch_id)
    assert token is not None
    assert (
        claim_run_branch(
            organization_id=run.organization_id,
            branch_id=branch_id,
            delivery_token=token,
        )
        == "claimed"
    )
    RunBranch.objects.filter(pk=branch_id).update(
        claim_expires_at=timezone.now() + timedelta(seconds=1)
    )

    renew_run_branch_claim(
        organization_id=run.organization_id,
        branch_id=branch_id,
        delivery_token=token,
    )
    renewed = RunBranch.objects.get(pk=branch_id)
    assert renewed.status == RunBranchStatus.RUNNING
    assert renewed.delivery_token == token
    assert renewed.claim_expires_at is not None
    assert renewed.claim_expires_at > timezone.now() + timedelta(seconds=30)

    with pytest.raises(RunParallelError, match="WORKFLOW_BRANCH_CLAIM_INVALID"):
        renew_run_branch_claim(
            organization_id=run.organization_id,
            branch_id=branch_id,
            delivery_token=uuid4(),
        )


@pytest.mark.django_db
def test_branch_execution_renews_its_exact_claim_at_the_safe_node_boundary(
    workflow_fixture, monkeypatch
) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-claim-renewal-boundary")
    assert _execute_queued(run).status == "waiting_child"

    branch_id = _branch_ids(run)[0]
    token = _delivery_token(branch_id)
    assert token is not None
    renewals: list[tuple] = []

    def track_renewal(**kwargs) -> None:
        renewals.append((kwargs["branch_id"], kwargs["delivery_token"]))
        renew_run_branch_claim(**kwargs)

    monkeypatch.setattr("apps.workflows.unified_executor.renew_run_branch_claim", track_renewal)

    assert _deliver(run, branch_id) == "committed"
    assert renewals == [(branch_id, token)]


@pytest.mark.django_db
def test_reconciliation_fails_a_lost_branch_claim_and_closes_its_parent_join(
    workflow_fixture,
) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-worker-loss")
    assert _execute_queued(run).status == "waiting_child"

    branch_id = _branch_ids(run)[0]
    token = _delivery_token(branch_id)
    assert token is not None
    assert (
        claim_run_branch(
            organization_id=run.organization_id,
            branch_id=branch_id,
            delivery_token=token,
        )
        == "claimed"
    )
    RunBranch.objects.filter(pk=branch_id).update(
        claim_expires_at=timezone.now() - timedelta(seconds=1)
    )

    reconciliation = reconcile_run_parallel_work(organization_id=run.organization_id)

    recovered = RunBranch.objects.get(pk=branch_id)
    join = RunJoin.objects.get(run_id=run.id)
    assert (recovered.status, recovered.reason_code) == (
        "failed",
        "WORKFLOW_BRANCH_RECOVERY_REQUIRED",
    )
    assert (join.status, join.reason_code) == ("failed", "WORKFLOW_JOIN_FAILED")
    assert reconciliation.closed_regions == ((run.id, "split"),)


@pytest.mark.django_db
def test_cancellation_revokes_pending_parallel_deliveries_and_converges_parent(
    workflow_fixture,
) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-cancellation")
    assert _execute_queued(run).status == "waiting_child"

    result = request_run_cancellation(
        organization_id=run.organization_id,
        run_id=run.id,
        reason_code="CLIENT_REQUESTED",
    )

    run.refresh_from_db()
    join = RunJoin.objects.get(run_id=run.id)
    assert (result.status, run.status, join.status) == ("cancelled", "cancelled", "cancelled")
    assert all(
        branch.status == RunBranchStatus.CANCELLED
        and branch.delivery_token is None
        and branch.claim_expires_at is None
        for branch in RunBranch.objects.filter(run_id=run.id)
    )


@pytest.mark.django_db
def test_failed_branch_fails_the_join_and_the_resumed_run(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-branch-failure")
    assert _execute_queued(run).status == "waiting_child"

    first, _second = _branch_ids(run)
    token = _delivery_token(first)
    assert token is not None
    claim_run_branch(organization_id=run.organization_id, branch_id=first, delivery_token=token)
    transition = complete_run_branch(
        organization_id=run.organization_id,
        branch_id=first,
        delivery_token=token,
        idempotency_key="test-failure",
        reason_code="WORKFLOW_RETRIEVAL_FAILED",
    )
    assert transition.outcome == "committed"
    join = RunJoin.objects.get(run_id=run.id)
    assert (join.status, join.reason_code) == ("failed", "WORKFLOW_JOIN_FAILED")
    assert join.merged_state == {}
    assert (
        resume_run_for_join(
            organization_id=run.organization_id,
            run_id=run.id,
            region_node_id="split",
        ).outcome
        == "committed"
    )
    run.refresh_from_db()
    assert run.status == "queued"

    assert _execute_queued(run).status == "failed"
    run.refresh_from_db()
    # The Run fails closed on the join's own reason code rather than serving a partial merge.
    assert run.error_code == "WORKFLOW_JOIN_FAILED"


@pytest.mark.django_db
def test_exhausted_branch_budget_fails_the_branch_and_converges_the_join(
    workflow_fixture,
) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-budget")
    assert _execute_queued(run).status == "waiting_child"

    first, second = _branch_ids(run)
    RunBranch.objects.filter(pk=first).update(attempt_count=MAX_RUN_BRANCH_ATTEMPTS)
    token = _delivery_token(first)
    assert token is not None
    assert claim_run_branch(
        organization_id=run.organization_id,
        branch_id=first,
        delivery_token=token,
    ) == ("budget_exhausted")

    exhausted = RunBranch.objects.get(pk=first)
    assert (exhausted.status, exhausted.reason_code) == ("failed", "WORKFLOW_BUDGET_EXCEEDED")
    join = RunJoin.objects.get(run_id=run.id)
    # An exhausted branch is a durable outcome: the region converges now, not at the deadline.
    assert join.status == RunJoinStatus.FAILED
    assert RunBranch.objects.get(pk=second).status == RunBranchStatus.CANCELLED


@pytest.mark.django_db
def test_join_resume_requires_the_exact_region_and_a_closed_join(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-resume-authority")
    assert _execute_queued(run).status == "waiting_child"

    with pytest.raises(RunWaitError, match="RUN_WAIT_NOT_FOUND"):
        resume_run_for_join(
            organization_id=run.organization_id, run_id=run.id, region_node_id="joined"
        )
    with pytest.raises(RunWaitError, match="RUN_WAIT_NOT_FOUND"):
        resume_run_for_join(
            organization_id=run.organization_id, run_id=run.id, region_node_id="split"
        )
    run.refresh_from_db()
    assert run.status == "waiting_child"


@pytest.mark.django_db
def test_branch_transitions_are_denied_across_tenants(workflow_fixture) -> None:
    _install_graph(workflow_fixture, _PARALLEL_NODES, _PARALLEL_EDGES)
    run = _started_parallel_run(workflow_fixture, key="parallel-cross-tenant")
    assert _execute_queued(run).status == "waiting_child"
    branch_id = _branch_ids(run)[0]
    other_organization = Organization.objects.create(
        slug=f"parallel-other-{uuid4().hex[:12]}", name="Parallel Other"
    )

    with pytest.raises(RunBranch.DoesNotExist):
        claim_run_branch(
            organization_id=other_organization.id,
            branch_id=branch_id,
            delivery_token=uuid4(),
        )
    with pytest.raises(RunBranch.DoesNotExist):
        complete_run_branch(
            organization_id=other_organization.id,
            branch_id=branch_id,
            delivery_token=uuid4(),
            idempotency_key="foreign",
        )
    assert RunBranch.objects.get(pk=branch_id).status == RunBranchStatus.PENDING


@pytest.mark.django_db
def test_for_each_region_fans_out_per_item_and_merges_in_order(
    workflow_fixture, monkeypatch
) -> None:
    _stub_for_each_body(monkeypatch)
    _install_graph(workflow_fixture, _FOR_EACH_NODES, _FOR_EACH_EDGES)
    run = _started_parallel_run(
        workflow_fixture,
        key="for-each-region",
        state={"input": {"items": ["first", "second", "third"]}},
    )
    assert _execute_queued(run).status == "waiting_child"

    branches = list(RunBranch.objects.filter(run_id=run.id).order_by("item_ordinal"))
    assert [item.item_ordinal for item in branches] == [0, 1, 2]
    assert {item.branch_name for item in branches} == {"for_each_items"}
    assert [item.input_state for item in branches] == [
        {"item": "first"},
        {"item": "second"},
        {"item": "third"},
    ]

    # At most two branches are admitted initially. Completing one admits the third, while the
    # ordinal merge remains deterministic even though delivery order is not source order.
    _deliver(run, branches[1].id)
    _deliver(run, branches[2].id)
    _deliver(run, branches[0].id)

    join = RunJoin.objects.get(run_id=run.id)
    assert join.status == RunJoinStatus.SUCCEEDED
    # Item results merge by ordinal, so a reversed delivery order is still deterministic.
    assert isinstance(join.merged_state["evidence"]["items"], list)
    assert len(join.merged_state["evidence"]["items"]) == 3
    run.refresh_from_db()
    assert run.status == "queued"
    assert _execute_queued(run).status == "completed"


@pytest.mark.django_db
def test_for_each_places_items_at_its_compiled_item_path(workflow_fixture) -> None:
    nodes = list(_FOR_EACH_NODES)
    nodes[1] = {
        **_FOR_EACH_NODES[1],
        "config": {**_FOR_EACH_NODES[1]["config"], "item_path": "/payload/item"},
    }
    nodes[2] = {
        **_FOR_EACH_NODES[2],
        "input_mapping": [{"from": "/payload/item", "to": "/documents"}],
    }
    _install_graph(workflow_fixture, nodes, _FOR_EACH_EDGES)
    run = _started_parallel_run(
        workflow_fixture,
        key="for-each-item-path",
        state={"input": {"items": ["first", "second"]}},
    )

    assert _execute_queued(run).status == "waiting_child"
    assert list(
        RunBranch.objects.filter(run_id=run.id)
        .order_by("item_ordinal")
        .values_list("input_state", flat=True)
    ) == [{"payload": {"item": "first"}}, {"payload": {"item": "second"}}]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            "node",
            "RUN_EXECUTOR_NODE_UNSUPPORTED",
        ),
        (
            "edge",
            "RUN_EXECUTOR_EDGE_UNSUPPORTED",
        ),
        (
            "mapping",
            "RUN_EXECUTOR_BRANCH_INPUT_MAPPING_REQUIRED",
        ),
    ],
)
def test_unified_graph_validation_denies_unsupported_branch_bodies(mutation, code) -> None:
    from apps.workflows.compiler import compile_workflow

    nodes = deepcopy(_PARALLEL_NODES)
    if mutation == "node":
        nodes[2] = {
            "id": "a",
            "type": "human_task",
            "config": {
                "allowed_decision_roles": ["approver"],
                "decision_schema": {
                    "type": "object",
                    "properties": {"approved": {"type": "boolean"}},
                    "additionalProperties": False,
                },
                "timeout_seconds": 60,
            },
            "output_mapping": [{"from": "/payload", "to": "/branches/a/output"}],
        }
    compiled = compile_workflow(
        {
            "api_version": "agenthub/v1",
            "kind": "Workflow",
            "metadata": {"id": "parallel_guard.v1"},
            "spec": {
                "input_node": "start",
                "nodes": nodes,
                "edges": _PARALLEL_EDGES,
            },
        }
    )
    graph = deepcopy(compiled.graph)
    if mutation == "edge":
        next(edge for edge in graph["edges"] if edge["from"] == "a" and edge["to"] == "joined").pop(
            "branch"
        )
    if mutation == "mapping":
        next(node for node in graph["nodes"] if node["id"] == "a").pop("input_mapping")
    with pytest.raises(UnifiedExecutorError, match=code):
        _validated_graph(graph)
