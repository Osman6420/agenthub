from __future__ import annotations

from datetime import timedelta
from threading import Barrier, Thread
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection
from django.utils import timezone

from apps.agents.models import AgentRuntimeControl, RuntimeControlScope
from apps.agents.services import set_runtime_suspension
from apps.audit.models import AuditEvent
from apps.gateway.execution_context import issue_execution_context
from apps.identity.models import (
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tenancy.rls import inspect_rls_readiness, protected_tenant_tables
from apps.workflows.background_claims import (
    BackgroundClaimError,
    claim_background_delivery,
    claim_background_run,
    renew_background_claim,
    resolve_expired_background_claim,
)
from apps.workflows.compiler import WorkflowCompileError
from apps.workflows.models import (
    Run,
    RunBranch,
    RunCancellationState,
    RunCompensationEntry,
    RunCompensationStatus,
    RunEvent,
    RunEventType,
    RunExecutionMode,
    RunJoin,
    RunStatus,
    RunWait,
    RunWaitStatus,
    WorkflowVersion,
)
from apps.workflows.run_events import append_run_event, validate_run_event_payload
from apps.workflows.run_recovery import RunRecoveryError, resolve_run_recovery
from apps.workflows.run_waits import (
    RunWaitCreation,
    RunWaitError,
    decide_run_human_task,
    resume_run_wait,
    suspend_run_for_wait,
)
from apps.workflows.services import WorkflowRequestError, request_unified_run
from apps.workflows.tasks import (
    dispatch_unified_background_run,
    execute_unified_background_run,
)
from apps.workflows.transitions import (
    RunTransitionError,
    RunTransitionResult,
    renew_sync_lease,
    request_run_cancellation,
    resolve_expired_sync_lease,
    transition_run,
)
from apps.workflows.unified_executor import (
    UnifiedExecutorError,
    _validated_graph,
    execute_background_delivery,
    execute_claimed_bounded_run,
    service_revision,
)


def _suspended(creation: RunWaitCreation) -> tuple[UUID, UUID]:
    """Narrow a successful suspension to its resume authority."""
    assert creation.outcome == "suspended"
    assert creation.wait_id is not None
    assert creation.resume_token is not None
    return creation.wait_id, creation.resume_token


def _claimed_background_run(
    workflow_fixture,
    *,
    key: str,
) -> tuple[Run, UUID, RunTransitionResult]:
    run = _queued_background_run(workflow_fixture, key=key)
    claim_token = uuid4()
    claim = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=claim_token,
        lease_seconds=30,
    )
    started = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=claim.checkpoint_version,
        expected_status="queued",
        target_status="running",
        background_claim_token=claim_token,
    )
    run.refresh_from_db()
    return run, claim_token, started


def _run(
    workflow_fixture,
    *,
    key: str = "unified-run",
    execution_mode: str = RunExecutionMode.SYNC,
) -> Run:
    workflow_version = WorkflowVersion.objects.get(scenario=workflow_fixture.scenario)
    return Run.objects.create(
        organization=workflow_fixture.organization,
        scenario=workflow_fixture.scenario,
        release=workflow_fixture.release,
        workflow_version=workflow_version,
        consumer=workflow_fixture.consumer,
        actor_id="test-actor",
        idempotency_key=key,
        compiled_checksum=workflow_version.checksum,
        compiler_version=workflow_version.compiler_version,
        execution_mode=execution_mode,
        deadline_at=timezone.now() + timedelta(minutes=5),
        input_checksum="a" * 64,
    )


def _queued_background_run(workflow_fixture, *, key: str) -> Run:
    run = _run(
        workflow_fixture,
        key=key,
        execution_mode=RunExecutionMode.BACKGROUND,
    )
    transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=run.status,
        target_status="queued",
    )
    run.refresh_from_db()
    return run


@pytest.mark.django_db
def test_unified_run_uses_uuid_and_exact_compiler_pins(workflow_fixture) -> None:
    run = _run(workflow_fixture)

    assert run.id.version == 4
    assert run.compiled_checksum == run.workflow_version.checksum
    assert run.compiler_version == run.workflow_version.compiler_version
    assert run.next_event_sequence == 1


@pytest.mark.django_db
def test_run_rejects_incomplete_wait_and_sync_lease_contracts(workflow_fixture) -> None:
    run = _run(workflow_fixture)
    run.awaiting_kind = "event"
    with pytest.raises(ValidationError, match="kind and reference"):
        run.full_clean()

    run.awaiting_kind = ""
    run.execution_mode = RunExecutionMode.BACKGROUND
    run.sync_lease_expires_at = timezone.now() + timedelta(seconds=30)
    with pytest.raises(ValidationError, match="only synchronous"):
        run.full_clean()

    run = _run(
        workflow_fixture,
        key="invalid-background-claim",
        execution_mode=RunExecutionMode.BACKGROUND,
    )
    run.background_claim_token = uuid4()
    with pytest.raises(ValidationError, match="background claim token"):
        run.full_clean()


@pytest.mark.django_db
def test_background_claim_replay_competition_and_checkpoint_ownership(
    workflow_fixture,
) -> None:
    run = _queued_background_run(workflow_fixture, key="background-claim")
    claim_token = uuid4()
    first = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=claim_token,
        lease_seconds=30,
    )
    replay = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=claim_token,
        lease_seconds=30,
    )
    competing = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=uuid4(),
        lease_seconds=30,
    )

    assert first.outcome == "claimed"
    assert replay.outcome == "replayed"
    assert replay.claim_expires_at == first.claim_expires_at
    assert competing.outcome == "busy"
    audit = AuditEvent.objects.get(
        action="workflow.run.background_claim",
        resource_id=str(run.id),
    )
    assert audit.after == {
        "checkpoint_version": run.checkpoint_version,
        "status": "queued",
    }
    assert str(claim_token) not in str(audit.after)

    committed = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=first.checkpoint_version,
        expected_status="queued",
        target_status="running",
        background_claim_token=claim_token,
    )
    assert committed.outcome == "committed"
    run.refresh_from_db()
    assert run.background_claim_checkpoint_version == run.checkpoint_version

    with pytest.raises(BackgroundClaimError, match="RUN_BACKGROUND_CLAIM_STALE"):
        renew_background_claim(
            organization_id=run.organization_id,
            run_id=run.id,
            claim_token=claim_token,
            expected_checkpoint_version=first.checkpoint_version,
            lease_seconds=30,
        )


@pytest.mark.django_db
def test_background_claim_fails_closed_when_audit_persistence_fails(
    workflow_fixture,
    monkeypatch,
) -> None:
    run = _queued_background_run(workflow_fixture, key="background-audit-failure")

    def fail_audit(**_kwargs) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.workflows.background_claims.record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        claim_background_run(
            organization_id=run.organization_id,
            run_id=run.id,
            claim_token=uuid4(),
            lease_seconds=30,
        )
    run.refresh_from_db()
    assert run.background_claim_token is None


@pytest.mark.django_db
def test_background_delivery_is_identifier_only_and_tenant_scoped(workflow_fixture) -> None:
    run = _queued_background_run(workflow_fixture, key="background-delivery")
    token = uuid4()
    claimed = claim_background_delivery(
        body={"run_id": str(run.id), "delivery_token": str(token)},
        headers={
            "organization_id": run.organization_id,
            "service_revision": service_revision(),
        },
    )
    assert claimed.outcome == "claimed"

    with pytest.raises(BackgroundClaimError, match="RUN_BACKGROUND_DELIVERY_BODY_INVALID"):
        claim_background_delivery(
            body={
                "run_id": str(run.id),
                "delivery_token": str(uuid4()),
                "checkpoint": {"forged": True},
            },
            headers={
                "organization_id": run.organization_id,
                "service_revision": service_revision(),
            },
        )
    with pytest.raises(Run.DoesNotExist):
        claim_background_delivery(
            body={"run_id": str(run.id), "delivery_token": str(uuid4())},
            headers={
                "organization_id": run.organization_id + 99_999,
                "service_revision": service_revision(),
            },
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        (
            "compiler_version",
            "workflow-compiler/stale",
            "RUN_BACKGROUND_COMPILER_INCOMPATIBLE",
        ),
        ("compiled_checksum", "b" * 64, "RUN_BACKGROUND_CHECKSUM_MISMATCH"),
    ],
)
def test_background_claim_rejects_stale_worker_pins(
    workflow_fixture,
    field: str,
    value: str,
    error_code: str,
) -> None:
    run = _queued_background_run(workflow_fixture, key=f"background-pin-{field}")
    Run.objects.filter(pk=run.id).update(**{field: value})

    with pytest.raises(BackgroundClaimError, match=error_code):
        claim_background_run(
            organization_id=run.organization_id,
            run_id=run.id,
            claim_token=uuid4(),
            lease_seconds=30,
        )
    run.refresh_from_db()
    assert run.background_claim_token is None


