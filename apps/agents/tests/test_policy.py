from __future__ import annotations

from apps.agents.policy import resolve_runtime_policy


def test_runtime_policy_resolves_defaults_and_child_attenuation() -> None:
    config = {
        "objective_key": "objective",
        "output_key": "answer",
        "limits": {"max_steps": 8, "max_tool_calls": 4, "max_tokens": 1000},
        "actions": {
            "verify_roles": ["retrieval", "tool_binding.search"],
            "role_call_caps": {"tool_binding.search": 2},
            "repeat_retrieval": True,
            "escalation_enabled": True,
        },
    }

    policy = resolve_runtime_policy(
        compiled_config=config,
        execution_context={
            "composition": {
                "max_decisions": 3,
                "allowed_actions": ["retrieve", "respond"],
            }
        },
    )

    assert policy.max_steps == 3
    assert policy.allowed_actions == frozenset({"retrieve", "respond"})
    assert policy.verify_roles == frozenset({"retrieval", "tool_binding.search"})
    assert policy.role_call_caps == {"tool_binding.search": 2}
    assert policy.repeat_retrieval is True
    assert policy.escalation_enabled is True
