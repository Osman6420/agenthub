from __future__ import annotations

from apps.workflows.compiler import compile_workflow
from apps.workflows.presets import (
    agent_loop_workflow,
    document_answer_workflow,
    empty_workflow,
)
from apps.workflows.unified_executor import _validated_graph


def test_empty_and_document_answer_presets_compile_as_sync_workflows() -> None:
    empty = compile_workflow(empty_workflow())
    document = compile_workflow(document_answer_workflow())

    assert empty.graph["execution_mode_analysis"]["supported_execution_modes"] == [
        "background",
        "sync",
    ]
    assert document.graph["execution_mode_analysis"]["supported_execution_modes"] == [
        "background",
        "sync",
    ]
    assert {node["id"]: node["type"] for node in document.graph["nodes"]} == {
        "request": "input",
        "retrieve": "retrieve",
        "answer": "generate",
        "done": "end",
    }


def test_agent_loop_preset_reuses_closed_policy_validation_without_mutating_input() -> None:
    policy = {
        "tool_binding_roles": [],
        "retrieval": {"enabled": True},
        "limits": {"max_steps": 4, "max_tool_calls": 0},
    }

    compiled = compile_workflow(
        agent_loop_workflow(policy=policy),
        allow_agent_loop=True,
    )

    assert policy == {
        "tool_binding_roles": [],
        "retrieval": {"enabled": True},
        "limits": {"max_steps": 4, "max_tool_calls": 0},
    }
    agent = next(node for node in compiled.graph["nodes"] if node["type"] == "agent_loop")
    assert agent["config"]["policy"]["limits"]["max_steps"] == 4
    assert compiled.graph["execution_mode_analysis"]["supported_execution_modes"] == ["background"]
    nodes, _outgoing, _branches, _input = _validated_graph(compiled.graph)
    assert nodes["agent"]["type"] == "agent_loop"