@pytest.mark.django_db
def test_background_claim_and_transition_recheck_kill_switch(workflow_fixture) -> None:
    run = _queued_background_run(workflow_fixture, key="background-kill-switch")
    set_runtime_suspension(
        organization_id=run.organization_id,
        suspended=True,
        actor="test-operator",
        reason="test",
    )
    token = uuid4()
    blocked = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
        lease_seconds=30,
    )
    assert blocked.outcome == "suspended"
    run.refresh_from_db()
    assert run.background_claim_token is None

    set_runtime_suspension(
        organization_id=run.organization_id,
        suspended=False,
        actor="test-operator",
        reason="test",
    )
    claim = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
        lease_seconds=30,
    )
    transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=claim.checkpoint_version,
        expected_status="queued",
        target_status="running",
        background_claim_token=token,
    )
    set_runtime_suspension(
        organization_id=run.organization_id,
        suspended=True,
        actor="test-operator",
        reason="test",
    )
    run.refresh_from_db()
    with pytest.raises(RunTransitionError, match="RUN_RUNTIME_SUSPENDED"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=uuid4(),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status="running",
            target_status="completed",
            background_claim_token=token,
        )
    recovery = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status="running",
        target_status="recovery_required",
        awaiting_reference="runtime-suspended",
        reason_code="RUN_RUNTIME_SUSPENDED",
        background_claim_token=token,
    )
    assert recovery.status == "recovery_required"


@pytest.mark.django_db
def test_bounded_unified_executor_completes_without_legacy_side_tables(
    workflow_fixture,
) -> None:
    run = _queued_background_run(workflow_fixture, key="bounded-executor")
    Run.objects.filter(pk=run.id).update(redacted_state={"query": "hello"})
    token = uuid4()
    claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
        lease_seconds=30,
    )
    result = execute_claimed_bounded_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
    )
    assert result.status == "completed"
    run.refresh_from_db()
    assert run.checkpoint["output"] == {"answer": "ok", "sources": []}
    assert run.step_count == 3
    assert run.background_claim_token is None


@pytest.mark.django_db
def test_bounded_unified_executor_is_the_default_runtime(workflow_fixture) -> None:
    run = _queued_background_run(workflow_fixture, key="bounded-executor-default")
    token = uuid4()
    claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
        lease_seconds=30,
    )
    result = execute_claimed_bounded_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
    )
    run.refresh_from_db()
    assert result.status == run.status == "completed"


@pytest.mark.django_db
def test_bounded_unified_executor_observes_cancellation_between_nodes(
    workflow_fixture,
    monkeypatch,
) -> None:
    from apps.workflows import unified_executor

    run = _queued_background_run(workflow_fixture, key="bounded-executor-cancel")
    token = uuid4()
    claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
        lease_seconds=30,
    )
    original_execute_node = unified_executor._execute_node

    def execute_then_cancel(**kwargs):
        result = original_execute_node(**kwargs)
        if kwargs["node"]["type"] == "input":
            request_run_cancellation(
                organization_id=run.organization_id,
                run_id=run.id,
                reason_code="CLIENT_REQUESTED",
            )
        return result

    monkeypatch.setattr(unified_executor, "_execute_node", execute_then_cancel)
    result = execute_claimed_bounded_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
    )
    assert result.status == "cancelled"
    run.refresh_from_db()
    assert run.background_claim_token is None


@pytest.mark.django_db
def test_identifier_only_delivery_executes_and_rejects_stale_revision(
    workflow_fixture,
) -> None:
    run = _queued_background_run(workflow_fixture, key="celery-delivery")
    token = uuid4()
    body: dict[str, object] = {"run_id": str(run.id), "delivery_token": str(token)}
    headers = {
        "organization_id": run.organization_id,
        "service_revision": "stale-revision",
    }
    with pytest.raises(UnifiedExecutorError, match="RUN_EXECUTOR_REVISION_MISMATCH"):
        execute_background_delivery(body=body, headers=headers)
    run.refresh_from_db()
    assert run.background_claim_token is None

    headers["service_revision"] = service_revision()
    assert execute_background_delivery(body=body, headers=headers) == "completed"


