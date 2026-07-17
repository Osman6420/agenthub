"""P2.6.6 advanced governed agent loop: schema v2, verify/escalate, budgets, repeat/
no-progress guards, bounded redacted observations, and the fail-closed kill switch.

Every planner proposal is untrusted input; these tests prove the runtime re-validates
kind/role/arguments/schema-version, enforces per-role budgets and repeat policy, keeps the
approval/proxy invariants, bounds and redacts planner observations, and that the DB-backed
kill switch denies claim/resume without a restart, org-scoped and role-gated.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.agents.compiler import AgentCompileError, compile_agent
from apps.agents.models import AgentRunEvent, AgentRunStatus, AgentRuntimeControl
from apps.agents.planner import (
    AGENT_DECISION_SCHEMA_VERSION,
    DECISION_ESCALATE,
    DECISION_RESPOND,
    DECISION_RETRIEVE,
    DECISION_TOOL,
    DECISION_VERIFY,
    AgentDecision,
    DecisionParseError,
    parse_decision,
)
from apps.agents.runtime import (
    AgentRuntimeError,
    _validate_decision,
    run_agent_candidate,
)
from apps.agents.services import runtime_suspended, set_runtime_suspension
from apps.agents.tasks import execute_agent_run
from apps.agents.tests.conftest import agent_body, build_agent, make_run
from apps.identity.capabilities import Capability
from apps.releases.compiler import CompileError
from apps.tools.approvals import decide_approval
from apps.tools.models import ApprovalRequest, ToolInvocation, ToolInvocationStatus

pytestmark = pytest.mark.django_db

TOOL_CAPS: list[str] = [
    Capability.AGENT_INVOKE,
    Capability.TOOL_CALL,
    Capability.TOOL_CALL_SIDE_EFFECT,
]


class ScriptedPlanner:
    """Returns decisions by invocation count (clamped to the last), so a soft-denied
    proposal that re-invokes the planner at the same step gets the next scripted move."""

    def __init__(self, decisions: list[AgentDecision]) -> None:
        self._decisions = decisions
        self._calls = 0

    def next_action(self, **_: Any) -> AgentDecision:
        decision = self._decisions[min(self._calls, len(self._decisions) - 1)]
        self._calls += 1
        return decision


def _use_planner(monkeypatch: Any, decisions: list[AgentDecision]) -> None:
    planner = ScriptedPlanner(decisions)
    monkeypatch.setattr("apps.agents.runtime.get_configured_planner", lambda: planner)


# --------------------------------------------------------------------------- schema/compiler


def test_actions_block_compiles_and_is_deterministic() -> None:
    body = agent_body(
        tools=["a", "b"],
        actions={
            "verify_roles": ["b", "a"],
            "role_call_caps": {"b": 2},
            "escalation_enabled": True,
        },
    )
    compiled = compile_agent(body)
    assert compiled.config["decision_schema_version"] == AGENT_DECISION_SCHEMA_VERSION
    # verify_roles and caps are canonicalized (sorted) for a stable checksum.
    assert compiled.config["actions"]["verify_roles"] == ["a", "b"]
    assert compiled.config["actions"]["role_call_caps"] == {"b": 2}
    assert compiled.config["actions"]["escalation_enabled"] is True
    # Reordering authored keys/elements yields the identical checksum.
    reordered = agent_body(
        tools=["a", "b"],
        actions={
            "escalation_enabled": True,
            "role_call_caps": {"b": 2},
            "verify_roles": ["a", "b"],
        },
    )
    assert compile_agent(reordered).checksum == compiled.checksum


def test_legacy_agent_config_unchanged_without_actions() -> None:
    # Compatibility: an agent that does not author actions keeps a byte-identical config
    # and stable checksum (no decision_schema_version / actions keys added).
    compiled = compile_agent(agent_body(tools=["a"]))
    assert "actions" not in compiled.config
    assert "decision_schema_version" not in compiled.config


def test_verify_role_must_reference_declared_tool_or_retrieval() -> None:
    with pytest.raises(AgentCompileError):
        compile_agent(agent_body(tools=["a"], actions={"verify_roles": ["ghost"]}))


def test_verify_retrieval_requires_retrieval_enabled() -> None:
    with pytest.raises(AgentCompileError):
        compile_agent(agent_body(tools=[], actions={"verify_roles": ["retrieval"]}))


def test_role_call_cap_bounds_are_enforced() -> None:
    with pytest.raises(AgentCompileError):
        compile_agent(agent_body(tools=["a"], actions={"role_call_caps": {"a": 999}}))
    with pytest.raises(AgentCompileError):
        compile_agent(agent_body(tools=["a"], actions={"role_call_caps": {"ghost": 1}}))


def test_repeat_retrieval_requires_retrieval() -> None:
    with pytest.raises(AgentCompileError):
        compile_agent(agent_body(tools=[], actions={"repeat_retrieval": True}))


def test_side_effecting_verification_role_rejected_at_release_compile() -> None:
    # "search" is high-risk, side-effecting, approval-required; it can never be a verify role.
    with pytest.raises(CompileError) as exc:
        build_agent(with_tool=True, actions={"verify_roles": ["search"]})
    assert "no-side-effect" in str(exc.value)


def test_no_side_effect_verification_role_compiles_at_release() -> None:
    fixture = build_agent(with_verify_tool=True, actions={"verify_roles": ["check"]})
    cfg = _config(fixture)
    assert cfg["actions"]["verify_roles"] == ["check"]


# --------------------------------------------------------------------------- decision validation


def test_schema_version_mismatch_fails_closed() -> None:
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(AgentDecision(DECISION_RESPOND, schema_version=1), {"tools": []})
    assert exc.value.code == "AGENT_DECISION_SCHEMA_MISMATCH"


def test_verify_denied_without_policy() -> None:
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(AgentDecision(DECISION_VERIFY, role="check"), {"tools": ["check"]})
    assert exc.value.code == "AGENT_VERIFY_NOT_ALLOWED"


def test_escalate_denied_without_policy() -> None:
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(AgentDecision(DECISION_ESCALATE), {"tools": []})
    assert exc.value.code == "AGENT_ESCALATE_NOT_ALLOWED"


def test_composition_allowed_actions_denies_new_kind() -> None:
    # A parent compiled before P2.6.6 never lists verify/escalate: deny by default.
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(
            AgentDecision(DECISION_VERIFY, role="check"),
            {"tools": ["check"]},
            verify_roles=frozenset({"check"}),
            allowed_actions=frozenset({"retrieve", "tool", "respond"}),
        )
    assert exc.value.code == "AGENT_ACTION_NOT_ALLOWED"


def test_arguments_rejected_on_non_role_action() -> None:
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(AgentDecision(DECISION_RESPOND, arguments={"x": 1}), {"tools": []})
    assert exc.value.code == "AGENT_ARGUMENTS_INVALID"


def test_protected_namespace_argument_rejected() -> None:
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(
            AgentDecision(DECISION_TOOL, role="a", arguments={"capabilities": ["x"]}),
            {"tools": ["a"]},
        )
    assert exc.value.code == "AGENT_ARGUMENTS_INVALID"


def test_oversized_arguments_rejected() -> None:
    with pytest.raises(AgentRuntimeError) as exc:
        _validate_decision(
            AgentDecision(DECISION_TOOL, role="a", arguments={"q": "x" * 5000}),
            {"tools": ["a"]},
        )
    assert exc.value.code == "AGENT_ARGUMENTS_INVALID"


def test_parse_decision_rejects_unknown_keys_and_bad_types() -> None:
    with pytest.raises(DecisionParseError):
        parse_decision({"kind": "tool", "role": "a", "evil": 1})
    with pytest.raises(DecisionParseError):
        parse_decision({"kind": "tool", "arguments": "not-a-dict"})
    with pytest.raises(DecisionParseError):
        parse_decision({"kind": "tool", "schema_version": "two"})
    parsed = parse_decision({"kind": "tool", "role": "a", "arguments": {"query": "x"}})
    assert parsed.kind == "tool" and parsed.arguments == {"query": "x"}


# ------------------------------------------------------------------------------- verify/escalate


def test_deterministic_verify_retrieval_trajectory() -> None:
    fixture = build_agent(retrieval=True, actions={"verify_roles": ["retrieval"]})
    result = run_agent_candidate(release=fixture.release, input_payload={"query": "hi"})
    assert result.status == "completed"
    assert result.metadata["decisions"] == [
        DECISION_RETRIEVE,
        DECISION_VERIFY,
        DECISION_RESPOND,
    ]


def test_escalate_is_a_distinct_audited_terminal(monkeypatch: Any) -> None:
    fixture = build_agent(actions={"escalation_enabled": True})
    _use_planner(monkeypatch, [AgentDecision(DECISION_ESCALATE, reason_code="needs_human")])
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "AGENT_ESCALATED"
    assert run.checkpoint["_escalation"] == {"reason_code": "needs_human", "steps": 0}
    assert AgentRunEvent.objects.filter(run=run, event_type="run_escalated").exists()


def test_escalation_envelope_sanitizes_free_text(monkeypatch: Any) -> None:
    fixture = build_agent(actions={"escalation_enabled": True})
    _use_planner(monkeypatch, [AgentDecision(DECISION_ESCALATE, reason_code="leak secret token!!")])
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    # A non-identifier reason collapses to the safe default; no free text is stored.
    assert run.checkpoint["_escalation"]["reason_code"] == "escalated"


def test_verify_over_no_side_effect_tool(monkeypatch: Any) -> None:
    fixture = build_agent(with_verify_tool=True, actions={"verify_roles": ["check"]})
    _use_planner(
        monkeypatch,
        [AgentDecision(DECISION_VERIFY, role="check"), AgentDecision(DECISION_RESPOND)],
    )
    run = make_run(fixture, capabilities=[Capability.AGENT_INVOKE, Capability.TOOL_CALL])
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    summaries = run.checkpoint["_summaries"]
    verify = [s for s in summaries if s["kind"] == DECISION_VERIFY][0]
    assert verify["role"] == "check"
    assert verify["outcome"] in {"verified", "inconclusive"}


# ------------------------------------------------------------------- repeat / budget / no-progress


def test_repeated_action_denied_but_run_recovers(monkeypatch: Any) -> None:
    fixture = build_agent(with_verify_tool=True, actions={})
    _use_planner(
        monkeypatch,
        [
            AgentDecision(DECISION_TOOL, role="check"),
            AgentDecision(DECISION_TOOL, role="check"),  # identical repeat, cap=1 -> soft denial
            AgentDecision(DECISION_RESPOND),
        ],
    )
    run = make_run(fixture, capabilities=[Capability.AGENT_INVOKE, Capability.TOOL_CALL])
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    denials = AgentRunEvent.objects.filter(run=run, event_type="decision_denied")
    assert denials.filter(reason_code="AGENT_REPEATED_ACTION").exists()


def test_no_progress_terminates(monkeypatch: Any) -> None:
    fixture = build_agent(with_verify_tool=True)
    _use_planner(monkeypatch, [AgentDecision(DECISION_TOOL, role="check")])  # always repeats
    with pytest.raises(AgentRuntimeError) as exc:
        run_agent_candidate(release=fixture.release, input_payload={"query": "hi"})
    assert exc.value.code == "AGENT_NO_PROGRESS"


def test_role_budget_allows_bounded_repeat(monkeypatch: Any) -> None:
    fixture = build_agent(with_verify_tool=True, actions={"role_call_caps": {"check": 2}})
    _use_planner(
        monkeypatch,
        [
            AgentDecision(DECISION_TOOL, role="check", arguments={"query": "a"}),
            AgentDecision(DECISION_TOOL, role="check", arguments={"query": "b"}),
            AgentDecision(DECISION_RESPOND),
        ],
    )
    run = make_run(fixture, capabilities=[Capability.AGENT_INVOKE, Capability.TOOL_CALL])
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    assert run.checkpoint["_role_calls"]["check"] == 2


def test_budget_exceeded_beyond_cap(monkeypatch: Any) -> None:
    fixture = build_agent(with_verify_tool=True)  # default cap 1
    _use_planner(
        monkeypatch,
        [
            AgentDecision(DECISION_TOOL, role="check", arguments={"query": "a"}),
            AgentDecision(DECISION_TOOL, role="check", arguments={"query": "b"}),  # different args
        ],
    )
    with pytest.raises(AgentRuntimeError) as exc:
        # candidate seam: consumer-less; a second (different-args) call trips the role budget.
        run_agent_candidate(release=fixture.release, input_payload={"query": "hi"})
    assert exc.value.code == "AGENT_NO_PROGRESS"  # bounded soft denials terminate


# ------------------------------------------------------------------------- argument dual validation


def test_runtime_prevalidates_arguments_before_proxy(monkeypatch: Any) -> None:
    fixture = build_agent(with_tool=True)
    _use_planner(
        monkeypatch,
        [AgentDecision(DECISION_TOOL, role="search", arguments={"evil": "x"})],
    )
    run = make_run(fixture, capabilities=TOOL_CAPS)
    execute_agent_run(run.id)
    run.refresh_from_db()
    # The runtime rejects the disallowed field before any proxy/approval record is created.
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "TOOL_INPUT_FIELD_NOT_ALLOWED"
    assert not ToolInvocation.objects.filter(consumer=fixture.consumer).exists()


# ------------------------------------------------------------------------------ observation budget


def test_observations_are_code_count_only() -> None:
    fixture = build_agent(retrieval=True, actions={"verify_roles": ["retrieval"]})
    result = run_agent_candidate(release=fixture.release, input_payload={"query": "secret text"})
    # Trajectory persisted the redacted summaries; assert only codes/counts, no free text.
    assert result.status == "completed"
    # Rebuild via a real run to inspect the durable summaries.
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    for summary in run.checkpoint["_summaries"]:
        assert set(summary) == {"kind", "role", "outcome", "count", "bytes"}
        assert isinstance(summary["count"], int) and isinstance(summary["bytes"], int)


# --------------------------------------------------------------------------------- kill switch


def test_kill_switch_blocks_claim_and_preserves_state() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    set_runtime_suspension(organization_id=None, suspended=True, actor="admin")
    assert execute_agent_run(run.id) == "suspended"
    run.refresh_from_db()
    assert run.status == AgentRunStatus.QUEUED
    assert AgentRunEvent.objects.filter(run=run, event_type="run_suspended").exists()
    # Clearing the switch allows a normal completion.
    set_runtime_suspension(organization_id=None, suspended=False, actor="admin")
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED


def test_kill_switch_is_organization_scoped() -> None:
    a = build_agent(org_slug="org-a")
    b = build_agent(org_slug="org-b")
    run_a = make_run(a)
    run_b = make_run(b)
    set_runtime_suspension(organization_id=a.organization.id, suspended=True, actor="admin")
    assert runtime_suspended(a.organization.id) is True
    assert runtime_suspended(b.organization.id) is False
    assert execute_agent_run(run_a.id) == "suspended"
    execute_agent_run(run_b.id)
    run_b.refresh_from_db()
    assert run_b.status == AgentRunStatus.COMPLETED
    run_a.refresh_from_db()
    assert run_a.status == AgentRunStatus.QUEUED


def test_global_switch_singleton_upsert() -> None:
    set_runtime_suspension(organization_id=None, suspended=True, actor="admin", reason="incident")
    set_runtime_suspension(organization_id=None, suspended=False, actor="admin")
    assert AgentRuntimeControl.objects.filter(organization__isnull=True).count() == 1


def test_suspend_command_denied_for_non_platform_admin() -> None:
    from django.contrib.auth import get_user_model
    from django.core.management import CommandError, call_command

    get_user_model().objects.create_user(username="editor-1", password="x")  # noqa: S106
    with pytest.raises(CommandError):
        call_command("suspend_agent_runtime", "--actor", "editor-1")
    assert not AgentRuntimeControl.objects.filter(suspended=True).exists()


def test_suspend_and_resume_commands_flip_and_redispatch() -> None:
    from django.contrib.auth import get_user_model
    from django.core.management import call_command

    get_user_model().objects.create_superuser(
        username="admin-1",
        password="x",  # noqa: S106
        email="a@e.co",
    )
    fixture = build_agent()
    run = make_run(fixture)
    call_command("suspend_agent_runtime", "--actor", "admin-1", "--reason", "incident")
    assert runtime_suspended(fixture.organization.id) is True
    assert execute_agent_run(run.id) == "suspended"
    # Resume clears the switch (re-dispatch enqueues a task; eager or not, state is unblocked).
    call_command("resume_agent_runtime", "--actor", "admin-1")
    assert runtime_suspended(fixture.organization.id) is False
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED


def test_arguments_survive_approval_resume_with_checksum_binding(monkeypatch: Any) -> None:
    fixture = build_agent(with_tool=True)
    _use_planner(
        monkeypatch,
        [
            AgentDecision(DECISION_TOOL, role="search", arguments={"query": "lookup"}),
            AgentDecision(DECISION_RESPOND),
        ],
    )
    run = make_run(fixture, capabilities=TOOL_CAPS)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.WAITING_APPROVAL
    # The exact (redacted) approved input is pinned for a checksum-bound resume.
    assert run.checkpoint["_pending_tool_input"] == {"query": "[redacted]"}
    approval = ApprovalRequest.objects.get(invocation__consumer=fixture.consumer)
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
    invocation = ToolInvocation.objects.get(consumer=fixture.consumer)
    assert invocation.status == ToolInvocationStatus.COMPLETED


def _config(fixture: Any) -> dict[str, Any]:
    from apps.agents.services import resolve_release_agent

    return resolve_release_agent(fixture.release).compiled_config
