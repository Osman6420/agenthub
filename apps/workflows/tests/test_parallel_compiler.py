from __future__ import annotations

from copy import deepcopy

import pytest

from apps.workflows.compiler import WorkflowCompileError, compile_workflow


def parallel_workflow() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "parallel_test"},
        "spec": {
            "input_node": "input",
            "nodes": [
                {"id": "input", "type": "input"},
                {
                    "id": "split",
                    "type": "parallel",
                    "config": {"join": "joined", "max_concurrency": 2},
                },
                {
                    "id": "a",
                    "type": "retrieve",
                    "output_mapping": [{"from": "/chunks", "to": "/branches/a/output"}],
                },
                {
                    "id": "b",
                    "type": "retrieve",
                    "output_mapping": [{"from": "/chunks", "to": "/branches/b/output"}],
                },
                {
                    "id": "joined",
                    "type": "join",
                    "config": {
                        "mode": "all",
                        "branches": ["a", "b"],
                        "merge": [
                            {"from": "/branches/a/output", "to": "/evidence/a"},
                            {"from": "/branches/b/output", "to": "/evidence/b"},
                        ],
                    },
                },
                {"id": "generate", "type": "generate"},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "input", "to": "split"},
                {"from": "split", "to": "a", "branch": "a"},
                {"from": "a", "to": "joined", "branch": "a"},
                {"from": "split", "to": "b", "branch": "b"},
                {"from": "b", "to": "joined", "branch": "b"},
                {"from": "joined", "to": "generate"},
                {"from": "generate", "to": "end"},
            ],
        },
    }


def test_parallel_contract_is_closed_and_deterministic() -> None:
    first = compile_workflow(parallel_workflow())
    second = compile_workflow(parallel_workflow())
    assert first.checksum == second.checksum
    joined = next(node for node in first.graph["nodes"] if node["id"] == "joined")
    assert joined["config"]["branches"] == ["a", "b"]


@pytest.mark.parametrize(
    "mutate,code",
    [
        (
            lambda body: body["spec"]["nodes"][1]["config"].update(max_concurrency=17),
            "WORKFLOW_BUDGET_EXCEEDED",
        ),
        (
            lambda body: body["spec"]["nodes"][4]["config"].update(required=1),
            "WORKFLOW_JOIN_POLICY_INVALID",
        ),
        (
            lambda body: body["spec"]["nodes"][4]["config"]["branches"].reverse(),
            "WORKFLOW_PARALLEL_REGION_INVALID",
        ),
        (
            lambda body: body["spec"]["nodes"][4]["config"]["merge"].append(
                {"from": "/branches/b/output", "to": "/evidence/a"}
            ),
            "WORKFLOW_MAPPING_CONFLICT",
        ),
        (
            lambda body: body["spec"]["nodes"][2]["output_mapping"].__setitem__(
                0, {"from": "/chunks", "to": "/branches/b/output"}
            ),
            "WORKFLOW_PARALLEL_REGION_INVALID",
        ),
    ],
)
def test_parallel_contract_rejects_bounds_policy_conflicts_and_namespace_escape(
    mutate, code: str
) -> None:
    body = deepcopy(parallel_workflow())
    mutate(body)
    with pytest.raises(WorkflowCompileError, match=code):
        compile_workflow(body)


def test_for_each_rejects_unbounded_fanout() -> None:
    body = parallel_workflow()
    body["spec"]["nodes"][1] = {
        "id": "split",
        "type": "for_each",
        "config": {
            "items_path": "/input/items",
            "item_path": "/item",
            "max_items": 101,
            "max_concurrency": 2,
            "body_entry": "a",
            "join": "joined",
        },
    }
    with pytest.raises(WorkflowCompileError, match="WORKFLOW_BUDGET_EXCEEDED"):
        compile_workflow(body)