@pytest.mark.django_db
def test_delivery_redelivery_converges_expired_queued_and_running_claims(
    workflow_fixture,
) -> None:
    queued = _queued_background_run(workflow_fixture, key="celery-expired-queued")
    queued_token = uuid4()
    claim_background_run(
        organization_id=queued.organization_id,
        run_id=queued.id,
        claim_token=queued_token,
        lease_seconds=30,
    )
    Run.objects.filter(pk=queued.id).update(
        background_claim_expires_at=timezone.now() - timedelta(seconds=1)
    )
    headers = {
        "organization_id": queued.organization_id,
        "service_revision": service_revision(),
    }
    assert (
        execute_background_delivery(
            body={"run_id": str(queued.id), "delivery_token": str(queued_token)},
            headers=headers,
        )
        == "completed"
    )
    assert (
        AuditEvent.objects.filter(
            action="workflow.run.background_claim_released",
            resource_id=str(queued.id),
        ).count()
        == 1
    )

    running = _queued_background_run(workflow_fixture, key="celery-expired-running")
    running_token = uuid4()
    claim = claim_background_run(
        organization_id=running.organization_id,
        run_id=running.id,
        claim_token=running_token,
        lease_seconds=30,
    )
    transition_run(
        organization_id=running.organization_id,
        run_id=running.id,
        transition_token=uuid4(),
        expected_checkpoint_version=claim.checkpoint_version,
        expected_status="queued",
        target_status="running",
        background_claim_token=running_token,
    )
    Run.objects.filter(pk=running.id).update(
        background_claim_expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert (
        execute_background_delivery(
            body={"run_id": str(running.id), "delivery_token": str(running_token)},
            headers={
                "organization_id": running.organization_id,
                "service_revision": service_revision(),
            },
        )
        == "recovery_required"
    )
    running.refresh_from_db()
    assert running.status == "recovery_required"


@pytest.mark.django_db
def test_delivery_redelivery_continues_after_worker_crash_post_start(
    workflow_fixture,
    monkeypatch,
) -> None:
    from apps.workflows import unified_executor

    run = _queued_background_run(workflow_fixture, key="celery-crash-after-start")
    token = uuid4()
    body: dict[str, object] = {"run_id": str(run.id), "delivery_token": str(token)}
    headers = {
        "organization_id": run.organization_id,
        "service_revision": service_revision(),
    }

    def crash_after_start(**_kwargs):
        raise RuntimeError("simulated worker loss")

    monkeypatch.setattr(unified_executor, "_execute_node", crash_after_start)
    with pytest.raises(RuntimeError, match="simulated worker loss"):
        execute_background_delivery(body=body, headers=headers)
    run.refresh_from_db()
    assert run.status == "running"

    monkeypatch.undo()
    assert execute_background_delivery(body=body, headers=headers) == "completed"
    run.refresh_from_db()
    assert run.status == "completed"
    assert run.events.filter(event_type=RunEventType.STARTED).count() == 1


@pytest.mark.django_db
def test_unified_dispatch_is_on_commit_identifier_only(
    workflow_fixture,
    django_capture_on_commit_callbacks,
    monkeypatch,
) -> None:
    run = _queued_background_run(workflow_fixture, key="celery-dispatch")
    token = uuid4()
    calls: list[dict[str, object]] = []

    def capture_apply_async(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(execute_unified_background_run, "apply_async", capture_apply_async)
    with django_capture_on_commit_callbacks(execute=True):
        returned = dispatch_unified_background_run(
            run_id=run.id,
            organization_id=run.organization_id,
            delivery_token=token,
        )
        assert calls == []
    assert returned == token
    assert calls == [
        {
            "args": (str(run.id), str(token)),
            "headers": {
                "organization_id": run.organization_id,
                "service_revision": service_revision(),
            },
            "queue": "runtime",
        }
    ]
    assert execute_unified_background_run.acks_late is True
    assert execute_unified_background_run.reject_on_worker_lost is True


@pytest.mark.django_db
def test_unified_celery_task_executes_with_closed_headers(workflow_fixture) -> None:
    run = _queued_background_run(workflow_fixture, key="celery-task")
    token = uuid4()
    result = execute_unified_background_run.apply(
        args=(str(run.id), str(token)),
        headers={
            "organization_id": run.organization_id,
            "service_revision": service_revision(),
        },
    )
    assert result.get() == "completed"
    run.refresh_from_db()
    assert run.status == "completed"


def test_bounded_unified_executor_rejects_unsupported_and_cyclic_graphs() -> None:
    with pytest.raises(UnifiedExecutorError, match="RUN_EXECUTOR_NODE_UNSUPPORTED"):
        _validated_graph(
            {
                "api_version": "agenthub/compiled-workflow/v5",
                "input_node": "request",
                "nodes": [
                    {"id": "request", "type": "input", "config": {}},
                    # The executor's node allowlist is deny-by-default: a type it does not
                    # implement is refused rather than skipped or guessed at.
                    {"id": "later", "type": "not_yet_implemented", "config": {}},
                ],
                "edges": [{"from": "request", "to": "later"}],
            }
        )
    with pytest.raises(UnifiedExecutorError, match="RUN_EXECUTOR_GRAPH_UNBOUNDED"):
        _validated_graph(
            {
                "api_version": "agenthub/compiled-workflow/v5",
                "input_node": "request",
                "nodes": [
                    {"id": "request", "type": "input", "config": {}},
                    {
                        "id": "condition",
                        "type": "condition",
                        "config": {"expression": "true"},
                    },
                    {"id": "done", "type": "end", "config": {}},
                ],
                "edges": [
                    {"from": "request", "to": "condition"},
                    {"from": "condition", "to": "condition", "when": True},
                    {"from": "condition", "to": "done", "when": False},
                ],
            }
        )


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db(transaction=True)
def test_concurrent_background_delivery_has_one_claim_owner(workflow_fixture) -> None:
    run = _queued_background_run(workflow_fixture, key="background-claim-race")
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def claim(token) -> None:
        close_old_connections()
        try:
            barrier.wait()
            result = claim_background_run(
                organization_id=run.organization_id,
                run_id=run.id,
                claim_token=token,
                lease_seconds=30,
            )
            outcomes.append(result.outcome)
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=claim, args=(uuid4(),)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(outcomes) == ["busy", "claimed"]


@pytest.mark.django_db
def test_expired_background_claim_reclaims_only_before_running(workflow_fixture) -> None:
    run = _queued_background_run(workflow_fixture, key="background-expiry")
    old_token = uuid4()
    claim = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=old_token,
        lease_seconds=30,
    )
    Run.objects.filter(pk=run.id).update(
        background_claim_expires_at=timezone.now() - timedelta(seconds=1)
    )
    replacement_token = uuid4()
    replacement = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=replacement_token,
        lease_seconds=30,
    )
    assert replacement.outcome == "claimed"
    with pytest.raises(RunTransitionError, match="RUN_BACKGROUND_CLAIM_STALE"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=uuid4(),
            expected_checkpoint_version=claim.checkpoint_version,
            expected_status="queued",
            target_status="running",
            background_claim_token=old_token,
        )

    transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=replacement.checkpoint_version,
        expected_status="queued",
        target_status="running",
        background_claim_token=replacement_token,
    )
    Run.objects.filter(pk=run.id).update(
        background_claim_expires_at=timezone.now() - timedelta(seconds=1)
    )
    outcome = resolve_expired_background_claim(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=replacement_token,
        transition_token=uuid4(),
    )
    assert outcome == "committed"
    run.refresh_from_db()
    assert run.status == "recovery_required"
    assert run.background_claim_token is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("guard", "expected_outcome", "expected_status"),
    [
        ("cancellation", "cancellation_requested", "cancelled"),
        ("deadline", "deadline_exceeded", "timed_out"),
    ],
)
def test_background_claim_observes_cancellation_and_deadline_before_work(
    workflow_fixture,
    guard: str,
    expected_outcome: str,
    expected_status: str,
) -> None:
    run = _queued_background_run(workflow_fixture, key=f"background-{guard}")
    if guard == "cancellation":
        request_run_cancellation(
            organization_id=run.organization_id,
            run_id=run.id,
            reason_code="CLIENT_REQUESTED",
        )
    else:
        Run.objects.filter(pk=run.id).update(deadline_at=timezone.now() - timedelta(seconds=1))

    claim = claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=uuid4(),
        lease_seconds=30,
    )
    assert claim.outcome == expected_outcome
    run.refresh_from_db()
    result = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status="queued",
        target_status=expected_status,
    )
    assert result.status == expected_status


@pytest.mark.django_db
def test_event_allocator_owns_monotonic_sequence(workflow_fixture) -> None:
    run = _run(workflow_fixture)

    first = append_run_event(
        run_id=run.id,
        event_type=RunEventType.REQUESTED,
        payload={"request_id": "req-safe"},
    )
    second = append_run_event(
        run_id=run.id,
        event_type=RunEventType.QUEUED,
        payload={"queue": "runtime"},
    )

    run.refresh_from_db()
    assert [first.sequence, second.sequence] == [1, 2]
    assert run.next_event_sequence == 3
    with pytest.raises(IntegrityError):
        RunEvent.objects.create(
            organization=run.organization,
            run=run,
            sequence=2,
            event_type=RunEventType.STARTED,
        )


@pytest.mark.django_db
def test_event_payload_rejects_sensitive_oversized_and_deep_values(workflow_fixture) -> None:
    run = _run(workflow_fixture)

    assert validate_run_event_payload({"input_token_count": 12}) == {"input_token_count": 12}
    with pytest.raises(ValidationError, match="forbidden"):
        append_run_event(
            run_id=run.id,
            event_type=RunEventType.REQUESTED,
            payload={"access_token": "do not persist"},
        )
    with pytest.raises(ValidationError, match="16 KiB"):
        validate_run_event_payload({"safe_value": "x" * (16 * 1024)})
    nested: dict[str, Any] = {"safe": {}}
    cursor = nested["safe"]
    for _ in range(8):
        cursor["safe"] = {}
        cursor = cursor["safe"]
    with pytest.raises(ValidationError, match="depth"):
        validate_run_event_payload(nested)


@pytest.mark.django_db
def test_transition_commits_checkpoint_counters_and_terminal_guard(workflow_fixture) -> None:
    run = _run(workflow_fixture)

    started = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=1,
        expected_status="requested",
        target_status="running",
        checkpoint={"cursor": "node-a"},
        step_delta=1,
        input_token_delta=7,
    )
    completed = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=2,
        expected_status="running",
        target_status="completed",
        checkpoint={"output": {"status": "[redacted]"}},
        output_token_delta=3,
    )
    late = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=3,
        expected_status="running",
        target_status="failed",
        error_code="LATE_FAILURE",
    )

    run.refresh_from_db()
    assert (started.outcome, completed.outcome, late.outcome) == (
        "committed",
        "committed",
        "terminal",
    )
    assert run.status == "completed"
    assert run.checkpoint_version == 3
    assert (run.step_count, run.input_token_count, run.output_token_count) == (1, 7, 3)
    assert list(run.events.values_list("sequence", "event_type")) == [
        (1, "run.started"),
        (2, "run.completed"),
        (3, "run.late_result_discarded"),
    ]


@pytest.mark.django_db
def test_sync_transition_requires_the_exact_live_lease_after_admission(
    workflow_fixture,
) -> None:
    run = _run(workflow_fixture, execution_mode=RunExecutionMode.SYNC)
    transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=RunStatus.REQUESTED,
        target_status=RunStatus.QUEUED,
    )
    run.refresh_from_db()
    lease_token = uuid4()
    renew_sync_lease(
        organization_id=run.organization_id,
        run_id=run.id,
        lease_token=lease_token,
        expires_at=timezone.now() + timedelta(seconds=30),
    )

    with pytest.raises(RunTransitionError, match="RUN_SYNC_LEASE_REQUIRED"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=uuid4(),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=RunStatus.QUEUED,
            target_status=RunStatus.RUNNING,
        )
    with pytest.raises(RunTransitionError, match="RUN_SYNC_LEASE_STALE"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=uuid4(),
            expected_checkpoint_version=run.checkpoint_version,
            expected_status=RunStatus.QUEUED,
            target_status=RunStatus.RUNNING,
            sync_lease_token=uuid4(),
        )

    started = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=RunStatus.QUEUED,
        target_status=RunStatus.RUNNING,
        sync_lease_token=lease_token,
    )
    assert started.outcome == "committed"


