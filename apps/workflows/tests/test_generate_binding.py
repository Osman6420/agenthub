"""Compiler validation for the P5.2 per-node prompt/model binding on generate/retrieve nodes."""

from __future__ import annotations

from typing import Any

import pytest

from apps.workflows.compiler import WorkflowCompileError, compile_workflow


def _body(generate_config: dict | None, *, retrieve_config: dict | None = None) -> dict:
    retrieve_node: dict[str, Any] = {"id": "r", "type": "retrieve"}
    if retrieve_config is not None:
        retrieve_node["config"] = retrieve_config
    generate_node: dict[str, Any] = {"id": "g", "type": "generate"}
    if generate_config is not None:
        generate_node["config"] = generate_config
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "rag_flow.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                retrieve_node,
                generate_node,
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "r"},
                {"from": "r", "to": "g"},
                {"from": "g", "to": "done"},
            ],
        },
    }


def test_generate_accepts_no_config() -> None:
    compile_workflow(_body(None))


def test_generate_accepts_per_node_prompt_and_model_binding() -> None:
    compiled = compile_workflow(
        _body({"prompt_ref": "summarize_prompt", "model_profile_ref": "fast_model"})
    )
    generate = next(n for n in compiled.graph["nodes"] if n["id"] == "g")
    assert generate["config"]["prompt_ref"] == "summarize_prompt"


def test_generate_rejects_unknown_config_key() -> None:
    with pytest.raises(WorkflowCompileError):
        compile_workflow(_body({"prompt_ref": "p", "unexpected": 1}))


def test_generate_rejects_non_identifier_ref() -> None:
    with pytest.raises(WorkflowCompileError):
        compile_workflow(_body({"prompt_ref": "not an identifier!"}))


def test_retrieve_rejects_config() -> None:
    with pytest.raises(WorkflowCompileError):
        compile_workflow(_body(None, retrieve_config={"top_k": 5}))
