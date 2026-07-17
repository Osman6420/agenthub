"""Strict deterministic compiler for the non-executable AgentHub workflow DSL."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.workflows.state_mapping import MappingError, compile_mappings

MAX_NODES = 50
MAX_EDGES = 100
MAX_IDENTIFIER_LENGTH = 64

# Compiled-contract version (ADR-0008). Bumped for the P2.6.1 typed-mapping semantics so a
# stale v1 compiled graph or checkpoint can never be resumed under the new runtime.
COMPILED_WORKFLOW_API_VERSION = "agenthub/compiled-workflow/v2"
COMPILER_VERSION = "workflow-compiler/v2"

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
        "tool",
        "transform",
    }
)

# Nodes that may declare typed ``input_mapping``/``output_mapping`` (P2.6.1). Control/IO nodes
# never carry mappings so they cannot silently reshape state.
MAPPING_ELIGIBLE_NODE_TYPES = frozenset({"retrieve", "generate", "tool", "custom", "transform"})


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
        "api_version": COMPILED_WORKFLOW_API_VERSION,
        "workflow_id": workflow_id,
        "input_node": input_node,
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "edges": sorted(edges, key=lambda item: (item["from"], str(item.get("when")), item["to"])),
        "limits": {"max_nodes": MAX_NODES, "max_edges": MAX_EDGES},
    }
    return CompiledWorkflow(graph=graph, checksum=compute_checksum(graph))


def _validate_node(raw: Any, allowed_custom_nodes: frozenset[str] | None) -> dict[str, Any]:
    node = _mapping(raw, "node")
    _require_exact_keys(
        node,
        {"id", "type", "config", "input_mapping", "output_mapping"},
        "node",
        optional={"config", "input_mapping", "output_mapping"},
    )
    node_id = _identifier(node.get("id"), "node id")
    node_type = node.get("type")
    if node_type not in BUILTIN_NODE_TYPES:
        raise WorkflowCompileError("unknown node type")
    config = node.get("config", {})
    if not isinstance(config, dict):
        raise WorkflowCompileError("node config must be an object")
    _reject_dangerous_keys(config)

    input_mapping, output_mapping = _validate_node_mappings(node, node_type)

    if node_type == "condition":
        _require_exact_keys(config, {"expression"}, "condition config")
        _validate_condition(config.get("expression"))
    elif node_type == "custom":
        execution_class = config.get("execution_class", "managed")
        if execution_class == "python":
            _require_exact_keys(
                config,
                {
                    "execution_class",
                    "node_ref",
                    "revision",
                    "source_checksum",
                    "contract_checksum",
                    "parameters",
                },
                "python custom config",
            )
            node_ref = config.get("node_ref")
            if not isinstance(node_ref, str) or ":r" not in node_ref or len(node_ref) > 128:
                raise WorkflowCompileError("python custom node_ref is invalid")
            revision = config.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise WorkflowCompileError("python custom revision is invalid")
            if not node_ref.endswith(f":r{revision}"):
                raise WorkflowCompileError("python custom revision does not match node_ref")
            for checksum_key in ("source_checksum", "contract_checksum"):
                checksum = config.get(checksum_key)
                if (
                    not isinstance(checksum, str)
                    or len(checksum) != 64
                    or any(character not in "0123456789abcdef" for character in checksum)
                ):
                    raise WorkflowCompileError(f"python custom {checksum_key} is invalid")
            if not isinstance(config.get("parameters"), dict):
                raise WorkflowCompileError("python custom parameters must be an object")
            if output_mapping is None:
                raise WorkflowCompileError("python custom node requires output_mapping")
        elif execution_class == "managed":
            _require_exact_keys(
                config,
                {"execution_class", "node_ref", "fields"},
                "custom config",
                optional={"execution_class", "fields"},
            )
            node_ref = _identifier(config.get("node_ref"), "custom node_ref")
        else:
            raise WorkflowCompileError("custom execution_class is invalid")
        if allowed_custom_nodes is not None and node_ref not in allowed_custom_nodes:
            raise WorkflowCompileError("custom node is not allowed for this workflow")
    elif node_type == "transform":
        # Pinned governed-transform profile only (D1): a release manifest role resolving to an
        # immutable transform_profile artifact. No inline operations, expressions or templates.
        _require_exact_keys(config, {"transform_profile_ref"}, "transform config")
        _identifier(config.get("transform_profile_ref"), "transform transform_profile_ref")
        if input_mapping is None or output_mapping is None:
            raise WorkflowCompileError("transform node requires input_mapping and output_mapping")
    elif node_type == "tool":
        # A tool node calls the governed tool proxy for a release-pinned binding role;
        # egress/approval are enforced at runtime, never in the workflow graph. The input
        # source and output sink may be a legacy state key or a typed mapping, never both.
        _require_exact_keys(
            config,
            {"binding_role", "input_key", "output_key"},
            "tool config",
            optional={"input_key", "output_key"},
        )
        _identifier(config.get("binding_role"), "tool binding_role")
        if "input_key" in config:
            _identifier(config.get("input_key"), "tool input_key")
        if "output_key" in config:
            _identifier(config.get("output_key"), "tool output_key")
        if input_mapping is not None and "input_key" in config:
            raise WorkflowCompileError("tool node cannot set both input_key and input_mapping")
        if (output_mapping is None) == ("output_key" not in config):
            raise WorkflowCompileError(
                "tool node requires exactly one of output_key/output_mapping"
            )
    elif node_type == "generate":
        # Optional per-node prompt/model binding (P5.2): names of manifest roles pinned into the
        # release. The runtime resolves them; a missing role falls back to the release defaults.
        _require_exact_keys(
            config,
            {"prompt_ref", "model_profile_ref"},
            "generate config",
            optional={"prompt_ref", "model_profile_ref"},
        )
        if "prompt_ref" in config:
            _identifier(config.get("prompt_ref"), "generate prompt_ref")
        if "model_profile_ref" in config:
            _identifier(config.get("model_profile_ref"), "generate model_profile_ref")
    elif node_type == "retrieve" and config:
        raise WorkflowCompileError("retrieve node does not accept config")
    elif node_type in {"input", "validate_contract", "end"} and config:
        raise WorkflowCompileError(f"{node_type} node does not accept config")

    compiled_node: dict[str, Any] = {"id": node_id, "type": node_type, "config": config}
    if input_mapping is not None:
        compiled_node["input_mapping"] = input_mapping
    if output_mapping is not None:
        compiled_node["output_mapping"] = output_mapping
    return compiled_node


def _validate_node_mappings(
    node: dict[str, Any], node_type: str
) -> tuple[list[dict[str, str]] | None, list[dict[str, str]] | None]:
    """Validate optional typed mappings and return their canonical form (or ``None``).

    Mappings are only accepted on the eligible node types; the shared strict parser and the
    protected-namespace policy in :mod:`apps.workflows.state_mapping` are the single source of
    truth for both authoring and runtime.
    """
    has_mapping = "input_mapping" in node or "output_mapping" in node
    if has_mapping and node_type not in MAPPING_ELIGIBLE_NODE_TYPES:
        raise WorkflowCompileError(f"{node_type} node does not accept mappings")
    input_mapping = _compile_one_mapping(node.get("input_mapping"), restrict_destination=False)
    output_mapping = _compile_one_mapping(node.get("output_mapping"), restrict_destination=True)
    return input_mapping, output_mapping


def _compile_one_mapping(
    entries: Any, *, restrict_destination: bool
) -> list[dict[str, str]] | None:
    if entries is None:
        return None
    try:
        compiled = compile_mappings(entries, restrict_destination=restrict_destination)
        return [dict(item) for item in compiled]
    except MappingError as exc:
        # Surface the stable content-free code (WORKFLOW_PATH_INVALID / _PROTECTED /
        # _MAPPING_CONFLICT / _MAPPING_INVALID) as the diagnostic message.
        raise WorkflowCompileError(exc.code) from None


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