@pytest.mark.django_db
def test_transition_rejects_stale_invalid_and_unbounded_mutations(workflow_fixture) -> None:
    run = _run(workflow_fixture)
    transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=1,
        target_status="running",
    )

    stale = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=1,
        target_status="completed",
    )
    assert stale.outcome == "stale"
    with pytest.raises(RunTransitionError, match="RUN_AWAITING_REFERENCE_INVALID"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=uuid4(),
            expected_checkpoint_version=2,
            target_status="waiting_event",
        )
    with pytest.raises(RunTransitionError, match="RUN_COUNTER_DELTA_INVALID"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=uuid4(),
            expected_checkpoint_version=2,
            target_status="failed",
            step_delta=-1,
        )
    with pytest.raises(RunTransitionError, match="RUN_CHECKPOINT_TOO_LARGE"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=uuid4(),
            expected_checkpoint_version=2,
            target_status="failed",
            checkpoint={"safe": "x" * (1024 * 1024)},
        )


@pytest.mark.django_db
def test_transition_token_replay_is_side_effect_free_and_conflicts_fail(
    workflow_fixture,
) -> None:
    run = _run(workflow_fixture)
    token = uuid4()
    first = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=token,
        expected_checkpoint_version=1,
        expected_status="requested",
        target_status="running",
        step_delta=1,
    )
    replay = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=token,
        expected_checkpoint_version=1,
        expected_status="requested",
        target_status="running",
        step_delta=1,
    )

    assert replay == first
    assert run.events.count() == 1
    with pytest.raises(RunTransitionError, match="RUN_TRANSITION_TOKEN_CONFLICT"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            transition_token=token,
            expected_checkpoint_version=1,
            expected_status="requested",
            target_status="running",
            step_delta=2,
        )


@pytest.mark.django_db
def test_cancellation_request_is_cooperative_and_idempotent(workflow_fixture) -> None:
    run = _run(workflow_fixture)

    first = request_run_cancellation(
        organization_id=run.organization_id,
        run_id=run.id,
        reason_code="CLIENT_DISCONNECTED",
    )
    replay = request_run_cancellation(
        organization_id=run.organization_id,
        run_id=run.id,
        reason_code="CLIENT_DISCONNECTED",
    )

    run.refresh_from_db()
    assert (first.outcome, replay.outcome) == ("committed", "replayed")
    assert run.status == "requested"
    assert run.cancellation_state == RunCancellationState.REQUESTED
    assert run.events.filter(event_type=RunEventType.CANCELLATION_REQUESTED).count() == 1

    cancelled = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status="requested",
        target_status="completed",
    )
    run.refresh_from_db()
    assert cancelled.status == "cancelled"
    assert run.cancellation_state == RunCancellationState.ACKNOWLEDGED


@pytest.mark.django_db
def test_expired_sync_lease_enters_recovery_without_background_takeover(
    workflow_fixture,
) -> None:
    run = _run(
        workflow_fixture,
        execution_mode=RunExecutionMode.SYNC,
    )
    lease_token = uuid4()
    now = timezone.now()
    renew_sync_lease(
        organization_id=run.organization_id,
        run_id=run.id,
        lease_token=lease_token,
        expires_at=now + timedelta(seconds=30),
    )
    Run.objects.filter(pk=run.id).update(sync_lease_expires_at=now - timedelta(seconds=1))

    result = resolve_expired_sync_lease(
        organization_id=run.organization_id,
        run_id=run.id,
        lease_token=lease_token,
        transition_token=uuid4(),
        observed_at=now,
    )

    run.refresh_from_db()
    assert result.status == "recovery_required"
    assert run.execution_mode == RunExecutionMode.SYNC
    assert run.awaiting_kind == "recovery"


@pytest.mark.django_db
def test_operator_recovery_resolution_is_explicit_terminal_and_audited(
    workflow_fixture,
) -> None:
    run = _run(workflow_fixture, key="operator-recovery")
    transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        transition_token=uuid4(),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=RunStatus.REQUESTED,
        target_status=RunStatus.RECOVERY_REQUIRED,
        awaiting_reference="ambiguous-provider-result",
        error_code="OUTCOME_UNKNOWN",
    )
    run.refresh_from_db()

    with pytest.raises(RunRecoveryError, match="RUN_RECOVERY_DECISION_INVALID"):
        resolve_run_recovery(
            organization_id=run.organization_id,
            run_id=run.id,
            actor_id="operator",
            decision="retry",
        )
    resolved = resolve_run_recovery(
        organization_id=run.organization_id,
        run_id=run.id,
        actor_id="operator",
        decision="confirm_failed",
    )

    assert resolved.status == RunStatus.FAILED
    run.refresh_from_db()
    assert (run.error_code, run.reason_code) == (
        "OUTCOME_UNKNOWN",
        "OPERATOR_CONFIRMED_FAILED",
    )
    assert (
        AuditEvent.objects.filter(
            organization_id=run.organization_id,
            resource_id=str(run.id),
            action="workflow.run.recovery.resolve",
            actor_id="operator",
        ).count()
        == 1
    )
    assert run.sync_lease_token is None


@pytest.mark.django_db
def test_expired_cancelled_sync_lease_becomes_cancelled(workflow_fixture) -> None:
    run = _run(workflow_fixture, execution_mode=RunExecutionMode.SYNC)
    lease_token = uuid4()
    now = timezone.now()
    renew_sync_lease(
        organization_id=run.organization_id,
        run_id=run.id,
        lease_token=lease_token,
        expires_at=now + timedelta(seconds=30),
    )
    request_run_cancellation(
        organization_id=run.organization_id,
        run_id=run.id,
        reason_code="CLIENT_DISCONNECTED",
    )
    Run.objects.filter(pk=run.id).update(sync_lease_expires_at=now - timedelta(seconds=1))

    result = resolve_expired_sync_lease(
        organization_id=run.organization_id,
        run_id=run.id,
        lease_token=lease_token,
        transition_token=uuid4(),
        observed_at=now,
    )

    run.refresh_from_db()
    assert result.status == "cancelled"
    assert run.cancellation_state == RunCancellationState.ACKNOWLEDGED
    assert run.sync_lease_token is None


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db(transaction=True)
def test_concurrent_unified_admission_creates_one_exact_run(workflow_fixture) -> None:
    workflow_version = WorkflowVersion.objects.get(scenario=workflow_fixture.scenario)
    context = issue_execution_context(
        organization_id=workflow_fixture.organization.id,
        project_id=workflow_fixture.scenario.project_id,
        scenario_id=workflow_fixture.scenario.id,
        scenario_alias=workflow_fixture.alias,
        consumer_id=workflow_fixture.consumer.id,
        capabilities=["workflow_run"],
        release_id=workflow_fixture.release.id,
        request_id="concurrent-unified-admission",
    )
    barrier = Barrier(2)
    results: list[tuple[UUID, bool, str | None]] = []
    errors: list[BaseException] = []

    def attempt() -> None:
        close_old_connections()
        try:
            barrier.wait()
            admitted, created = request_unified_run(
                release=workflow_fixture.release,
                consumer=workflow_fixture.consumer,
                workflow_version=workflow_version,
                execution_context=context,
                input_payload={"query": "same"},
                idempotency_key="concurrent-unified-admission",
                execution_mode=RunExecutionMode.BACKGROUND,
            )
            results.append((admitted.id, created, admitted.response_id))
        except BaseException as exc:  # pragma: no cover - asserted by parent thread
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=attempt), Thread(target=attempt)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert len(results) == 2
    assert {item[0] for item in results} == {Run.objects.get().id}
    assert sorted(item[1] for item in results) == [False, True]
    assert len({item[2] for item in results}) == 1
    assert list(RunEvent.objects.values_list("sequence", "event_type")) == [
        (1, RunEventType.REQUESTED),
        (2, RunEventType.QUEUED),
    ]


@pytest.mark.django_db
def test_unified_admission_rejects_mismatched_or_unprivileged_signed_context(
    workflow_fixture,
) -> None:
    workflow_version = WorkflowVersion.objects.get(scenario=workflow_fixture.scenario)

    def context(*, consumer_id: int, capabilities: list[str]) -> dict:
        return issue_execution_context(
            organization_id=workflow_fixture.organization.id,
            project_id=workflow_fixture.scenario.project_id,
            scenario_id=workflow_fixture.scenario.id,
            scenario_alias=workflow_fixture.alias,
            consumer_id=consumer_id,
            capabilities=capabilities,
            release_id=workflow_fixture.release.id,
            request_id="unified-context-boundary",
        )

    for key, signed_context in (
        (
            "wrong-consumer-context",
            context(
                consumer_id=workflow_fixture.consumer.id + 1,
                capabilities=["workflow_run"],
            ),
        ),
        (
            "missing-capability-context",
            context(
                consumer_id=workflow_fixture.consumer.id,
                capabilities=[],
            ),
        ),
    ):
        with pytest.raises(WorkflowRequestError, match="EXECUTION_CONTEXT_INVALID"):
            request_unified_run(
                release=workflow_fixture.release,
                consumer=workflow_fixture.consumer,
                workflow_version=workflow_version,
                execution_context=signed_context,
                input_payload={"query": "same"},
                idempotency_key=key,
                execution_mode=RunExecutionMode.BACKGROUND,
            )

    assert not Run.objects.exists()


