from __future__ import annotations

from datetime import timedelta
from threading import Barrier, Thread
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection
from django.utils import timezone

from apps.agents.services import set_runtime_suspension
from apps.audit.models import AuditEvent
from apps.workflows.background_claims import (
    BackgroundClaimError,
    claim_background_delivery,
    claim_background_run,
    renew_background_claim,
    resolve_expired_background_claim,
)
from apps.workflows.models import (
    Run,
    RunCancellationState,
    RunEvent,
    RunEventType,
    RunExecutionMode,
    WorkflowVersion,
)
from apps.workflows.run_events import append_run_event, validate_run_event_payload
from apps.workflows.transitions import (
    RunTransitionError,
    renew_sync_lease,
    request_run_cancellation,
    resolve_expired_sync_lease,
    transition_run,
)


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
        headers={"organization_id": run.organization_id},
    )
    assert claimed.outcome == "claimed"

    with pytest.raises(
        BackgroundClaimError, match="RUN_BACKGROUND_DELIVERY_BODY_INVALID"
    ):
        claim_background_delivery(
            body={
                "run_id": str(run.id),
                "delivery_token": str(uuid4()),
                "checkpoint": {"forged": True},
            },
            headers={"organization_id": run.organization_id},
        )
    with pytest.raises(Run.DoesNotExist):
        claim_background_delivery(
            body={"run_id": str(run.id), "delivery_token": str(uuid4())},
            headers={"organization_id": run.organization_id + 99_999},
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
        Run.objects.filter(pk=run.id).update(
            deadline_at=timezone.now() - timedelta(seconds=1)
        )

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
    nested = {"safe": {}}
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


@pytest.mark.skipif(connection.vendor != "postgresql", reason="FORCE RLS requires PostgreSQL")
@pytest.mark.django_db
def test_unified_run_tables_force_rls_for_non_owner_role(workflow_fixture) -> None:
    run = _run(workflow_fixture)
    event = append_run_event(run_id=run.id, event_type=RunEventType.REQUESTED)
    role = "rls_probe_unified_run"
    tables = (Run._meta.db_table, RunEvent._meta.db_table)

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
        for table, row_id in ((tables[0], run.id), (tables[1], event.id)):
            cursor.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id = %s', [row_id])  # noqa: S608
            assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", ["99999999"])
        cursor.execute(f"SET ROLE {role}")
        for table, row_id in ((tables[0], run.id), (tables[1], event.id)):
            cursor.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id = %s', [row_id])  # noqa: S608
            assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")
        cursor.execute(f"DROP OWNED BY {role}")
        cursor.execute(f"DROP ROLE {role}")
