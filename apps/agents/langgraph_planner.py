"""LangGraph-backed :class:`~apps.agents.planner.AgentPlanner` adapter.

Selected only when ``AGENT_PLANNER`` points here, so ``langgraph`` is imported lazily and
the default runtime never runs graph code. LangGraph owns *only* the planning decision:
a compiled ``StateGraph`` encodes the agent's transitions (retrieve -> select a tool ->
respond) and, when a run reference is supplied, an agent-local in-memory checkpoint keyed
by that tenant-scoped run id. Everything durable and security-relevant — the run state
machine, tenant isolation, tool proxy, approval, audit, retry, idempotency, and every
resource cap — stays in AgentHub. A decision returned here is still only a proposal that
the runtime re-validates against the immutable compiled tool allowlist.

No LangSmith / LangGraph Cloud / hosted service is used; the graph runs fully in-process.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from apps.agents.planner import (
    DECISION_RESPOND,
    DECISION_RETRIEVE,
    DECISION_TOOL,
    AgentDecision,
    AgentObservation,
)


class _PlannerState(TypedDict, total=False):
    retrieval_enabled: bool
    retrieved: bool
    tools: list[str]
    tools_called: list[str]
    decision: dict[str, str]


def _next_uncalled_tool(state: _PlannerState) -> str:
    called = set(state.get("tools_called", []))
    for role in state.get("tools", []):
        if role not in called:
            return role
    return ""


def _route(state: _PlannerState) -> str:
    if state.get("retrieval_enabled") and not state.get("retrieved"):
        return DECISION_RETRIEVE
    if _next_uncalled_tool(state):
        return DECISION_TOOL
    return DECISION_RESPOND


def _retrieve_node(state: _PlannerState) -> dict[str, Any]:
    return {"decision": {"kind": DECISION_RETRIEVE, "role": "", "reason_code": "gather_context"}}


def _tool_node(state: _PlannerState) -> dict[str, Any]:
    role = _next_uncalled_tool(state)
    return {"decision": {"kind": DECISION_TOOL, "role": role, "reason_code": "use_tool"}}


def _respond_node(state: _PlannerState) -> dict[str, Any]:
    return {"decision": {"kind": DECISION_RESPOND, "role": "", "reason_code": "final_answer"}}


def _build_graph() -> Any:
    graph: StateGraph = StateGraph(_PlannerState)
    graph.add_node(DECISION_RETRIEVE, _retrieve_node)
    graph.add_node(DECISION_TOOL, _tool_node)
    graph.add_node(DECISION_RESPOND, _respond_node)
    graph.add_conditional_edges(
        START,
        _route,
        {
            DECISION_RETRIEVE: DECISION_RETRIEVE,
            DECISION_TOOL: DECISION_TOOL,
            DECISION_RESPOND: DECISION_RESPOND,
        },
    )
    graph.add_edge(DECISION_RETRIEVE, END)
    graph.add_edge(DECISION_TOOL, END)
    graph.add_edge(DECISION_RESPOND, END)
    # The checkpointer demonstrates agent-local state keyed by the tenant run id; the
    # authoritative durable checkpoint remains AgentHub's ``AgentRun`` row.
    return graph.compile(checkpointer=MemorySaver())


class LangGraphPlanner:
    """Compute the next agent action via an in-process LangGraph ``StateGraph``."""

    def __init__(self) -> None:
        self._graph = _build_graph()

    def next_action(
        self,
        *,
        config: dict[str, Any],
        observation: AgentObservation,
        step_index: int,
        run_ref: str = "",
    ) -> AgentDecision:
        state: _PlannerState = {
            "retrieval_enabled": bool(config.get("retrieval", {}).get("enabled")),
            "retrieved": observation.retrieved,
            "tools": list(config.get("tools", [])),
            "tools_called": list(observation.tools_called),
        }
        thread_id = run_ref or f"ephemeral-{step_index}"
        result = self._graph.invoke(state, {"configurable": {"thread_id": thread_id}})
        decision = result.get("decision") or {}
        return AgentDecision(
            kind=str(decision.get("kind", DECISION_RESPOND)),
            role=str(decision.get("role", "")),
            reason_code=str(decision.get("reason_code", "")),
        )