@pytest.mark.django_db
def test_unified_admission_rejects_exact_project_suspension(workflow_fixture) -> None:
    workflow_version = WorkflowVersion.objects.get(scenario=workflow_fixture.scenario)
    AgentRuntimeControl.objects.create(
        scope_type=RuntimeControlScope.PROJECT,
        organization=workflow_fixture.organization,
        project=workflow_fixture.scenario.project,
        suspended=True,
        reason_code="incident_response",
        reason="Project incident",
        updated_by="safety-system",
    )
    context = issue_execution_context(
        organization_id=workflow_fixture.organization.id,
        project_id=workflow_fixture.scenario.project_id,
        scenario_id=workflow_fixture.scenario.id,
        scenario_alias=workflow_fixture.alias,
        consumer_id=workflow_fixture.consumer.id,
        capabilities=["workflow_run"],
        release_id=workflow_fixture.release.id,
        request_id="project-suspended-admission",
    )

    with pytest.raises(WorkflowRequestError, match="RUN_RUNTIME_SUSPENDED"):
        request_unified_run(
            release=workflow_fixture.release,
            consumer=workflow_fixture.consumer,
            workflow_version=workflow_version,
            execution_context=context,
            input_payload={"query": "same"},
            idempotency_key="project-suspended-admission",
            execution_mode=RunExecutionMode.BACKGROUND,
        )

    assert not Run.objects.exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db(transaction=True)
def test_concurrent_transition_has_one_commit_and_one_stale_result(workflow_fixture) -> None:
    run = _run(workflow_fixture)
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def attempt() -> None:
        close_old_connections()
        try:
            barrier.wait()
            result = transition_run(
                organization_id=run.organization_id,
                run_id=run.id,
                transition_token=uuid4(),
                expected_checkpoint_version=1,
                expected_status="requested",
                target_status="running",
            )
            outcomes.append(result.outcome)
        except BaseException as exc:  # pragma: no cover - asserted by parent thread
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=attempt), Thread(target=attempt)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert sorted(outcomes) == ["committed", "stale"]
    run.refresh_from_db()
    assert run.status == "running"
    assert run.checkpoint_version == 2
    assert list(run.events.values_list("sequence", "event_type")) == [
        (1, "run.started"),
        (2, "run.late_result_discarded"),
    ]


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_transition_token_replays_one_event(workflow_fixture) -> None:
    run = _run(workflow_fixture)
    barrier = Barrier(2)
    token = uuid4()
    results = []
    errors: list[BaseException] = []

    def attempt() -> None:
        close_old_connections()
        try:
            barrier.wait()
            results.append(
                transition_run(
                    organization_id=run.organization_id,
                    run_id=run.id,
                    transition_token=token,
                    expected_checkpoint_version=1,
                    expected_status="requested",
                    target_status="running",
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted by parent thread
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=attempt), Thread(target=attempt)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(results) == 2
    assert results[0] == results[1]
    assert run.events.count() == 1


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db
def test_run_wait_suspends_and_resumes_once_without_legacy_wait_rows(workflow_fixture) -> None:
    run, claim_token, started = _claimed_background_run(
        workflow_fixture,
        key="unified-wait-resume",
    )
    created = suspend_run_for_wait(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=claim_token,
        expected_checkpoint_version=started.checkpoint_version,
        node_id="approval",
        kind="human",
        checkpoint={"cursor": "approval", "decisions": {}},
        deadline_at=timezone.now() + timedelta(minutes=1),
        payload_schema={
            "type": "object",
            "properties": {"approved": {"type": "boolean"}},
            "required": ["approved"],
            "additionalProperties": False,
        },
        output_mapping=[{"from": "/payload/approved", "to": "/decisions/approved"}],
        allowed_roles=["approver"],
    )

    run.refresh_from_db()
    wait_id, resume_token = _suspended(created)
    wait = RunWait.objects.get(pk=wait_id)
    assert run.status == "waiting_human"
    assert run.awaiting_reference == str(wait.id)
    assert run.background_claim_token is None
    assert wait.checkpoint_version_snapshot == run.checkpoint_version

    resumed = resume_run_wait(
        organization_id=run.organization_id,
        resume_token=resume_token,
        actor_id="operator:approver",
        actor_roles={"approver"},
        payload={"approved": True},
    )
    replayed = resume_run_wait(
        organization_id=run.organization_id,
        resume_token=resume_token,
        actor_id="operator:approver",
        actor_roles={"approver"},
        payload={"approved": True},
    )

    run.refresh_from_db()
    wait.refresh_from_db()
    assert resumed.outcome == "committed"
    assert replayed.outcome == "replayed"
    assert replayed.checkpoint_version == resumed.checkpoint_version
    assert run.status == "queued"
    assert run.awaiting_kind == ""
    assert run.awaiting_reference == ""
    assert run.background_claim_token is None
    assert run.checkpoint["decisions"] == {"approved": True}
    assert wait.status == RunWaitStatus.RESUMED
    assert wait.redacted_payload == {"approved": True}
    assert wait.consumed_by == "operator:approver"
    assert not hasattr(run, "workflowrun")
    assert (
        AuditEvent.objects.filter(
            action="workflow.run_wait_resume",
            outcome="success",
            reason="RUN_WAIT_RESUMED",
        ).count()
        == 1
    )
    # One resume signal produces exactly one waiting and one resumed transition.
    assert [event.event_type for event in run.events.order_by("sequence")][-2:] == [
        RunEventType.WAITING,
        RunEventType.QUEUED,
    ]


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db
def test_run_wait_denies_forgery_roles_payload_conflict_and_cross_tenant(
    workflow_fixture,
) -> None:
    run, claim_token, started = _claimed_background_run(
        workflow_fixture,
        key="unified-wait-denials",
    )
    other_organization = Organization.objects.create(slug="other-wait-org", name="Other Wait Org")
    created = suspend_run_for_wait(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=claim_token,
        expected_checkpoint_version=started.checkpoint_version,
        node_id="approval",
        kind="approval",
        checkpoint={"cursor": "approval"},
        deadline_at=timezone.now() + timedelta(minutes=1),
        payload_schema={
            "type": "object",
            "properties": {"approved": {"type": "boolean"}},
            "required": ["approved"],
            "additionalProperties": False,
        },
        allowed_roles=["approver"],
    )
    wait_id, resume_token = _suspended(created)
    # Every denial reports the same code: a token holder learns nothing about why it failed.
    denials: tuple[tuple[str, UUID, int, str, set[str]], ...] = (
        ("RUN_WAIT_NOT_FOUND", uuid4(), run.organization_id, "operator:approver", {"approver"}),
        (
            "RUN_WAIT_NOT_FOUND",
            resume_token,
            other_organization.id,
            "operator:approver",
            {"approver"},
        ),
        (
            "RUN_WAIT_NOT_FOUND",
            resume_token,
            run.organization_id,
            "operator:viewer",
            {"viewer"},
        ),
        (
            "RUN_WAIT_NOT_FOUND",
            resume_token,
            run.organization_id,
            "operator:approver",
            set(),
        ),
        # Separation of duties: the run's own actor cannot decide its approval.
        (
            "RUN_WAIT_NOT_FOUND",
            resume_token,
            run.organization_id,
            "test-actor",
            {"approver"},
        ),
    )
    for code, token, organization_id, actor_id, roles in denials:
        with pytest.raises(RunWaitError, match=code):
            resume_run_wait(
                organization_id=organization_id,
                resume_token=token,
                actor_id=actor_id,
                actor_roles=roles,
                payload={"approved": True},
            )
    with pytest.raises(RunWaitError, match="RUN_WAIT_PAYLOAD_INVALID"):
        resume_run_wait(
            organization_id=run.organization_id,
            resume_token=resume_token,
            actor_id="operator:approver",
            actor_roles={"approver"},
            payload={"approved": "yes"},
        )

    run.refresh_from_db()
    wait = RunWait.objects.get(pk=wait_id)
    # Every denial is audited and none of them consumed the one-shot authority.
    assert wait.status == RunWaitStatus.PENDING
    assert run.status == "waiting_approval"
    assert AuditEvent.objects.filter(action="workflow.run_wait_resume", outcome="deny").count() == 6

    resume_run_wait(
        organization_id=run.organization_id,
        resume_token=resume_token,
        actor_id="operator:approver",
        actor_roles={"approver"},
        payload={"approved": True},
    )
    with pytest.raises(RunWaitError, match="RUN_WAIT_REPLAY_CONFLICT"):
        resume_run_wait(
            organization_id=run.organization_id,
            resume_token=resume_token,
            actor_id="operator:approver",
            actor_roles={"approver"},
            payload={"approved": False},
        )


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db
def test_expired_run_wait_closes_the_run_instead_of_leaving_it_waiting(
    workflow_fixture,
) -> None:
    run, claim_token, started = _claimed_background_run(
        workflow_fixture,
        key="unified-wait-expired",
    )
    created = suspend_run_for_wait(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=claim_token,
        expected_checkpoint_version=started.checkpoint_version,
        node_id="event",
        kind="event",
        checkpoint={"cursor": "event"},
        deadline_at=timezone.now() + timedelta(minutes=1),
    )
    wait_id, resume_token = _suspended(created)
    RunWait.objects.filter(pk=wait_id).update(deadline_at=timezone.now() - timedelta(seconds=1))

    with pytest.raises(RunWaitError, match="RUN_WAIT_NOT_FOUND"):
        resume_run_wait(
            organization_id=run.organization_id,
            resume_token=resume_token,
            actor_id="consumer:signal",
            payload={},
        )

    run.refresh_from_db()
    assert RunWait.objects.get(pk=wait_id).status == RunWaitStatus.EXPIRED
    assert run.status == "failed"
    assert run.error_code == "RUN_WAIT_EXPIRED"
    assert run.awaiting_reference == ""
    assert AuditEvent.objects.filter(
        action="workflow.run_wait_resume",
        outcome="deny",
        reason="RUN_WAIT_EXPIRED",
    ).exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db
def test_run_wait_rejects_protected_output_mapping_and_reports_cancelled_run(
    workflow_fixture,
) -> None:
    run, claim_token, started = _claimed_background_run(
        workflow_fixture,
        key="unified-wait-protected",
    )
    with pytest.raises(RunWaitError, match="RUN_WAIT_CONFIG_INVALID"):
        suspend_run_for_wait(
            organization_id=run.organization_id,
            run_id=run.id,
            claim_token=claim_token,
            expected_checkpoint_version=started.checkpoint_version,
            node_id="approval",
            kind="human",
            checkpoint={"cursor": "approval"},
            deadline_at=timezone.now() + timedelta(minutes=1),
            output_mapping=[{"from": "/payload/role", "to": "/authorization/role"}],
            allowed_roles=["approver"],
        )

    request_run_cancellation(
        organization_id=run.organization_id,
        run_id=run.id,
        reason_code="OPERATOR_REQUESTED",
    )
    created = suspend_run_for_wait(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=claim_token,
        expected_checkpoint_version=started.checkpoint_version,
        node_id="approval",
        kind="human",
        checkpoint={"cursor": "approval"},
        deadline_at=timezone.now() + timedelta(minutes=1),
        allowed_roles=["approver"],
    )

    run.refresh_from_db()
    # Cancellation won the race: the committed terminal transition is reported, never rolled
    # back, and no resume authority exists for a run that can no longer continue.
    assert created.outcome == "converged"
    assert created.wait_id is None
    assert created.resume_token is None
    assert run.status == "cancelled"
    assert not RunWait.objects.filter(run=run).exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="FORCE RLS requires PostgreSQL")
