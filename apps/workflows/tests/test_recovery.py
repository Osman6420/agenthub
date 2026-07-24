from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.audit.models import AuditEvent
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.compiler import WorkflowCompileError, compile_workflow
from apps.workflows.models import (
    WorkflowCompensationEntry,
    WorkflowCompensationStatus,
    WorkflowNodeAttempt,
    WorkflowNodeAttemptStatus,
    WorkflowRecoveryCase,
    WorkflowRecoveryStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from apps.workflows.recovery import classify_failure, retry_decision, select_error_route
from apps.workflows.recovery_services import (
    WorkflowRecoveryError,
    decide_recovery_case,
    open_recovery_case,
)
from apps.workflows.services import resolve_release_workflow


def recovery_workflow() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "recovery.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "generate",
                    "type": "generate",
                    "retry_policy": {
                        "max_attempts": 3,
                        "backoff_seconds": 2,
                        "retry_on": ["transient"],
                        "idempotent": True,
                    },
                },
                {"id": "error", "type": "format_output", "config": {"template_ref": "err"}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "generate"},
                {"from": "generate", "to": "done"},
                {"from": "generate", "on_error": "transient", "to": "error"},
                {"from": "error", "to": "done"},
            ],
        },
    }


def test_compiler_normalizes_bounded_retry_and_error_route() -> None:
    graph = compile_workflow(recovery_workflow()).graph
    generate = next(node for node in graph["nodes"] if node["id"] == "generate")
    assert generate["retry_policy"]["max_attempts"] == 3
    assert next(edge for edge in graph["edges"] if edge.get("on_error"))["on_error"] == "transient"


def test_compiler_rejects_ambiguous_or_unsafe_retry() -> None:
    body = recovery_workflow()
    body["spec"]["edges"].append({"from": "generate", "on_error": "transient", "to": "done"})
    with pytest.raises(WorkflowCompileError, match="WORKFLOW_ERROR_ROUTE_AMBIGUOUS"):
        compile_workflow(body)
    body = recovery_workflow()
    body["spec"]["nodes"][1]["retry_policy"]["retry_on"] = ["outcome_unknown"]
    with pytest.raises(WorkflowCompileError, match="WORKFLOW_RETRY_POLICY_INVALID"):
        compile_workflow(body)


def test_compensation_target_is_pinned_and_not_reachable_from_normal_graph() -> None:
    mapping_in = [{"from": "/input", "to": "/input"}]
    mapping_out = [{"from": "/result", "to": "/output"}]
    body: Any = {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "compensated.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "apply",
                    "type": "tool",
                    "config": {"binding_role": "apply"},
                    "input_mapping": mapping_in,
                    "output_mapping": mapping_out,
                    "compensation": "undo",
                },
                {
                    "id": "undo",
                    "type": "tool",
                    "config": {"binding_role": "undo"},
                    "input_mapping": mapping_in,
                    "output_mapping": mapping_out,
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "apply"},
                {"from": "apply", "to": "done"},
                {"from": "undo", "to": "done"},
            ],
        },
    }
    assert compile_workflow(body).graph["api_version"].endswith("/v5")
    body["spec"]["edges"].append({"from": "request", "to": "undo"})
    with pytest.raises(WorkflowCompileError, match="WORKFLOW_COMPENSATION_INVALID"):
        compile_workflow(body)


def test_failure_classification_retry_and_route_are_fail_closed() -> None:
    assert classify_failure("TOOL_OUTCOME_UNKNOWN") == "outcome_unknown"
    assert classify_failure("TOOL_CAPABILITY_DENIED") == "authorization"
    assert classify_failure("INPUT_CONTRACT_VIOLATION") == "validation"
    assert classify_failure("WORKFLOW_GENERATION_FAILED") == "transient"
    assert classify_failure("UNRECOGNIZED_PROVIDER_TEXT") == "permanent"
    policy = {
        "max_attempts": 3,
        "backoff_seconds": 2,
        "retry_on": ["transient"],
        "idempotent": True,
    }
    assert retry_decision(policy=policy, failure_class="transient", completed_attempts=1).allowed
    assert not retry_decision(
        policy=policy, failure_class="outcome_unknown", completed_attempts=1
    ).allowed
    assert (
        select_error_route(
            edges=[
                {"from": "n", "to": "fallback", "on_error": "any"},
                {"from": "n", "to": "exact", "on_error": "transient"},
            ],
            node_id="n",
            failure_class="transient",
        )
        == "exact"
    )


def _run(workflow_fixture, key: str) -> WorkflowRun:
    workflow_version = resolve_release_workflow(workflow_fixture.release)
    return WorkflowRun.objects.create(
        organization=workflow_fixture.organization,
        scenario=workflow_fixture.scenario,
        release=workflow_fixture.release,
        workflow_version=workflow_version,
        consumer=workflow_fixture.consumer,
        idempotency_key=key,
        input_checksum=compute_checksum({"query": "safe"}),
        execution_context={},
        redacted_state={"input": {"query": "[redacted]"}},
        status=WorkflowRunStatus.RUNNING,
        deadline_at=timezone.now() + timedelta(minutes=5),
    )


