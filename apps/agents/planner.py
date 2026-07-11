"""Internal agent-planner facade.

A planner proposes the *next action* given the objective and what has been observed so
far. It is deliberately the only pluggable "intelligence" seam: LangGraph plugs in here
(``AGENT_PLANNER``) without the durable run state machine, tenant isolation, tool proxy,
approval, audit, retry, idempotency, or resource guards depending on its API. The
default is the deterministic planner, so tests and CI stay hermetic and no graph code
runs unless a deployment explicitly selects an adapter.

A planner's decision is a *proposal only*. The runtime re-validates every decision:
the kind must be allowlisted and any tool role must be inside the immutable compiled tool
allowlist. A compromised or novel planner can therefore never widen the tool surface,
skip approval, or escape a resource cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from django.utils.module_loading import import_string

DECISION_RETRIEVE = "retrieve"
DECISION_TOOL = "tool"
DECISION_RESPOND = "respond"
DECISION_KINDS: frozenset[str] = frozenset({DECISION_RETRIEVE, DECISION_TOOL, DECISION_RESPOND})


@dataclass(frozen=True)
class AgentDecision:
    kind: str
    role: str = ""
    reason_code: str = ""


@dataclass(frozen=True)
class AgentObservation:
    objective: str
    retrieved: bool
    tools_called: tuple[str, ...]


@runtime_checkable
class AgentPlanner(Protocol):
    def next_action(
        self,
        *,
        config: dict[str, Any],
        observation: AgentObservation,
        step_index: int,
        run_ref: str = "",
    ) -> AgentDecision: ...


class DeterministicPlanner:
    """A bounded, reproducible policy that exercises the full governed runtime.

    Retrieve once (if enabled), then propose each allowlisted tool binding role in
    declared order exactly once, then respond. It converges within
    ``1 + len(tools) + 1`` steps, well under the step cap.
    """

    def next_action(
        self,
        *,
        config: dict[str, Any],
        observation: AgentObservation,
        step_index: int,
        run_ref: str = "",
    ) -> AgentDecision:
        if config.get("retrieval", {}).get("enabled") and not observation.retrieved:
            return AgentDecision(DECISION_RETRIEVE, reason_code="gather_context")
        for role in config.get("tools", []):
            if role not in observation.tools_called:
                return AgentDecision(DECISION_TOOL, role=role, reason_code="use_tool")
        return AgentDecision(DECISION_RESPOND, reason_code="final_answer")


def get_configured_planner() -> AgentPlanner:
    path = getattr(settings, "AGENT_PLANNER", "")
    if path:
        return import_string(path)()
    return DeterministicPlanner()