@pytest.mark.django_db
def test_unified_run_tables_force_rls_for_non_owner_role(workflow_fixture) -> None:
    run = _run(workflow_fixture)
    event = append_run_event(run_id=run.id, event_type=RunEventType.REQUESTED)
    waiting_run, claim_token, started = _claimed_background_run(
        workflow_fixture,
        key="unified-wait-rls",
    )
    created = suspend_run_for_wait(
        organization_id=waiting_run.organization_id,
        run_id=waiting_run.id,
        claim_token=claim_token,
        expected_checkpoint_version=started.checkpoint_version,
        node_id="approval",
        kind="event",
        checkpoint={"cursor": "event"},
        deadline_at=timezone.now() + timedelta(minutes=1),
    )
    wait_id, _resume_token = _suspended(created)
    join = RunJoin.objects.create(
        organization=run.organization,
        run=run,
        region_node_id="rls-region",
        join_node_id="rls-join",
        compiled_checksum=run.compiled_checksum,
        mode="all",
        required_count=1,
        branch_count=1,
        max_concurrency=1,
        max_duration_seconds=60,
        max_state_bytes=1024,
        deadline_at=run.deadline_at,
    )
    branch = RunBranch.objects.create(
        organization=run.organization,
        run=run,
        region_node_id=join.region_node_id,
        branch_name="rls",
        compiled_checksum=run.compiled_checksum,
        input_state={},
    )
    role = "rls_probe_unified_run"
    tables = (
        Run._meta.db_table,
        RunEvent._meta.db_table,
        RunWait._meta.db_table,
        RunBranch._meta.db_table,
        RunJoin._meta.db_table,
    )
    rows = (
        (tables[0], run.id),
        (tables[1], event.id),
        (tables[2], wait_id),
        (tables[3], branch.id),
        (tables[4], join.id),
    )

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        if cursor.fetchone():
            cursor.execute(f"DROP OWNED BY {role}")
            cursor.execute(f"DROP ROLE {role}")
        cursor.execute(f"CREATE ROLE {role} NOSUPERUSER NOLOGIN")
        for table in tables:
            cursor.execute(f'GRANT SELECT ON "{table}" TO {role}')
        cursor.execute(
            f"GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO {role}"
        )
        cursor.execute(
            "SELECT set_config('app.tenant_scope', %s, true)",
            [str(workflow_fixture.organization.id)],
        )
        cursor.execute(f"SET ROLE {role}")
        for table, row_id in rows:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id = %s', [row_id])  # noqa: S608
            assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", ["99999999"])
        cursor.execute(f"SET ROLE {role}")
        for table, row_id in rows:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id = %s', [row_id])  # noqa: S608
            assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")
        cursor.execute(f"DROP OWNED BY {role}")
        cursor.execute(f"DROP ROLE {role}")


# The owner-approved application-role inventory for the unified Run plane. `Run`, `RunWait`,
# branches, joins, child links and compensation intent carry mutable state; RunEvent is
# append-only. None has a delete path.
UNIFIED_RUN_GRANTS = {
    "workflows_run": ("SELECT", "INSERT", "UPDATE"),
    "workflows_runevent": ("SELECT", "INSERT"),
    "workflows_runwait": ("SELECT", "INSERT", "UPDATE"),
    "workflows_runbranch": ("SELECT", "INSERT", "UPDATE"),
    "workflows_runjoin": ("SELECT", "INSERT", "UPDATE"),
    "workflows_runchildlink": ("SELECT", "INSERT", "UPDATE"),
    "workflows_runcompensationentry": ("SELECT", "INSERT", "UPDATE"),
}


def test_unified_run_tables_are_protected_and_provisioned() -> None:
    inventory = {table.table_name: table for table in protected_tenant_tables()}
    sql = (settings.BASE_DIR / "deploy" / "postgres" / "provision-app-role.sql").read_text(
        encoding="utf-8"
    )

    # Comments are stripped first: a rationale mentioning DELETE must not read as a grant of it.
    statements = [
        "\n".join(line for line in statement.splitlines() if not line.lstrip().startswith("--"))
        for statement in sql.split(";")
    ]
    delete_grants = [
        statement for statement in statements if "GRANT" in statement and "DELETE" in statement
    ]
    for table_name in UNIFIED_RUN_GRANTS:
        assert inventory[table_name].tenant_column == "organization_id"
        assert table_name in sql
        assert not any(table_name in statement for statement in delete_grants)


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="role grants require PostgreSQL")
def test_unified_run_grants_make_a_non_owner_role_rls_ready_without_delete() -> None:
    role = f"unified_grant_{uuid4().hex[:12]}"
    tables = tuple(
        table for table in protected_tenant_tables() if table.table_name in UNIFIED_RUN_GRANTS
    )
    assert len(tables) == len(UNIFIED_RUN_GRANTS)

    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        for table_name, privileges in UNIFIED_RUN_GRANTS.items():
            cursor.execute(  # noqa: S608
                f'GRANT {", ".join(privileges)} ON "{table_name}" TO "{role}"'
            )
    try:
        report = inspect_rls_readiness(app_role=role, tables=tables)
        assert report.ready is True
        assert report.issues == ()

        with connection.cursor() as cursor:
            for table_name in UNIFIED_RUN_GRANTS:
                # Least privilege: no application code deletes these rows, so the role must not be
                # able to erase run lineage or a consumed wait authority.
                cursor.execute("SELECT has_table_privilege(%s, %s, 'DELETE')", [role, table_name])
                assert cursor.fetchone()[0] is False
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP OWNED BY "{role}"')  # noqa: S608
            cursor.execute(f'DROP ROLE "{role}"')  # noqa: S608


