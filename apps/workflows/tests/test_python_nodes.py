from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.workflows.compiler import WorkflowCompileError, compile_workflow
from apps.workflows.python_nodes import (
    PythonNodeError,
    PythonNodePin,
    ResolvedPythonNode,
    SubprocessTestRunner,
    _emit_safe_audit,
    contract_checksum,
    execute_configured_python_node,
    execute_reviewed_python_node,
    review_source,
)

SOURCE = "def run(config, input):\n    return {'result': input['value'] * config['factor']}\n"
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {"factor": {"type": "integer"}},
    "required": ["factor"],
    "additionalProperties": False,
}
INPUT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"result": {"type": "integer"}},
    "required": ["result"],
    "additionalProperties": False,
}


class Resolver:
    def __init__(self, node: ResolvedPythonNode | None) -> None:
        self.node = node
        self.calls = 0
        self.disable_after_dispatch = False

    def resolve(self, pin: PythonNodePin) -> ResolvedPythonNode | None:
        del pin
        self.calls += 1
        if self.node is not None and self.disable_after_dispatch and self.calls > 1:
            return replace(self.node, active=False)
        return self.node


def _node(**changes: Any) -> ResolvedPythonNode:
    pin = PythonNodePin(
        organization_id=7,
        node_ref="multiply:r3",
        revision=3,
        source_checksum=hashlib.sha256(SOURCE.encode()).hexdigest(),
        contract_checksum=contract_checksum(CONFIG_SCHEMA, INPUT_SCHEMA, OUTPUT_SCHEMA),
    )
    node = ResolvedPythonNode(
        pin=pin,
        source=SOURCE,
        config_schema=CONFIG_SCHEMA,
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        requested_modules=frozenset(),
        approved=True,
        active=True,
    )
    return replace(node, **changes)


def _execute(
    node: ResolvedPythonNode, **changes: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    audit: list[dict[str, Any]] = []
    arguments: dict[str, Any] = {
        "pin": node.pin,
        "resolver": Resolver(node),
        "runner": SubprocessTestRunner(),
        "config": {"factor": 2},
        "input_payload": {"value": 4},
        "output_mapping": [{"from": "/result", "to": "/output/value"}],
        "state": {"input": {"value": 4}},
        "idempotency_key": "run:1:node:multiply",
        "audit": audit.append,
    }
    arguments.update(changes)
    return execute_reviewed_python_node(**arguments), audit


def test_exact_approved_active_revision_executes_outside_main_process() -> None:
    result, audit = _execute(_node())
    assert result["output"] == {"value": 8}
    assert audit == [
        {
            "event": "python_node.execute",
            "organization_id": 7,
            "node_ref": "multiply:r3",
            "revision": 3,
            "source_checksum": _node().pin.source_checksum,
            "outcome": "completed",
            "reason_code": "PYTHON_NODE_OK",
        }
    ]


@pytest.mark.parametrize(
    ("node", "pin_change", "code"),
    [
        (_node(approved=False), {}, "PYTHON_NODE_NOT_APPROVED"),
        (_node(approved=False, rejected=True), {}, "PYTHON_NODE_REJECTED"),
        (_node(active=False), {}, "PYTHON_NODE_DISABLED"),
        (_node(), {"revision": 2}, "PYTHON_NODE_PIN_STALE"),
        (_node(), {"source_checksum": "0" * 64}, "PYTHON_NODE_PIN_STALE"),
    ],
)
def test_unapproved_disabled_stale_and_checksum_pin_fail_closed(
    node: ResolvedPythonNode, pin_change: dict[str, Any], code: str
) -> None:
    pin = replace(node.pin, **pin_change)
    with pytest.raises(PythonNodeError) as caught:
        _execute(node, pin=pin)
    assert caught.value.code == code


def test_source_checksum_mismatch_fails_closed() -> None:
    node = _node(source=SOURCE + "# drift\n")
    with pytest.raises(PythonNodeError) as caught:
        _execute(node)
    assert caught.value.code == "PYTHON_NODE_CHECKSUM_MISMATCH"


@pytest.mark.parametrize(
    "source",
    [
        "import socket\ndef run(config, input): return {}",
        "import os\ndef run(config, input): return os.environ",
        "import subprocess\ndef run(config, input): return {}",
        "def run(config, input): return open('x').read()",
        "def run(config, input): return eval('1')",
        "def run(config, input): return input.__class__",
    ],
)
def test_static_review_blocks_network_filesystem_process_secret_and_reflection(source: str) -> None:
    review = review_source(source, frozenset())
    assert not review.passed
    assert all(not hasattr(finding, "source") for finding in review.findings)


def test_closed_module_allowlist_allows_only_requested_platform_modules() -> None:
    source = "import math\ndef run(config, input): return {'result': math.floor(input['value'])}"
    assert review_source(source, frozenset({"math"})).passed
    assert not review_source(source, frozenset()).passed
    assert not review_source(source, frozenset({"socket"})).passed


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"config": {"factor": "secret"}}, "PYTHON_NODE_CONFIG_INVALID"),
        ({"input_payload": {"value": "bad"}}, "PYTHON_NODE_INPUT_INVALID"),
        (
            {"output_mapping": [{"from": "/result", "to": "/authorization/value"}]},
            "WORKFLOW_PATH_PROTECTED",
        ),
    ],
)
def test_invalid_config_input_and_state_patch_are_rejected(
    change: dict[str, Any], code: str
) -> None:
    with pytest.raises((PythonNodeError, Exception)) as caught:
        _execute(_node(), **change)
    assert getattr(caught.value, "code", "") == code


