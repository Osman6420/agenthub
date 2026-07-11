"""Governed agent evaluation: trajectory assertions over the candidate runtime."""

from __future__ import annotations

import pytest

from apps.agents.tests.conftest import build_agent
from apps.evaluations.models import EvalStatus
from apps.evaluations.services import run_eval

pytestmark = pytest.mark.django_db


def _suite(assertions: list[dict]) -> dict:
    return {"cases": [{"id": "c1", "input": {"query": "hello"}, "assertions": assertions}]}


def test_agent_completed_and_no_tools_pass() -> None:
    fixture = build_agent(
        eval_suite=_suite([{"type": "agent_completed"}, {"type": "agent_no_tools"}]),
    )
    run = run_eval(release=fixture.release, created_by="tester")
    assert run.status == EvalStatus.PASSED
    assert run.passed_cases == 1


def test_agent_max_steps_budget() -> None:
    fixture = build_agent(
        retrieval=True,
        eval_suite=_suite([{"type": "agent_max_steps", "count": 5}]),
    )
    run = run_eval(release=fixture.release, created_by="tester")
    assert run.status == EvalStatus.PASSED


def test_agent_max_steps_budget_exceeded_fails() -> None:
    fixture = build_agent(
        retrieval=True,
        eval_suite=_suite([{"type": "agent_max_steps", "count": 1}]),
    )
    run = run_eval(release=fixture.release, created_by="tester")
    assert run.status == EvalStatus.FAILED


def test_agent_tool_invoked_assertion() -> None:
    # The candidate seam stubs tool output (no consumer/egress), but records the call.
    fixture = build_agent(
        with_tool=True,
        eval_suite=_suite([{"type": "agent_tool_invoked", "value": "search"}]),
    )
    run = run_eval(release=fixture.release, created_by="tester")
    assert run.status == EvalStatus.PASSED


def test_no_tools_assertion_fails_for_tool_agent() -> None:
    fixture = build_agent(
        with_tool=True,
        eval_suite=_suite([{"type": "agent_no_tools"}]),
    )
    run = run_eval(release=fixture.release, created_by="tester")
    assert run.status == EvalStatus.FAILED
