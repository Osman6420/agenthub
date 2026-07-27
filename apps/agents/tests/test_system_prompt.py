"""Authored, governed agent system prompt (P6): schema bounds, compiler, runtime use."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from apps.agents import runtime
from apps.agents.compiler import AgentCompileError, compile_agent
from apps.agents.tests.conftest import agent_body
from apps.orchestration import rag_steps


def _body(system_prompt: Any) -> dict:
    body = agent_body(tools=[])
    body["spec"]["system_prompt"] = system_prompt
    return body


def test_compiler_pins_authored_system_prompt() -> None:
    compiled = compile_agent(_body("You are a helpful returns assistant."))
    assert compiled.config["system_prompt"] == "You are a helpful returns assistant."


def test_system_prompt_defaults_to_empty() -> None:
    compiled = compile_agent(agent_body(tools=[]))
    assert compiled.config["system_prompt"] == ""


def test_system_prompt_changes_the_checksum() -> None:
    a = compile_agent(agent_body(tools=[]))
    b = compile_agent(_body("Persona A"))
    assert a.checksum != b.checksum  # pinned into the immutable compiled agent


@pytest.mark.parametrize(
    "value",
    ["", "   ", 123, "x" * 8001, "bad\x00control"],
)
def test_invalid_system_prompt_is_rejected(value: Any) -> None:
    with pytest.raises(AgentCompileError):
        compile_agent(_body(value))


def test_respond_uses_authored_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_generate(*, release: Any, context: Any, prompt: Any = None, model_profile: Any = None):
        captured["prompt"] = prompt
        return SimpleNamespace(text="ok", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(rag_steps, "generate_for_release", fake_generate)
    # The grounding gate reads the pinned policy before generating, so the bundle must resolve.
    monkeypatch.setattr(rag_steps, "resolve_bundle", lambda release: SimpleNamespace(policy={}))
    config = {"system_prompt": "You are a helpful returns agent."}
    runtime._respond("what is the return policy", {"retrieval": {"chunks": []}}, config, object())
    # The authored persona is the prompt; the objective drove retrieval, not the system message.
    assert captured["prompt"] == "You are a helpful returns agent."


def test_respond_falls_back_to_objective_without_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_generate(*, release: Any, context: Any, prompt: Any = None, model_profile: Any = None):
        captured["prompt"] = prompt
        return SimpleNamespace(text="ok", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(rag_steps, "generate_for_release", fake_generate)
    monkeypatch.setattr(rag_steps, "resolve_bundle", lambda release: SimpleNamespace(policy={}))
    runtime._respond("the objective", {}, {"system_prompt": ""}, object())
    assert captured["prompt"] == "the objective"