@pytest.mark.django_db
def test_only_org_admin_can_resolve_system_opened_case(workflow_fixture) -> None:
    run = _run(workflow_fixture, "recovery-admin")
    case = open_recovery_case(
        run=run,
        node_id="tool",
        failure_class="outcome_unknown",
        reason_code="TOOL_OUTCOME_UNKNOWN",
        high_risk=False,
    )
    user_model = get_user_model()
    author = user_model.objects.create_user(username="recovery-author")
    OrganizationMembership.objects.create(
        organization=workflow_fixture.organization, user=author, role=Role.SCENARIO_EDITOR
    )
    with pytest.raises(WorkflowRecoveryError, match="RECOVERY_AUTHORIZATION_DENIED"):
        decide_recovery_case(
            recovery_public_id=case.public_id,
            actor=author,
            action="terminate_failed",
            reason="checked externally",
            expected_revision=case.revision,
            expected_state_checksum=case.state_checksum,
        )
    assert AuditEvent.objects.filter(
        action="workflow.recovery_decide", outcome="deny", actor_id=str(author.pk)
    ).exists()
    other_org = Organization.objects.create(slug="recovery-other", name="Recovery Other")
    foreign_admin = user_model.objects.create_user(username="recovery-foreign-admin")
    OrganizationMembership.objects.create(
        organization=other_org, user=foreign_admin, role=Role.ORGANIZATION_ADMIN
    )
    with pytest.raises(WorkflowRecoveryError, match="RECOVERY_AUTHORIZATION_DENIED"):
        decide_recovery_case(
            recovery_public_id=case.public_id,
            actor=foreign_admin,
            action="terminate_failed",
            reason="foreign operation",
            expected_revision=case.revision,
            expected_state_checksum=case.state_checksum,
        )
    admin = user_model.objects.create_user(username="recovery-admin")
    OrganizationMembership.objects.create(
        organization=workflow_fixture.organization, user=admin, role=Role.ORGANIZATION_ADMIN
    )
    decided = decide_recovery_case(
        recovery_public_id=case.public_id,
        actor=admin,
        action="terminate_failed",
        reason="checked externally",
        expected_revision=case.revision,
        expected_state_checksum=case.state_checksum,
    )
    assert decided.status == WorkflowRecoveryStatus.RESOLVED
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.FAILED


@pytest.mark.django_db
def test_high_risk_compensation_requires_two_distinct_admins(workflow_fixture) -> None:
    run = _run(workflow_fixture, "recovery-dual")
    case = open_recovery_case(
        run=run,
        node_id="compensate",
        failure_class="outcome_unknown",
        reason_code="TOOL_OUTCOME_UNKNOWN",
        high_risk=True,
    )
    WorkflowCompensationEntry.objects.create(
        organization=workflow_fixture.organization,
        run=run,
        sequence=1,
        source_node_id="source",
        compensation_node_id="compensate",
        input_checksum=compute_checksum(run.redacted_state),
    )
    user_model = get_user_model()
    admins = []
    for ordinal in (1, 2):
        admin = user_model.objects.create_user(username=f"recovery-admin-{ordinal}")
        OrganizationMembership.objects.create(
            organization=workflow_fixture.organization,
            user=admin,
            role=Role.ORGANIZATION_ADMIN,
        )
        admins.append(admin)
    first = decide_recovery_case(
        recovery_public_id=case.public_id,
        actor=admins[0],
        action="resume_compensation",
        reason="first independent check",
        expected_revision=case.revision,
        expected_state_checksum=case.state_checksum,
    )
    assert first.status == WorkflowRecoveryStatus.AWAITING_SECOND_APPROVAL
    second = decide_recovery_case(
        recovery_public_id=case.public_id,
        actor=admins[1],
        action="resume_compensation",
        reason="second independent check",
        expected_revision=case.revision,
        expected_state_checksum=case.state_checksum,
    )
    assert second.status == WorkflowRecoveryStatus.RESOLVED
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.QUEUED