def test_invalid_output_schema_is_rejected() -> None:
    node = _node(source="def run(config, input): return {'result': 'bad'}\n")
    node = replace(
        node,
        pin=replace(node.pin, source_checksum=hashlib.sha256(node.source.encode()).hexdigest()),
    )
    with pytest.raises(PythonNodeError) as caught:
        _execute(node)
    assert caught.value.code == "PYTHON_NODE_OUTPUT_INVALID"


def test_cross_tenant_reference_is_indistinguishable_not_allowed() -> None:
    node = _node()
    foreign = replace(node, pin=replace(node.pin, organization_id=8))
    with pytest.raises(PythonNodeError) as caught:
        _execute(node, resolver=Resolver(foreign))
    assert caught.value.code == "PYTHON_NODE_NOT_ALLOWED"


def test_disable_during_dispatch_rejects_late_patch() -> None:
    node = _node()
    resolver = Resolver(node)
    resolver.disable_after_dispatch = True
    with pytest.raises(PythonNodeError) as caught:
        _execute(node, resolver=resolver)
    assert caught.value.code == "PYTHON_NODE_DISABLED"


def test_timeout_output_and_memory_limits() -> None:
    runner = SubprocessTestRunner()
    common: dict[str, Any] = {
        "config": {},
        "input_payload": {},
        "idempotency_key": "same-durable-key",
        "requested_modules": frozenset(),
    }
    with pytest.raises(PythonNodeError, match="PYTHON_NODE_TIMEOUT"):
        runner.execute(
            source="def run(config, input):\n while True: pass",
            wall_seconds=0.1,
            memory_bytes=64 * 1024 * 1024,
            output_bytes=1024,
            **common,
        )
    with pytest.raises(PythonNodeError, match="PYTHON_NODE_OUTPUT_LIMIT"):
        runner.execute(
            source="def run(config, input): return {'x': 'a' * 10000}",
            wall_seconds=2,
            memory_bytes=64 * 1024 * 1024,
            output_bytes=256,
            **common,
        )
    with pytest.raises(PythonNodeError, match="PYTHON_NODE_MEMORY_LIMIT"):
        runner.execute(
            source="def run(config, input): return {'x': 'a' * 80000000}",
            wall_seconds=2,
            memory_bytes=64 * 1024 * 1024,
            output_bytes=90_000_000,
            **common,
        )


