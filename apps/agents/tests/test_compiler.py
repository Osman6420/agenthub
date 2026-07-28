"""Deterministic embedded agent-loop policy compilation."""

from __future__ import annotations

import pytest

from apps.agents.compiler import AgentCompileError, compile_agent
from apps.agents.limits import MAX_STEPS, MAX_TOKENS
from apps.agents.tests.conftest import agent_body


def test_compile_emits_immutable_config_and_checksum() -> None:
    compiled = compile_agent(agent_body(tools=["search"], retrieval=True))
    assert compiled.config["api_version"] == "agenthub/compiled-agent/v1"
    assert compiled.config["agent_id"] == "assistant.v1"
    assert compiled.config["retrieval"] == {"enabled": True}
    assert compiled.config["tools"] == ["search"]
    assert compiled.config["limits"]["max_steps"] == MAX_STEPS
    assert compiled.config["limits"]["max_tokens"] == MAX_TOKENS
    assert len(compiled.checksum) == 64


def test_compile_is_deterministic() -> None:
    a = compile_agent(agent_body(tools=["a", "b"]))
    b = compile_agent(agent_body(tools=["a", "b"]))
    assert a.checksum == b.checksum


def test_tool_order_is_preserved() -> None:
    compiled = compile_agent(agent_body(tools=["b", "a", "c"]))
    assert compiled.tools == ("b", "a", "c")


def test_limits_lowered_but_never_raised() -> None:
    compiled = compile_agent(agent_body(limits={"max_steps": 3}))
    assert compiled.config["limits"]["max_steps"] == 3
    # Untouched fields keep the hard cap.
    assert compiled.config["limits"]["max_tokens"] == MAX_TOKENS


def test_compile_rejects_invalid_body() -> None:
    with pytest.raises(AgentCompileError):
        compile_agent(agent_body(tools=["dup", "dup"]))
