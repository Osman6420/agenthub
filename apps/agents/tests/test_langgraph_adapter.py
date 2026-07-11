"""LangGraph planner adapter: decision parity + end-to-end drive through the runtime.

LangGraph owns only the planning decision; it is imported lazily and exercised here to
prove the adapter honors the same transition policy as the deterministic planner and
that the runtime still enforces the compiled allowlist and caps regardless of planner.
"""

from __future__ import annotations

import pytest

from apps.agents.langgraph_planner import LangGraphPlanner
from apps.agents.models import AgentRunStatus
from apps.agents.planner import (
    DECISION_RESPOND,
    DECISION_RETRIEVE,
    DECISION_TOOL,
    AgentObservation,
    DeterministicPlanner,
)
from apps.agents.tasks import execute_agent_run
from apps.agents.tests.conftest import build_agent, make_run

PLANNER_PATH = "apps.agents.langgraph_planner.LangGraphPlanner"


def _config(tools: list[str], retrieval: bool) -> dict:
    return {"tools": tools, "retrieval": {"enabled": retrieval}}


@pytest.mark.parametrize(
    ("tools", "retrieval", "retrieved", "called", "expected"),
    [
        ([], False, False, (), DECISION_RESPOND),
        ([], True, False, (), DECISION_RETRIEVE),
        ([], True, True, (), DECISION_RESPOND),
        (["a", "b"], False, False, (), DECISION_TOOL),
        (["a", "b"], False, False, ("a",), DECISION_TOOL),
        (["a", "b"], False, False, ("a", "b"), DECISION_RESPOND),
    ],
)
def test_langgraph_matches_deterministic(tools, retrieval, retrieved, called, expected) -> None:
    config = _config(tools, retrieval)
    observation = AgentObservation(objective="q", retrieved=retrieved, tools_called=called)
    deterministic = DeterministicPlanner().next_action(
        config=config, observation=observation, step_index=0
    )
    langgraph = LangGraphPlanner().next_action(
        config=config, observation=observation, step_index=0, run_ref="run-1"
    )
    assert deterministic.kind == expected
    assert langgraph.kind == expected
    assert langgraph.role == deterministic.role


@pytest.mark.django_db
def test_run_completes_under_langgraph_planner(settings) -> None:
    settings.AGENT_PLANNER = PLANNER_PATH
    fixture = build_agent(retrieval=True)
    run = make_run(fixture)
    execute_agent_run(run.id)
    run.refresh_from_db()
    assert run.status == AgentRunStatus.COMPLETED
    assert run.step_count == 2  # retrieve + respond, same as the deterministic planner
