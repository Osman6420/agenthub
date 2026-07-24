from __future__ import annotations

from datetime import timedelta
from threading import Barrier, Thread

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection
from django.utils import timezone

from apps.workflows.models import (
    Run,
    RunEvent,
    RunEventType,
    RunExecutionMode,
    WorkflowVersion,
)
from apps.workflows.run_events import append_run_event, validate_run_event_payload
from apps.workflows.transitions import RunTransitionError, transition_run


def _run(workflow_fixture, *, key: str = "unified-run") -> Run:
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
        execution_mode=RunExecutionMode.BACKGROUND,
        deadline_at=timezone.now() + timedelta(minutes=5),
        input_checksum="a" * 64,
    )


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
    run.sync_lease_expires_at = timezone.now() + timedelta(seconds=30)
    with pytest.raises(ValidationError, match="only synchronous"):
        run.full_clean()


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
        expected_checkpoint_version=2,
        expected_status="running",
        target_status="completed",
        checkpoint={"output": {"status": "[redacted]"}},
        output_token_delta=3,
    )
    late = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
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
        expected_checkpoint_version=1,
        target_status="running",
    )

    stale = transition_run(
        organization_id=run.organization_id,
        run_id=run.id,
        expected_checkpoint_version=1,
        target_status="completed",
    )
    assert stale.outcome == "stale"
    with pytest.raises(RunTransitionError, match="RUN_AWAITING_REFERENCE_INVALID"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            expected_checkpoint_version=2,
            target_status="waiting_event",
        )
    with pytest.raises(RunTransitionError, match="RUN_COUNTER_DELTA_INVALID"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            expected_checkpoint_version=2,
            target_status="failed",
            step_delta=-1,
        )
    with pytest.raises(RunTransitionError, match="RUN_CHECKPOINT_TOO_LARGE"):
        transition_run(
            organization_id=run.organization_id,
            run_id=run.id,
            expected_checkpoint_version=2,
            target_status="failed",
            checkpoint={"safe": "x" * (1024 * 1024)},
        )


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