def test_audit_is_content_free_on_failure_and_duplicate_key_is_stable() -> None:
    node = _node(active=False)
    audit: list[dict[str, Any]] = []
    for _ in range(2):
        with pytest.raises(PythonNodeError):
            _execute(
                node,
                config={"factor": "top-secret"},
                input_payload={"value": "top-secret"},
                idempotency_key="same-durable-key",
                audit=audit.append,
            )
    rendered = str(audit)
    assert "top-secret" not in rendered
    assert "def run" not in rendered
    assert len(audit) == 2


@override_settings(PYTHON_NODE_RUNTIME_ENABLED=False)
def test_production_runtime_is_feature_disabled_by_default() -> None:
    with pytest.raises(PythonNodeError, match="PYTHON_NODE_RUNTIME_DISABLED"):
        execute_configured_python_node(
            config={}, input_payload={}, run=SimpleNamespace(), node_id="python"
        )


def test_duplicate_redelivery_is_deterministic_and_uses_same_authority_key() -> None:
    node = _node()
    first, _ = _execute(node, idempotency_key="run:1:node:multiply")
    second, _ = _execute(node, idempotency_key="run:1:node:multiply")
    assert first == second == {"input": {"value": 4}, "output": {"value": 8}}


def test_persisted_workflow_audit_uses_only_safe_existing_fields() -> None:
    run = SimpleNamespace(id=12, organization_id=7)
    event: dict[str, str | int | bool] = {
        "event": "python_node.execute",
        "outcome": "denied",
        "reason_code": "PYTHON_NODE_REJECTED",
        "source_checksum": "a" * 64,
    }
    with (
        patch("apps.workflows.services._next_sequence", return_value=9),
        patch("apps.workflows.models.WorkflowRunEvent.objects.create") as create,
    ):
        _emit_safe_audit(run, event, "python-node")
    create.assert_called_once_with(
        run=run,
        organization_id=7,
        sequence=9,
        event_type="python_node_execution",
        node_id="python-node",
        outcome="denied",
        reason_code="PYTHON_NODE_REJECTED",
    )


def _workflow_custom(config: dict[str, Any], *, output_mapping: bool = True) -> dict[str, Any]:
    node: dict[str, Any] = {"id": "custom", "type": "custom", "config": config}
    if output_mapping:
        node["output_mapping"] = [{"from": "/result", "to": "/output/value"}]
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "python_flow.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                node,
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "custom"},
                {"from": "custom", "to": "done"},
            ],
        },
    }


def test_compiler_accepts_exact_python_pin_and_requires_safe_output_mapping() -> None:
    node = _node()
    config = {
        "execution_class": "python",
        "node_ref": node.pin.node_ref,
        "revision": node.pin.revision,
        "source_checksum": node.pin.source_checksum,
        "contract_checksum": node.pin.contract_checksum,
        "parameters": {"factor": 2},
    }
    compiled = compile_workflow(
        _workflow_custom(config), allowed_custom_nodes=frozenset({node.pin.node_ref})
    )
    custom = next(item for item in compiled.graph["nodes"] if item["id"] == "custom")
    assert custom["config"] == config
    with pytest.raises(WorkflowCompileError, match="requires output_mapping"):
        compile_workflow(
            _workflow_custom(config, output_mapping=False),
            allowed_custom_nodes=frozenset({node.pin.node_ref}),
        )


def test_managed_node_compiler_contract_remains_backward_compatible() -> None:
    body = _workflow_custom({"node_ref": "redact.v1", "fields": ["answer"]})
    compiled = compile_workflow(body, allowed_custom_nodes=frozenset({"redact.v1"}))
    custom = next(item for item in compiled.graph["nodes"] if item["id"] == "custom")
    assert custom["config"] == {"node_ref": "redact.v1", "fields": ["answer"]}
