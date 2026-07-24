"""Persistence-independent resolution of immutable compiled agent policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeAgentPolicy:
    limits: dict[str, int]
    max_steps: int
    objective_key: str
    output_key: str
    verify_roles: frozenset[str]
    role_call_caps: dict[str, int]
    repeat_retrieval: bool
    escalation_enabled: bool
    allowed_actions: frozenset[str] | None


def resolve_runtime_policy(
    *, compiled_config: dict[str, Any], execution_context: dict[str, Any]
) -> RuntimeAgentPolicy:
    """Resolve server-compiled policy plus child-call attenuation.

    The function performs no persistence or provider calls, so both the legacy AgentRun runtime and
    the unified workflow runtime can consume the same authority calculation.
    """

    limits = dict(compiled_config["limits"])
    actions = compiled_config.get("actions") or {}
    max_steps = int(limits["max_steps"])
    allowed_actions: frozenset[str] | None = None
    composition = execution_context.get("composition")
    if isinstance(composition, dict):
        if isinstance(composition.get("max_decisions"), int):
            max_steps = min(max_steps, int(composition["max_decisions"]))
        if isinstance(composition.get("allowed_actions"), list):
            allowed_actions = frozenset(str(action) for action in composition["allowed_actions"])

    return RuntimeAgentPolicy(
        limits=limits,
        max_steps=max_steps,
        objective_key=str(compiled_config["objective_key"]),
        output_key=str(compiled_config["output_key"]),
        verify_roles=frozenset(str(role) for role in actions.get("verify_roles", [])),
        role_call_caps={
            str(role): int(cap) for role, cap in (actions.get("role_call_caps") or {}).items()
        },
        repeat_retrieval=bool(actions.get("repeat_retrieval", False)),
        escalation_enabled=bool(actions.get("escalation_enabled", False)),
        allowed_actions=allowed_actions,
    )