_START_NODE = {"id": "start", "type": "input"}
_FORMAT_NODE = {"id": "format", "type": "format_output", "config": {"template_ref": "ok"}}
_END_NODE = {"id": "done", "type": "end"}
_DECISION_SCHEMA = {
    "type": "object",
    "properties": {"approved": {"type": "boolean"}},
    "required": ["approved"],
    "additionalProperties": False,
}


def _human_node(**config) -> dict:
    return {
        "id": "review",
        "type": "human_task",
        "config": {
            "decision_schema": _DECISION_SCHEMA,
            "timeout_seconds": 60,
            **config,
        },
        "output_mapping": [{"from": "/payload/approved", "to": "/decisions/approved"}],
    }


def _scenario_approver(workflow_fixture, username: str = "reviewer"):
    user = get_user_model().objects.create_user(username=username)
    membership = OrganizationMembership.objects.create(
        organization=workflow_fixture.organization,
        user=user,
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=workflow_fixture.organization,
        scenario=workflow_fixture.scenario,
        membership=membership,
        responsibility=ScenarioResponsibility.APPROVER,
        assigned_by=user,
    )
    return user


def _install_graph(workflow_fixture, nodes: list[dict], edges: list[dict]) -> None:
    """Compile an authored graph onto the pinned version, leaving its release checksum intact."""
    from apps.workflows.compiler import compile_workflow

    compiled = compile_workflow(
        {
            "api_version": "agenthub/v1",
            "kind": "Workflow",
            "metadata": {"id": "wait_flow.v1"},
            "spec": {"input_node": "start", "nodes": nodes, "edges": edges},
        }
    )
    WorkflowVersion.objects.filter(scenario=workflow_fixture.scenario).update(
        compiled_graph=compiled.graph
    )


def _execute_queued(run: Run):
    token = uuid4()
    claim_background_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
        lease_seconds=30,
    )
    return execute_claimed_bounded_run(
        organization_id=run.organization_id,
        run_id=run.id,
        claim_token=token,
    )


@pytest.mark.django_db
def test_bounded_executor_suspends_at_a_human_task_and_resumes_at_the_successor(
    workflow_fixture,
    monkeypatch,
) -> None:
    from apps.workflows import unified_executor

    _install_graph(
        workflow_fixture,
        [_START_NODE, _human_node(), _FORMAT_NODE, _END_NODE],
        [
            {"from": "start", "to": "review"},
            {"from": "review", "to": "format"},
            {"from": "format", "to": "done"},
        ],
    )
    run = _queued_background_run(workflow_fixture, key="executor-human-task")
    seen: list[tuple[str, list[str]]] = []
    original = unified_executor._execute_node

    def record(**kwargs):
        seen.append((kwargs["node"]["id"], sorted(kwargs["state"])))
        return original(**kwargs)

    monkeypatch.setattr(unified_executor, "_execute_node", record)

    suspended = _execute_queued(run)
    assert suspended.status == "waiting_human"
    assert suspended.resume_token is not None
    run.refresh_from_db()
    assert run.awaiting_reference == str(suspended.wait_id)
    assert run.step_count == 2
    assert run.background_claim_token is None
    wait = RunWait.objects.get(pk=suspended.wait_id, run_id=run.id)
    assert wait.status == RunWaitStatus.PENDING
    assert wait.node_id == "review"
    # The resume cursor is server-owned state, so it must survive the pause on the durable
    # checkpoint and never be handed to a node.
    assert run.checkpoint["__resume_node"] == "format"

    with pytest.raises(RunWaitError, match="RUN_WAIT_NOT_FOUND"):
        resume_run_wait(
            organization_id=run.organization_id,
            resume_token=suspended.resume_token,
            actor_id="reviewer",
            payload={"approved": True},
        )
    decide_run_human_task(
        organization_id=run.organization_id,
        wait_id=suspended.wait_id,
        actor=_scenario_approver(workflow_fixture),
        payload={"approved": True},
    )
    run.refresh_from_db()
    assert run.status == "queued"
    completed = _execute_queued(run)
    assert completed.status == "completed"
    run.refresh_from_db()
    assert run.checkpoint["decisions"] == {"approved": True}
    assert run.checkpoint["output"] == {"answer": "ok", "sources": []}
    assert "__resume_node" not in run.checkpoint
    # The wait node ran once and the pre-wait prefix was not replayed.
    assert [node_id for node_id, _ in seen] == ["start", "format", "done"]
    assert all("__resume_node" not in state for _, state in seen)
    assert run.step_count == 4


@pytest.mark.django_db
def test_authorized_operator_decides_human_wait_without_resume_token(
    workflow_fixture,
) -> None:
    _install_graph(
        workflow_fixture,
        [_START_NODE, _human_node(), _FORMAT_NODE, _END_NODE],
        [
            {"from": "start", "to": "review"},
            {"from": "review", "to": "format"},
            {"from": "format", "to": "done"},
        ],
    )
    run = _queued_background_run(workflow_fixture, key="operator-human-task")
    suspended = _execute_queued(run)
    assert suspended.wait_id is not None
    approver = _scenario_approver(workflow_fixture)

    decided = decide_run_human_task(
        organization_id=run.organization_id,
        wait_id=suspended.wait_id,
        actor=approver,
        payload={"approved": True},
    )

    assert decided.outcome == "committed"
    run.refresh_from_db()
    assert run.status == RunStatus.QUEUED
    assert RunWait.objects.get(pk=suspended.wait_id).consumed_by == "reviewer"


@pytest.mark.django_db
def test_bounded_executor_suspends_at_event_and_timer_waits(workflow_fixture) -> None:
    _install_graph(
        workflow_fixture,
        [
            _START_NODE,
            {
                "id": "external",
                "type": "event_wait",
                "config": {
                    "event_role": "evidence_ready",
                    "payload_schema": _DECISION_SCHEMA,
                    "timeout_seconds": 60,
                },
                "output_mapping": [{"from": "/payload/approved", "to": "/decisions/approved"}],
            },
            {"id": "delay", "type": "timer", "config": {"delay_seconds": 30}},
            _FORMAT_NODE,
            _END_NODE,
        ],
        [
            {"from": "start", "to": "external"},
            {"from": "external", "to": "delay"},
            {"from": "delay", "to": "format"},
            {"from": "format", "to": "done"},
        ],
    )
    run = _queued_background_run(workflow_fixture, key="executor-event-timer")

    event_wait = _execute_queued(run)
    assert event_wait.status == "waiting_event"
    assert RunWait.objects.get(pk=event_wait.wait_id).kind == "event"
    assert event_wait.resume_token is not None
    resume_run_wait(
        organization_id=run.organization_id,
        resume_token=event_wait.resume_token,
        actor_id="consumer:producer",
        payload={"approved": True},
    )
    run.refresh_from_db()

    timer_wait = _execute_queued(run)
    assert timer_wait.status == "waiting_timer"
    assert RunWait.objects.get(pk=timer_wait.wait_id).kind == "timer"
    assert timer_wait.resume_token is not None
    run.refresh_from_db()
    assert run.checkpoint["__resume_node"] == "format"
    resume_run_wait(
        organization_id=run.organization_id,
        resume_token=timer_wait.resume_token,
        actor_id="system:timer",
        payload={},
    )
    run.refresh_from_db()

    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    assert run.checkpoint["output"] == {"answer": "ok", "sources": []}
    assert run.step_count == 5


@pytest.mark.django_db
def test_compiler_refuses_an_authored_role_escalation_contract(
    workflow_fixture,
) -> None:
    with pytest.raises(WorkflowCompileError, match="human_task config contains unknown fields"):
        _install_graph(
            workflow_fixture,
            [
                _START_NODE,
                _human_node(escalation_role="manager", escalation_timeout_seconds=120),
                _FORMAT_NODE,
                _END_NODE,
            ],
            [
                {"from": "start", "to": "review"},
                {"from": "review", "to": "format"},
                {"from": "format", "to": "done"},
            ],
        )


