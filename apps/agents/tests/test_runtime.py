"""Bounded, guarded agent decision-loop behavior and fail-closed governance."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.agents.models import AgentRun, AgentRunStatus
from apps.agents.planner import DECISION_RESPOND, DECISION_TOOL, AgentDecision
from apps.agents.runtime import (
    AgentRuntimeError,
    _validate_decision,
    execute_agent,
    run_embedded_agent_loop,
)
from apps.agents.services import resolve_release_agent
from apps.agents.tasks import execute_agent_run
from apps.agents.tests.conftest import build_agent, make_run
from apps.identity.capabilities import Capability
from apps.tools.approvals import decide_approval
from apps.tools.models import ApprovalRequest, ToolInvocation, ToolInvocationStatus

pytestmark = pytest.mark.django_db

TOOL_CAPS: list[str] = [
    Capability.AGENT_INVOKE,
    Capability.TOOL_CALL,
    Capability.TOOL_CALL_SIDE_EFFECT,
]


def test_respond_completes_and_persists_output() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    assert run.step_count == 1
    assert run.checkpoint["output"]["answer"]
    assert run.checkpoint["output"]["sources"] == []


def test_embedded_agent_loop_runs_tool_free_policy_without_agentrun_persistence() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    result = run_embedded_agent_loop(
        compiled_config=resolve_release_agent(fixture.release).compiled_config,
        release=fixture.release,
        workflow_run=run,
        state=dict(run.checkpoint),
    )

    assert result.output["answer"]
    assert result.steps == 1
    run.refresh_from_db()
    assert run.status == AgentRunStatus.QUEUED
    assert run.step_count == 0


def test_embedded_agent_loop_rejects_tools_until_unified_pause_ownership_exists() -> None:
    fixture = build_agent(with_tool=True)
    run = make_run(fixture, capabilities=TOOL_CAPS)
    with pytest.raises(AgentRuntimeError, match="AGENT_EMBEDDED_TOOLS_UNAVAILABLE"):
        run_embedded_agent_loop(
            compiled_config=resolve_release_agent(fixture.release).compiled_config,
            release=fixture.release,
            workflow_run=run,
            state=dict(run.checkpoint),
        )


def test_retrieval_then_respond() -> None:
    fixture = build_agent(retrieval=True)
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    # retrieve (step 1) + respond (step 2).
    assert run.step_count == 2


def test_cancellation_is_observed_by_the_loop() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    AgentRun.objects.filter(pk=run.pk).update(status=AgentRunStatus.CANCELLED)
    with pytest.raises(AgentRuntimeError) as exc:
        execute_agent(run=run)
    assert exc.value.code == "AGENT_CANCELLED"


def test_deadline_exceeded_times_out() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    AgentRun.objects.filter(pk=run.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.TIMED_OUT
    assert run.error_code == "AGENT_TIMED_OUT"


def test_step_cap_fails_closed() -> None:
    # retrieval enabled with max_steps=1: retrieve consumes step 0, step 1 trips the cap.
    fixture = build_agent(retrieval=True, limits={"max_steps": 1})
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "AGENT_MAX_STEPS"


def test_model_provider_failure_marks_run_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    # A model-generation failure must terminate the run as FAILED with a stable code,
    # never leave it stuck in `running` (the ModelProviderError previously escaped the
    # task's AgentRuntimeError handler).
    from apps.orchestration import rag_steps
    from apps.orchestration.providers import ModelProviderError

    class _FailingProvider:
        def generate(self, **_: object) -> object:
            raise ModelProviderError("UPSTREAM_STATUS")

    monkeypatch.setattr(rag_steps, "get_model_provider", lambda: _FailingProvider())
    fixture = build_agent()
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "AGENT_MODEL_FAILED"


def test_incompatible_checkpoint_never_resumes() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    AgentRun.objects.filter(pk=run.pk).update(checkpoint_version=999)
    run.refresh_from_db()
    with pytest.raises(AgentRuntimeError) as exc:
        execute_agent(run=run)
    assert exc.value.code == "AGENT_CHECKPOINT_INCOMPATIBLE"


def test_validate_decision_blocks_unlisted_tool() -> None:
    # Defense in depth: a planner proposing a tool outside the compiled allowlist is denied.
    config = {"tools": ["search"]}
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(AgentDecision(DECISION_TOOL, role="danger"), config)
    assert exc.value.code == "AGENT_TOOL_NOT_ALLOWED"


def test_validate_decision_blocks_unknown_kind() -> None:
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(AgentDecision("exfiltrate"), {"tools": []})
    assert exc.value.code == "AGENT_DECISION_INVALID"


def test_validate_decision_allows_respond() -> None:
    _validate_decision(AgentDecision(DECISION_RESPOND), {"tools": []})


def test_policy_requires_citations_fails_closed() -> None:
    # citations required + no retrieval -> empty sources -> POLICY_VIOLATION.
    fixture = build_agent(policy_citations_required=True)
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "POLICY_VIOLATION"


def test_high_risk_tool_pauses_then_resumes() -> None:
    fixture = build_agent(with_tool=True)
    run = make_run(fixture, capabilities=TOOL_CAPS)

    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.WAITING_APPROVAL
    assert run.awaiting_role == "search"
    assert run.awaiting_step == 0
    invocation = ToolInvocation.objects.get(consumer=fixture.consumer)
    assert invocation.status == ToolInvocationStatus.PENDING_APPROVAL

    approval = ApprovalRequest.objects.get(invocation=invocation)
    decide_approval(
        approval_id=approval.pk,
        organization_id=fixture.organization.id,
        actor="operator-1",
        actor_roles=["approver"],
        approve=True,
    )
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    assert run.awaiting_role == ""
    assert run.tool_call_count == 1
    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.COMPLETED


def test_rejected_tool_fails_the_run_closed() -> None:
    fixture = build_agent(with_tool=True)
    run = make_run(fixture, capabilities=TOOL_CAPS)
    execute_agent_run(run.id)
    approval = ApprovalRequest.objects.get(invocation__consumer=fixture.consumer)
    decide_approval(
        approval_id=approval.pk,
        organization_id=fixture.organization.id,
        actor="operator-1",
        actor_roles=["approver"],
        approve=False,
    )
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "TOOL_REJECTED"


def test_terminal_run_is_idempotent_on_redelivery() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    first_finished = run.finished_at
    # A redelivered broker message must be a safe no-op.
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    assert run.finished_at == first_finished


def test_missing_run_is_safe_noop() -> None:
    assert execute_agent_run(999_999) == "missing"