@pytest.mark.django_db
def test_transient_retry_is_durable_bounded_and_resumes(
    workflow_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.workflows import runtime

    run = _run(workflow_fixture, "recovery-retry")
    compiled = compile_workflow(recovery_workflow())
    type(run.workflow_version).objects.filter(pk=run.workflow_version_id).update(
        compiled_graph=compiled.graph,
        checksum=compiled.checksum,
        compiler_version="workflow-compiler/v5",
    )
    run.workflow_version.refresh_from_db()
    calls = 0

    def flaky(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise runtime.WorkflowRuntimeError("WORKFLOW_GENERATION_FAILED")
        return {"answer": "recovered", "sources": []}

    monkeypatch.setattr(runtime, "_execute_eligible_node", flaky)
    with pytest.raises(runtime.WorkflowRetryPending) as pending:
        runtime.execute_graph(run=run, verify_context=False)
    assert pending.value.countdown_seconds == 2
    first = WorkflowNodeAttempt.objects.get(run=run, node_id="generate", ordinal=1)
    assert first.status == WorkflowNodeAttemptStatus.RETRY_WAIT
    run.refresh_from_db()
    result = runtime.execute_graph(run=run, verify_context=False)
    assert result.output["answer"] == "recovered"
    assert (
        WorkflowNodeAttempt.objects.get(run=run, node_id="generate", ordinal=2).status
        == WorkflowNodeAttemptStatus.SUCCEEDED
    )


@pytest.mark.django_db
def test_compensation_stack_runs_in_reverse_and_is_terminally_idempotent(
    workflow_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.workflows import runtime

    run = _run(workflow_fixture, "recovery-compensation")
    state = {"input": {"query": "[redacted]"}}
    for sequence, node_id in ((1, "undo-first"), (2, "undo-second")):
        WorkflowCompensationEntry.objects.create(
            organization=workflow_fixture.organization,
            run=run,
            sequence=sequence,
            source_node_id=f"source-{sequence}",
            compensation_node_id=node_id,
            input_checksum=compute_checksum(state),
        )
    called: list[str] = []

    def compensate(*, node, state, run, resuming):
        del run, resuming
        called.append(node["id"])
        return state

    monkeypatch.setattr(runtime, "_run_eligible_node", compensate)
    nodes = {
        node_id: {
            "id": node_id,
            "type": "transform",
            "config": {"transform_profile_ref": "undo"},
            "input_mapping": [{"from": "/input", "to": "/input"}],
            "output_mapping": [{"from": "/output", "to": "/output"}],
        }
        for node_id in ("undo-first", "undo-second")
    }
    runtime._run_compensations(run=run, nodes=nodes, state=state)
    runtime._run_compensations(run=run, nodes=nodes, state=state)
    assert called == ["undo-second", "undo-first"]
    assert set(
        WorkflowCompensationEntry.objects.filter(run=run).values_list("status", flat=True)
    ) == {WorkflowCompensationStatus.SUCCEEDED}


@pytest.mark.skipif(connection.vendor != "postgresql", reason="FORCE RLS requires PostgreSQL")
@pytest.mark.django_db
def test_recovery_case_force_rls_blocks_cross_tenant(workflow_fixture) -> None:
    run = _run(workflow_fixture, "recovery-rls")
    case = open_recovery_case(
        run=run,
        node_id="tool",
        failure_class="outcome_unknown",
        reason_code="TOOL_OUTCOME_UNKNOWN",
        high_risk=False,
    )
    table = WorkflowRecoveryCase._meta.db_table
    role = "rls_probe_recovery"
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        if cursor.fetchone():
            cursor.execute(f"DROP OWNED BY {role}")
            cursor.execute(f"DROP ROLE {role}")
        cursor.execute(f"CREATE ROLE {role} NOSUPERUSER NOLOGIN")
        cursor.execute(f'GRANT SELECT ON "{table}" TO {role}')
        cursor.execute(
            f"GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO {role}"
        )
        cursor.execute(
            "SELECT set_config('app.tenant_scope', %s, true)",
            [str(workflow_fixture.organization.id)],
        )
        cursor.execute(f"SET ROLE {role}")
        cursor.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id = %s', [case.id])  # noqa: S608
        assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", ["99999999"])
        cursor.execute(f"SET ROLE {role}")
        cursor.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id = %s', [case.id])  # noqa: S608
        assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")
        cursor.execute(f"DROP OWNED BY {role}")
        cursor.execute(f"DROP ROLE {role}")


@pytest.mark.django_db
def test_recovery_console_is_csrf_protected_and_org_admin_scoped(workflow_fixture) -> None:
    run = _run(workflow_fixture, "recovery-console")
    case = open_recovery_case(
        run=run,
        node_id="tool",
        failure_class="outcome_unknown",
        reason_code="TOOL_OUTCOME_UNKNOWN",
        high_risk=False,
    )
    user_model = get_user_model()
    admin = user_model.objects.create_user(username="console-recovery-admin")
    OrganizationMembership.objects.create(
        organization=workflow_fixture.organization, user=admin, role=Role.ORGANIZATION_ADMIN
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin)
    list_response = client.get(reverse("console:workflow_recoveries"))
    assert list_response.status_code == 200
    assert str(case.public_id) in list_response.content.decode()
    path = reverse("console:workflow_recovery_decide", args=[case.public_id])
    payload = {
        "action": "terminate_failed",
        "reason": "verified by operations",
        "revision": str(case.revision),
        "state_checksum": case.state_checksum,
    }
    assert client.post(path, payload).status_code == 403
    token = client.cookies["csrftoken"].value
    response = client.post(path, payload, HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 302
    run.refresh_from_db()
    assert run.status == WorkflowRunStatus.FAILED