_RETRIEVE_NODE = {"id": "recall", "type": "retrieve"}
_GENERATE_NODE = {"id": "answer", "type": "generate"}
_RAG_EDGES = [
    {"from": "start", "to": "recall"},
    {"from": "recall", "to": "answer"},
    {"from": "answer", "to": "done"},
]


@pytest.mark.django_db
def test_bounded_executor_runs_retrieve_and_generate_through_the_governed_seams(
    workflow_fixture,
) -> None:
    _install_graph(
        workflow_fixture, [_START_NODE, _RETRIEVE_NODE, _GENERATE_NODE, _END_NODE], _RAG_EDGES
    )
    run = _queued_background_run(workflow_fixture, key="executor-rag")
    run.checkpoint = {"input": {"query": "what is the policy"}}
    run.redacted_state = {"input": {"query": "[redacted]"}}
    run.save(update_fields=["checkpoint", "redacted_state"])

    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    # Default per-node writes: retrieval evidence stays in its own root and never leaks into output.
    assert isinstance(run.checkpoint["retrieval"], dict)
    assert set(run.checkpoint["output"]) == {"answer", "sources"}
    assert run.step_count == 4


@pytest.mark.django_db
def test_bounded_executor_routes_rag_nodes_through_typed_mappings(workflow_fixture) -> None:
    _install_graph(
        workflow_fixture,
        [
            _START_NODE,
            {
                **_RETRIEVE_NODE,
                "input_mapping": [{"from": "/input/query", "to": "/query"}],
                "output_mapping": [{"from": "/chunks", "to": "/retrieval/chunks"}],
            },
            {
                **_GENERATE_NODE,
                "output_mapping": [
                    {"from": "/answer", "to": "/output/answer"},
                    {"from": "/sources", "to": "/output/sources"},
                ],
            },
            _END_NODE,
        ],
        _RAG_EDGES,
    )
    run = _queued_background_run(workflow_fixture, key="executor-rag-mapped")
    run.checkpoint = {"input": {"query": "what is the policy"}}
    run.redacted_state = {"input": {"query": "[redacted]"}}
    run.save(update_fields=["checkpoint", "redacted_state"])

    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    # Only the selected fields are written; the retrieval envelope's other keys are dropped.
    assert set(run.checkpoint["retrieval"]) == {"chunks"}
    assert set(run.checkpoint["output"]) == {"answer", "sources"}


@pytest.mark.django_db
def test_bounded_executor_fails_closed_on_an_unpinned_transform_profile(workflow_fixture) -> None:
    _install_graph(
        workflow_fixture,
        [
            _START_NODE,
            {
                "id": "shape",
                "type": "transform",
                "config": {"transform_profile_ref": "not_pinned"},
                "input_mapping": [{"from": "/input", "to": "/documents"}],
                "output_mapping": [{"from": "/result", "to": "/evidence/shaped"}],
            },
            _FORMAT_NODE,
            _END_NODE,
        ],
        [
            {"from": "start", "to": "shape"},
            {"from": "shape", "to": "format"},
            {"from": "format", "to": "done"},
        ],
    )
    run = _queued_background_run(workflow_fixture, key="executor-transform")
    run.checkpoint = {"input": {"query": "shape me"}}
    run.redacted_state = {"input": {"query": "[redacted]"}}
    run.save(update_fields=["checkpoint", "redacted_state"])

    assert _execute_queued(run).status == "failed"
    run.refresh_from_db()
    # There is no ambient profile fallback: an unpinned governed transform stops the Run.
    assert run.error_code == "WORKFLOW_TRANSFORM_PROFILE_UNRESOLVED"


@pytest.mark.django_db
def test_bounded_executor_retries_only_declared_transient_idempotent_nodes(
    workflow_fixture, monkeypatch
) -> None:
    _install_graph(
        workflow_fixture,
        [
            _START_NODE,
            {
                "id": "recall",
                "type": "retrieve",
                "retry_policy": {
                    "max_attempts": 2,
                    "backoff_seconds": 0,
                    "retry_on": ["transient"],
                    "idempotent": True,
                },
            },
            _FORMAT_NODE,
            _END_NODE,
        ],
        [
            {"from": "start", "to": "recall"},
            {"from": "recall", "to": "format"},
            {"from": "format", "to": "done"},
        ],
    )
    attempts = 0

    def flaky_node(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            from apps.workflows.runtime import WorkflowRuntimeError

            raise WorkflowRuntimeError("WORKFLOW_RETRIEVAL_FAILED")
        return {"chunks": [], "citations": []}

    monkeypatch.setattr("apps.workflows.unified_executor._execute_eligible_node", flaky_node)
    run = _queued_background_run(workflow_fixture, key="executor-retry")
    run.checkpoint = {"input": {"query": "retry"}}
    run.save(update_fields=["checkpoint"])

    assert _execute_queued(run).status == "completed"
    assert attempts == 2
    assert (
        RunEvent.objects.filter(
            run=run,
            event_type=RunEventType.NODE_RETRIED,
            node_id="recall",
            reason_code="WORKFLOW_RETRIEVAL_FAILED",
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_bounded_executor_compensates_completed_side_effects_in_reverse_intent_order(
    workflow_fixture, monkeypatch
) -> None:
    from apps.tools.models import ToolInvocationStatus
    from apps.workflows.runtime import WorkflowRuntimeError

    _install_graph(
        workflow_fixture,
        [
            _START_NODE,
            {
                "id": "act",
                "type": "tool",
                "config": {"binding_role": "tool_binding.act", "output_key": "tool_result"},
                "compensation": "undo",
            },
            {
                "id": "fail",
                "type": "transform",
                "config": {"transform_profile_ref": "missing"},
                "input_mapping": [{"from": "/input", "to": "/documents"}],
                "output_mapping": [{"from": "/result", "to": "/evidence/fail"}],
            },
            _FORMAT_NODE,
            _END_NODE,
            {
                "id": "undo",
                "type": "transform",
                "config": {"transform_profile_ref": "undo"},
                "input_mapping": [{"from": "/tool_result", "to": "/documents"}],
                "output_mapping": [{"from": "/result", "to": "/evidence/undo"}],
            },
        ],
        [
            {"from": "start", "to": "act"},
            {"from": "act", "to": "fail"},
            {"from": "fail", "to": "format"},
            {"from": "format", "to": "done"},
        ],
    )
    monkeypatch.setattr(
        "apps.workflows.unified_executor._invoke_tool",
        lambda **_kwargs: SimpleNamespace(
            status=ToolInvocationStatus.COMPLETED,
            redacted_output={"status": "created"},
        ),
    )

    def transform(**kwargs):
        if kwargs["node"]["id"] == "fail":
            raise WorkflowRuntimeError("WORKFLOW_TRANSFORM_PROFILE_UNRESOLVED")
        return {"result": {"status": "reverted"}}

    monkeypatch.setattr("apps.workflows.unified_executor._execute_eligible_node", transform)
    run = _queued_background_run(workflow_fixture, key="executor-compensation")
    run.checkpoint = {"input": {"query": "act"}}
    run.save(update_fields=["checkpoint"])

    assert _execute_queued(run).status == "failed"
    run.refresh_from_db()
    assert run.error_code == "WORKFLOW_TRANSFORM_PROFILE_UNRESOLVED"
    entry = RunCompensationEntry.objects.get(run=run, source_node_id="act")
    assert (entry.compensation_node_id, entry.status) == (
        "undo",
        RunCompensationStatus.COMPLETED,
    )
    assert (
        RunEvent.objects.filter(
            run=run,
            event_type=RunEventType.COMPENSATION,
            node_id="undo",
            outcome=RunCompensationStatus.COMPLETED,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_bounded_executor_denies_a_custom_node_the_organization_never_allowlisted(
    workflow_fixture,
) -> None:
    _install_graph(
        workflow_fixture,
        [
            _START_NODE,
            {"id": "plugin", "type": "custom", "config": {"node_ref": "unknown_plugin.v1"}},
            _FORMAT_NODE,
            _END_NODE,
        ],
        [
            {"from": "start", "to": "plugin"},
            {"from": "plugin", "to": "format"},
            {"from": "format", "to": "done"},
        ],
    )
    run = _queued_background_run(workflow_fixture, key="executor-custom")

    assert _execute_queued(run).status == "failed"
    run.refresh_from_db()
    # The unified executor reaches the same deny-by-default custom-node registry as the legacy one.
    assert run.error_code == "CUSTOM_NODE_NOT_ALLOWED"
