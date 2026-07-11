"""Strict deterministic compiler for the non-executable AgentHub workflow DSL."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum

MAX_NODES = 50
MAX_EDGES = 100
MAX_IDENTIFIER_LENGTH = 64

BUILTIN_NODE_TYPES = frozenset(
    {
        "input",
        "retrieve",
        "generate",
        "condition",
        "format_output",
        "validate_contract",
        "end",
        "custom",
    }
)


class WorkflowCompileError(ValueError):
    """Raised for safe, content-free workflow validation diagnostics."""


@dataclass(frozen=True)
class CompiledWorkflow:
    graph: dict[str, Any]
    checksum: str


def validate_artifact_body(artifact_type: str, body: dict[str, Any]) -> None:
    if artifact_type == ArtifactType.WORKFLOW_DEFINITION:
        compile_workflow(body)
        return
    if artifact_type == ArtifactType.CUSTOM_NODE_DEFINITION:
        _validate_custom_node(body)


def compile_workflow(
    body: dict[str, Any], *, allowed_custom_nodes: frozenset[str] | None = None
) -> CompiledWorkflow:
    _require_exact_keys(body, {"api_version", "kind", "metadata", "spec"}, "workflow")
    if body.get("api_version") != "agenthub/v1" or body.get("kind") != "Workflow":
        raise WorkflowCompileError("unsupported workflow api_version or kind")
    metadata = _mapping(body.get("metadata"), "metadata")
    _require_exact_keys(metadata, {"id"}, "metadata")
    workflow_id = _identifier(metadata.get("id"), "workflow id")
    spec = _mapping(body.get("spec"), "spec")
    _require_exact_keys(spec, {"input_node", "nodes", "edges"}, "spec")

    raw_nodes = spec.get("nodes")
    raw_edges = spec.get("edges")
    if not isinstance(raw_nodes, list) or not raw_nodes or len(raw_nodes) > MAX_NODES:
        raise WorkflowCompileError(f"workflow must contain 1..{MAX_NODES} nodes")
    if not isinstance(raw_edges, list) or len(raw_edges) > MAX_EDGES:
        raise WorkflowCompileError(f"workflow must contain at most {MAX_EDGES} edges")

    nodes: dict[str, dict[str, Any]] = {}
    for raw in raw_nodes:
        node = _validate_node(raw, allowed_custom_nodes)
        node_id = node["id"]
        if node_id in nodes:
            raise WorkflowCompileError("node ids must be unique")
        nodes[node_id] = node

    input_node = _identifier(spec.get("input_node"), "input_node")
    if input_node not in nodes or nodes[input_node]["type"] != "input":
        raise WorkflowCompileError("input_node must reference an input node")

    edges = [_validate_edge(item, nodes) for item in raw_edges]
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in edges:
        adjacency[edge["from"]].append(edge["to"])
    _assert_acyclic(adjacency)
    reachable = _reachable(input_node, adjacency)
    if reachable != set(nodes):
        raise WorkflowCompileError("workflow contains unreachable nodes")
    if not any(nodes[node_id]["type"] == "end" for node_id in reachable):
        raise WorkflowCompileError("workflow requires a reachable end node")
    for node_id, node in nodes.items():
        if node["type"] != "end" and not adjacency[node_id]:
            raise WorkflowCompileError("every non-end node requires an outgoing edge")
        if node["type"] == "end" and adjacency[node_id]:
            raise WorkflowCompileError("end nodes cannot have outgoing edges")

    graph = {
        "api_version": "agenthub/compiled-workflow/v1",
        "workflow_id": workflow_id,
        "input_node": input_node,
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "edges": sorted(edges, key=lambda item: (item["from"], str(item.get("when")), item["to"])),
        "limits": {"max_nodes": MAX_NODES, "max_edges": MAX_EDGES},
    }
    return CompiledWorkflow(graph=graph, checksum=compute_checksum(graph))


def _validate_node(raw: Any, allowed_custom_nodes: frozenset[str] | None) -> dict[str, Any]:
    node = _mapping(raw, "node")
    _require_exact_keys(node, {"id", "type", "config"}, "node", optional={"config"})
    node_id = _identifier(node.get("id"), "node id")
    node_type = node.get("type")
    if node_type not in BUILTIN_NODE_TYPES:
        raise WorkflowCompileError("unknown node type")
    config = node.get("config", {})
    if not isinstance(config, dict):
        raise WorkflowCompileError("node config must be an object")
    _reject_dangerous_keys(config)

    if node_type == "condition":
        _require_exact_keys(config, {"expression"}, "condition config")
        _validate_condition(config.get("expression"))
    elif node_type == "custom":
        _require_exact_keys(config, {"node_ref", "fields"}, "custom config", optional={"fields"})
        node_ref = _identifier(config.get("node_ref"), "custom node_ref")
        if allowed_custom_nodes is not None and node_ref not in allowed_custom_nodes:
            raise WorkflowCompileError("custom node is not allowed for this workflow")
    elif node_type in {"input", "validate_contract", "end"} and config:
        raise WorkflowCompileError(f"{node_type} node does not accept config")

    return {"id": node_id, "type": node_type, "config": config}


def _validate_edge(raw: Any, nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    edge = _mapping(raw, "edge")
    _require_exact_keys(edge, {"from", "to", "when"}, "edge", optional={"when"})
    source = _identifier(edge.get("from"), "edge from")
    target = _identifier(edge.get("to"), "edge to")
    if source not in nodes or target not in nodes:
        raise WorkflowCompileError("edge references an unknown node")
    result: dict[str, Any] = {"from": source, "to": target}
    if "when" in edge:
        if not isinstance(edge["when"], bool):
            raise WorkflowCompileError("edge when must be boolean")
        if nodes[source]["type"] != "condition":
            raise WorkflowCompileError("only condition edges may define when")
        result["when"] = edge["when"]
    return result


def _validate_condition(expression: Any) -> None:
    if not isinstance(expression, str) or not expression or len(expression) > 500:
        raise WorkflowCompileError("condition expression must be a bounded string")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise WorkflowCompileError("invalid condition expression") from None
    allowed = (
        ast.Expression,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Gt,
        ast.GtE,
        ast.Lt,
        ast.LtE,
        ast.Name,
        ast.Attribute,
        ast.Load,
        ast.Constant,
    )
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise WorkflowCompileError("condition uses a forbidden operation")
    if any(isinstance(node, ast.Name) and node.id.startswith("_") for node in ast.walk(tree)):
        raise WorkflowCompileError("condition uses a forbidden field")


def _validate_custom_node(body: dict[str, Any]) -> None:
    _require_exact_keys(body, {"api_version", "kind", "metadata", "spec"}, "custom node")
    if body.get("api_version") != "agenthub/v1" or body.get("kind") != "CustomNode":
        raise WorkflowCompileError("unsupported custom node api_version or kind")
    metadata = _mapping(body.get("metadata"), "metadata")
    _require_exact_keys(metadata, {"id", "owner"}, "metadata")
    _identifier(metadata.get("id"), "custom node id")
    _identifier(metadata.get("owner"), "custom node owner")
    spec = _mapping(body.get("spec"), "spec")
    allowed = {
        "package",
        "package_version",
        "entrypoint",
        "config_schema_ref",
        "input_state_schema_ref",
        "output_state_schema_ref",
        "allowed_organizations",
        "execution",
        "permissions",
    }
    _require_exact_keys(spec, allowed, "custom node spec")
    for key in ("package", "package_version", "entrypoint"):
        value = spec.get(key)
        if not isinstance(value, str) or not value or len(value) > 255:
            raise WorkflowCompileError(f"custom node {key} is invalid")
    organizations = spec.get("allowed_organizations")
    if not isinstance(organizations, list) or not organizations:
        raise WorkflowCompileError("custom node requires allowed organizations")
    if any(not isinstance(item, str) or not item for item in organizations):
        raise WorkflowCompileError("custom node organization allowlist is invalid")
    execution = _mapping(spec.get("execution"), "execution")
    _require_exact_keys(execution, {"queue", "timeout_seconds", "max_output_bytes"}, "execution")
    timeout = execution.get("timeout_seconds")
    output_bytes = execution.get("max_output_bytes")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 30:
        raise WorkflowCompileError("custom node timeout must be 1..30 seconds")
    if not isinstance(output_bytes, int) or not 1 <= output_bytes <= 1_048_576:
        raise WorkflowCompileError("custom node output limit is invalid")
    permissions = _mapping(spec.get("permissions"), "permissions")
    _require_exact_keys(
        permissions,
        {"allow_retrieval", "allow_model_generation", "allow_tool_calls"},
        "permissions",
    )
    if any(not isinstance(value, bool) for value in permissions.values()):
        raise WorkflowCompileError("custom node permissions must be boolean")
    if permissions.get("allow_tool_calls"):
        raise WorkflowCompileError("custom nodes cannot call tools directly")


def _reject_dangerous_keys(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = {"endpoint", "url", "entrypoint", "package", "python", "code", "secret"}
        if forbidden & {str(key).lower() for key in value}:
            raise WorkflowCompileError("node config contains a forbidden field")
        for item in value.values():
            _reject_dangerous_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_dangerous_keys(item)


def _assert_acyclic(adjacency: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise WorkflowCompileError("workflow graph must be acyclic")
        if node_id in visited:
            return
        visiting.add(node_id)
        for target in adjacency[node_id]:
            visit(target)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in adjacency:
        visit(node_id)


def _reachable(start: str, adjacency: dict[str, list[str]]) -> set[str]:
    found: set[str] = set()
    pending = [start]
    while pending:
        node_id = pending.pop()
        if node_id in found:
            continue
        found.add(node_id)
        pending.extend(adjacency[node_id])
    return found


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowCompileError(f"{name} must be an object")
    return value


def _identifier(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or not all(character.isalnum() or character in "._-" for character in value)
    ):
        raise WorkflowCompileError(f"{name} is invalid")
    return value


def _require_exact_keys(
    value: dict[str, Any], required: set[str], name: str, *, optional: set[str] | None = None
) -> None:
    optional = optional or set()
    missing = required - optional - set(value)
    unknown = set(value) - required
    if missing:
        raise WorkflowCompileError(f"{name} is missing required fields")
    if unknown:
        raise WorkflowCompileError(f"{name} contains unknown fields")
