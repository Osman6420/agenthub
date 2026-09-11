"""Internal agent-planner facade (schema v2, P2.6.6).

A planner proposes the *next action* given the objective and what has been observed so
far. It is deliberately the only pluggable "intelligence" seam: LangGraph plugs in here
(``AGENT_PLANNER``) without the durable run state machine, tenant isolation, tool proxy,
approval, audit, retry, idempotency, or resource guards depending on its API. The
default is the deterministic planner, so tests and CI stay hermetic and no graph code
runs unless a deployment explicitly selects an adapter.

A planner's decision is a *proposal only*. The runtime re-validates every decision: the
schema version must match, the kind must be allowlisted, any tool/verify role must be
inside the immutable compiled allowlist, ``verify``/``escalate`` must be policy-enabled,
and any structured ``arguments`` must pass the pinned tool contract at the runtime
boundary *and* again at the proxy. A compromised or novel planner can therefore never
widen the tool surface, skip approval, raise a cap, reach an unpinned destination, or
smuggle arguments a contract forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from django.utils.module_loading import import_string

# Structured decision schema version. Carried on every proposal and re-validated
# server-side; a mismatch fails the run closed (never reinterpreted).
AGENT_DECISION_SCHEMA_VERSION = 2

DECISION_RETRIEVE = "retrieve"
DECISION_TOOL = "tool"
DECISION_VERIFY = "verify"
DECISION_RESPOND = "respond"
DECISION_ESCALATE = "escalate"
DECISION_KINDS: frozenset[str] = frozenset(
    {DECISION_RETRIEVE, DECISION_TOOL, DECISION_VERIFY, DECISION_RESPOND, DECISION_ESCALATE}
)
# Kinds that address a specific compiled role (tool binding or verification observation).
ROLE_DECISION_KINDS: frozenset[str] = frozenset({DECISION_TOOL, DECISION_VERIFY})

_DECISION_KEYS: frozenset[str] = frozenset(
    {"schema_version", "kind", "role", "arguments", "reason_code"}
)


class DecisionParseError(ValueError):
    """Raised when a dict-form planner proposal has an invalid structural shape."""


@dataclass(frozen=True)
class AgentDecision:
    kind: str
    role: str = ""
    arguments: dict[str, Any] | None = None
    reason_code: str = ""
    schema_version: int = AGENT_DECISION_SCHEMA_VERSION


@dataclass(frozen=True)
class ObservationSummary:
    """A bounded, redacted digest of one prior action for the planner.

    Carries only stable identifiers, codes and counts — never raw retrieval/tool text,
    arguments, secret references, execution context, capabilities or chain of thought.
    """

    kind: str
    role: str = ""
    outcome: str = ""
    count: int = 0
    bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "role": self.role,
            "outcome": self.outcome,
            "count": self.count,
            "bytes": self.bytes,
        }


@dataclass(frozen=True)
class AgentObservation:
    objective: str
    retrieved: bool
    tools_called: tuple[str, ...]
    summaries: tuple[ObservationSummary, ...] = ()
    schema_version: int = AGENT_DECISION_SCHEMA_VERSION


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


def parse_decision(payload: dict[str, Any]) -> AgentDecision:
    """Exact-key parse of a dict-form proposal into an ``AgentDecision``.

    Structural validation only (shape, key set, primitive types). Authority validation
    (allowlist, policy, argument contracts, budgets) is the runtime's, applied after this.
    """
    if not isinstance(payload, dict):
        raise DecisionParseError("decision must be an object")
    unknown = set(payload) - _DECISION_KEYS
    if unknown:
        raise DecisionParseError("decision contains unknown keys")
    kind = payload.get("kind")
    if not isinstance(kind, str) or not kind:
        raise DecisionParseError("decision kind is invalid")
    role = payload.get("role", "")
    if not isinstance(role, str):
        raise DecisionParseError("decision role is invalid")
    reason_code = payload.get("reason_code", "")
    if not isinstance(reason_code, str):
        raise DecisionParseError("decision reason_code is invalid")
    arguments = payload.get("arguments")
    if arguments is not None and not isinstance(arguments, dict):
        raise DecisionParseError("decision arguments must be an object")
    schema_version = payload.get("schema_version", AGENT_DECISION_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise DecisionParseError("decision schema_version is invalid")
    return AgentDecision(
        kind=kind,
        role=role,
        arguments=dict(arguments) if isinstance(arguments, dict) else None,
        reason_code=reason_code,
        schema_version=schema_version,
    )


class DeterministicPlanner:
    """A bounded, reproducible policy that exercises the full governed runtime.

    Observe–act–verify–respond/escalate: retrieve once (if enabled), then propose each
    allowlisted tool binding role in declared order exactly once, then — if the agent
    authored verification roles — verify each once, then respond. It converges within
    ``1 + len(tools) + len(verify_roles) + 1`` steps, well under the step cap. Repetition
    and escalation are only proposed when the compiled policy admits them, so the default
    single-use, no-escalate behavior is preserved for agents that do not opt in.
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
        actions = config.get("actions") or {}
        verified_roles = {s.role for s in observation.summaries if s.kind == DECISION_VERIFY}
        for role in actions.get("verify_roles", []):
            if role not in verified_roles:
                return AgentDecision(DECISION_VERIFY, role=role, reason_code="verify_result")
        return AgentDecision(DECISION_RESPOND, reason_code="final_answer")


def get_configured_planner() -> AgentPlanner:
    path = getattr(settings, "AGENT_PLANNER", "")
    if path:
        return import_string(path)()
    return DeterministicPlanner()
