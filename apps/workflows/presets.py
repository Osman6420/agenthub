"""Canonical type-free workflow starter bodies."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def empty_workflow(*, logical_id: str = "workflow.v1") -> dict[str, Any]:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": logical_id},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "output", "type": "format_output", "config": {"template_ref": ""}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "output"},
                {"from": "output", "to": "done"},
            ],
        },
    }


def document_answer_workflow(*, logical_id: str = "document_answer.v1") -> dict[str, Any]:
    """Return the governed retrieve/generate contract used for document answers."""

    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": logical_id},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "retrieve", "type": "retrieve"},
                {"id": "answer", "type": "generate"},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "retrieve"},
                {"from": "retrieve", "to": "answer"},
                {"from": "answer", "to": "done"},
            ],
        },
    }


def agent_loop_workflow(
    *,
    policy: dict[str, Any],
    logical_id: str = "agent_loop.v1",
) -> dict[str, Any]:
    """Embed a caller-supplied closed agent policy in the canonical workflow graph."""

    config = deepcopy(policy)
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": logical_id},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {
                    "id": "agent",
                    "type": "agent_loop",
                    "config": config,
                    "input_mapping": [{"from": "/input", "to": "/input"}],
                    "output_mapping": [{"from": "/output", "to": "/output"}],
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "agent"},
                {"from": "agent", "to": "done"},
            ],
        },
    }
