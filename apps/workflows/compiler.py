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
MAX_PARALLEL_BRANCHES = 16
MAX_FOR_EACH_ITEMS = 100
MAX_PARALLEL_CONCURRENCY = 16
MAX_PARALLEL_DURATION_SECONDS = 300
MAX_BRANCH_STATE_BYTES = 262_144
MAX_PARALLEL_STATE_BYTES = 1_048_576
MAX_WAIT_SECONDS = 2_592_000
# Pinned child-composition bounds (P2.6.5 / ADR-0009). A call-site may only *lower* the
# nesting depth. This is a compile-time bound; the runtime re-enforces it plus
# cumulative budgets and an ancestry/depth guard.
MAX_CHILD_DEPTH = 3
COMPOSITION_NODE_TYPES = frozenset({"subworkflow"})

# Compiled-contract version (ADR-0008/ADR-0014). The graph api_version stays at v5: v5 graphs
# stay executable, so already-compiled releases keep running. The compiler version bumps to v6 for
# per-node retrieval binding, so no claim or checkpoint compiled under the older retrieve semantics
# can resume.
COMPILED_WORKFLOW_API_VERSION = "agenthub/compiled-workflow/v5"
COMPILER_VERSION = "workflow-compiler/v6"

_SYNC_BLOCKER_BY_NODE_TYPE = {
    "tool": "tool_pause_policy_unproven",
    "custom": "custom_node_bounds_unproven",
    "agent_loop": "agent_loop_pause_policy_unproven",
    "event_wait": "durable_event_wait",
    "human_task": "durable_human_wait",
    "timer": "durable_timer_wait",
    "parallel": "durable_fan_out",
    "for_each": "durable_fan_out",
    "subworkflow": "durable_child_run",
}

FAILURE_CLASSES = frozenset(
    {"validation", "authorization", "permanent", "transient", "outcome_unknown"}
)
MAX_RETRY_ATTEMPTS = 3

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
        "parallel",
        "join",
        "for_each",
        "event_wait",
        "human_task",
        "timer",
        "subworkflow",
        "agent_loop",
    }
)

# Nodes that may declare typed ``input_mapping``/``output_mapping`` (P2.6.1). Control/IO nodes
# never carry mappings so they cannot silently reshape state. Composition nodes require both
# mappings so a child receives only the mapped minimum input and writes only mapped output.
MAPPING_ELIGIBLE_NODE_TYPES = frozenset(
    {
        "retrieve",
        "generate",
        "tool",
        "custom",
        "transform",
        "event_wait",
        "human_task",
        "subworkflow",
        "agent_loop",
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


def _composition_enabled(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    return True


def _agent_loop_enabled(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    return True


def compile_workflow(
    body: dict[str, Any],
    *,
    allowed_custom_nodes: frozenset[str] | None = None,
    allow_composition: bool | None = None,
    allow_agent_loop: bool | None = None,
) -> CompiledWorkflow:
    composition_enabled = _composition_enabled(allow_composition)
    agent_loop_enabled = _agent_loop_enabled(allow_agent_loop)
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
        node = _validate_node(raw, allowed_custom_nodes, composition_enabled, agent_loop_enabled)
        node_id = node["id"]
        if node_id in nodes:
            raise WorkflowCompileError("node ids must be unique")
        nodes[node_id] = node

    input_node = _identifier(spec.get("input_node"), "input_node")
    if input_node not in nodes or nodes[input_node]["type"] != "input":
        raise WorkflowCompileError("input_node must reference an input node")

    edges = [_validate_edge(item, nodes) for item in raw_edges]
    _validate_error_routes(edges)
    compensation_targets = _validate_compensations(nodes, edges)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in edges:
        adjacency[edge["from"]].append(edge["to"])
    _assert_acyclic(adjacency)
    _validate_parallel_regions(nodes, edges, adjacency)
    reachable = _reachable(input_node, adjacency)
    if reachable | compensation_targets != set(nodes):
        raise WorkflowCompileError("workflow contains unreachable nodes")
    if not any(nodes[node_id]["type"] == "end" for node_id in reachable):
        raise WorkflowCompileError("workflow requires a reachable end node")
    for node_id, node in nodes.items():
        success_edges = [
            edge for edge in edges if edge["from"] == node_id and "on_error" not in edge
        ]
        if node["type"] != "end" and node_id not in compensation_targets and not success_edges:
            raise WorkflowCompileError("every non-end node requires an outgoing edge")
        if node["type"] == "end" and success_edges:
            raise WorkflowCompileError("end nodes cannot have outgoing edges")

    graph = {
        "api_version": COMPILED_WORKFLOW_API_VERSION,
        "workflow_id": workflow_id,
        "input_node": input_node,
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "edges": sorted(edges, key=lambda item: (item["from"], str(item.get("when")), item["to"])),
        "limits": {"max_nodes": MAX_NODES, "max_edges": MAX_EDGES},
        "execution_mode_analysis": _execution_mode_analysis(nodes, reachable),
    }
    return CompiledWorkflow(graph=graph, checksum=compute_checksum(graph))


def _execution_mode_analysis(
    nodes: dict[str, dict[str, Any]], reachable: set[str]
) -> dict[str, Any]:
    """Derive safe execution modes from the canonical reachable graph."""

    blocker_nodes: dict[str, list[str]] = {}
    for node_id in sorted(reachable):
        code = _SYNC_BLOCKER_BY_NODE_TYPE.get(nodes[node_id]["type"])
        if code is not None:
            blocker_nodes.setdefault(code, []).append(node_id)

    blockers = [{"code": code, "node_ids": blocker_nodes[code]} for code in sorted(blocker_nodes)]
    supported = ["background"]
    if not blockers:
        supported.append("sync")
    return {
        "supported_execution_modes": supported,
        "sync_blockers": blockers,
    }


def _validate_node(
    raw: Any,
    allowed_custom_nodes: frozenset[str] | None,
    composition_enabled: bool,
    agent_loop_enabled: bool,
) -> dict[str, Any]:
    node = _mapping(raw, "node")
    _require_exact_keys(
        node,
        {"id", "type", "config", "input_mapping", "output_mapping", "retry_policy", "compensation"},
        "node",
        optional={"config", "input_mapping", "output_mapping", "retry_policy", "compensation"},
    )
    node_id = _identifier(node.get("id"), "node id")
    node_type = node.get("type")
    if node_type not in BUILTIN_NODE_TYPES:
        raise WorkflowCompileError("unknown node type")
    if node_type in COMPOSITION_NODE_TYPES and not composition_enabled:
        # Disabled-by-default: composition is rejected fail-closed until a deployment enables
        # it after the authorization/RLS/recovery gates pass.
        raise WorkflowCompileError("composition nodes are not enabled")
    if node_type == "agent_loop" and not agent_loop_enabled:
        raise WorkflowCompileError("agent_loop nodes are not enabled")
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
    elif node_type == "agent_loop":
        _require_exact_keys(
            config,
            {
                "tool_binding_roles",
                "retrieval",
                "limits",
                "objective_key",
                "output_key",
                "system_prompt",
                "actions",
            },
            "agent_loop config",
            optional={
                "retrieval",
                "limits",
                "objective_key",
                "output_key",
                "system_prompt",
                "actions",
            },
        )
        from apps.agents.compiler import AgentCompileError, compile_agent

        agent_body = {
            "api_version": "agenthub/v1",
            "kind": "Agent",
            "metadata": {"id": "workflow_agent_loop", "owner": "workflow"},
            "spec": {
                "tools": config["tool_binding_roles"],
                **{key: value for key, value in config.items() if key != "tool_binding_roles"},
            },
        }
        try:
            compiled_agent = compile_agent(agent_body)
        except AgentCompileError as exc:
            raise WorkflowCompileError(f"agent_loop config is invalid: {exc}") from exc
        config = {
            "policy": {
                key: value
                for key, value in compiled_agent.config.items()
                if key not in {"api_version", "agent_id"}
            },
            "policy_checksum": compiled_agent.checksum,
        }
        if input_mapping is None or output_mapping is None:
            raise WorkflowCompileError("agent_loop node requires input_mapping and output_mapping")
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
    elif node_type == "event_wait":
        _require_exact_keys(
            config, {"event_role", "payload_schema", "timeout_seconds"}, "event_wait config"
        )
        _identifier(config.get("event_role"), "event_wait event_role")
        _validate_wait_schema(config.get("payload_schema"), "event_wait payload_schema")
        _wait_seconds(config.get("timeout_seconds"), "event_wait timeout_seconds")
        if output_mapping is None:
            raise WorkflowCompileError("event_wait requires output_mapping")
    elif node_type == "human_task":
        _require_exact_keys(
            config,
            {
                "decision_schema",
                "timeout_seconds",
            },
            "human_task config",
        )
        _validate_wait_schema(config.get("decision_schema"), "human_task decision_schema")
        _wait_seconds(config.get("timeout_seconds"), "human_task timeout_seconds")
        if output_mapping is None:
            raise WorkflowCompileError("human_task requires output_mapping")
    elif node_type == "timer":
        _require_exact_keys(config, {"delay_seconds"}, "timer config")
        _wait_seconds(config.get("delay_seconds"), "timer delay_seconds")
    elif node_type == "subworkflow":
        # Names a release-manifest child role only (ADR-0009); never an artifact id, url or
        # latest reference. The release compiler pins the exact child revision/checksum/lineage.
        _require_exact_keys(config, {"workflow_role", "max_depth"}, "subworkflow config")
        _identifier(config.get("workflow_role"), "subworkflow workflow_role")
        _validate_child_depth(config.get("max_depth"))
        if input_mapping is None or output_mapping is None:
            raise WorkflowCompileError("subworkflow node requires input_mapping and output_mapping")
    elif node_type == "retrieve":
        _require_exact_keys(
            config,
            {"retrieval_profile_ref"},
            "retrieve config",
            optional={"retrieval_profile_ref"},
        )
        if "retrieval_profile_ref" in config:
            _identifier(config.get("retrieval_profile_ref"), "retrieve retrieval_profile_ref")
    elif node_type == "parallel":
        _require_exact_keys(
            config,
            {"join", "max_concurrency", "max_duration_seconds", "max_state_bytes"},
            "parallel config",
            optional={"max_duration_seconds", "max_state_bytes"},
        )
        _identifier(config.get("join"), "parallel join")
        _bounded_int(config.get("max_concurrency"), 1, MAX_PARALLEL_CONCURRENCY)
        _bounded_int(
            config.get("max_duration_seconds", MAX_PARALLEL_DURATION_SECONDS),
            1,
            MAX_PARALLEL_DURATION_SECONDS,
        )
        _bounded_int(
            config.get("max_state_bytes", MAX_PARALLEL_STATE_BYTES),
            1,
            MAX_PARALLEL_STATE_BYTES,
        )
    elif node_type == "for_each":
        _require_exact_keys(
            config,
            {"items_path", "item_path", "max_items", "max_concurrency", "body_entry", "join"},
            "for_each config",
        )
        from apps.workflows.state_mapping import parse_pointer

        try:
            parse_pointer(config.get("items_path"))
            parse_pointer(config.get("item_path"))
        except MappingError as exc:
            raise WorkflowCompileError(exc.code) from None
        _bounded_int(config.get("max_items"), 1, MAX_FOR_EACH_ITEMS)
        _bounded_int(config.get("max_concurrency"), 1, MAX_PARALLEL_CONCURRENCY)
        if config["max_concurrency"] > config["max_items"]:
            raise WorkflowCompileError("WORKFLOW_BUDGET_EXCEEDED")
        _identifier(config.get("body_entry"), "for_each body_entry")
        _identifier(config.get("join"), "for_each join")
    elif node_type == "join":
        _validate_join_config(config)
    elif node_type in {"input", "validate_contract", "end"} and config:
        raise WorkflowCompileError(f"{node_type} node does not accept config")

    compiled_node: dict[str, Any] = {"id": node_id, "type": node_type, "config": config}
    if input_mapping is not None:
        compiled_node["input_mapping"] = input_mapping
    if output_mapping is not None:
        compiled_node["output_mapping"] = output_mapping
    if "retry_policy" in node:
        compiled_node["retry_policy"] = _validate_retry_policy(node["retry_policy"], node_type)
    if "compensation" in node:
        if node_type != "tool":
            raise WorkflowCompileError("only tool nodes may declare compensation")
        compiled_node["compensation"] = _identifier(
            node["compensation"], "compensation node reference"
        )
    return compiled_node


def _wait_seconds(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_WAIT_SECONDS:
        raise WorkflowCompileError(f"{label} must be between 1 and {MAX_WAIT_SECONDS}")
    return value


def _validate_wait_schema(value: Any, label: str) -> None:
    if not isinstance(value, dict) or value.get("type") != "object":
        raise WorkflowCompileError(f"{label} must be an object JSON Schema")
    if value.get("additionalProperties") is not False or not isinstance(
        value.get("properties"), dict
    ):
        raise WorkflowCompileError(f"{label} must define properties and deny additionalProperties")
    if len(str(value)) > 16_384:
        raise WorkflowCompileError(f"{label} is too large")


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
    _require_exact_keys(
        edge,
        {"from", "to", "when", "branch", "on_error"},
        "edge",
        optional={"when", "branch", "on_error"},
    )
    source = _identifier(edge.get("from"), "edge from")
    target = _identifier(edge.get("to"), "edge to")
    if source not in nodes or target not in nodes:
        raise WorkflowCompileError("edge references an unknown node")
    result: dict[str, Any] = {"from": source, "to": target}
    selectors = {key for key in ("when", "branch", "on_error") if key in edge}
    if len(selectors) > 1:
        raise WorkflowCompileError("WORKFLOW_ROUTE_INVALID")
    if "when" in edge:
        if not isinstance(edge["when"], bool):
            raise WorkflowCompileError("edge when must be boolean")
        if nodes[source]["type"] != "condition":
            raise WorkflowCompileError("only condition edges may define when")
        result["when"] = edge["when"]
    if "branch" in edge:
        if (
            nodes[source]["type"] not in {"parallel", "for_each"}
            and nodes[target]["type"] != "join"
        ):
            raise WorkflowCompileError("WORKFLOW_ROUTE_INVALID")
        result["branch"] = _identifier(edge["branch"], "edge branch")
    if "on_error" in edge:
        failure_class = edge["on_error"]
        if failure_class not in FAILURE_CLASSES | {"any"}:
            raise WorkflowCompileError("WORKFLOW_ERROR_ROUTE_INVALID")
        if nodes[source]["type"] in {"input", "end", "condition", "parallel", "for_each", "join"}:
            raise WorkflowCompileError("WORKFLOW_ERROR_ROUTE_INVALID")
        result["on_error"] = failure_class
    return result


def _validate_error_routes(edges: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if "on_error" not in edge:
            continue
        key = (edge["from"], edge["on_error"])
        if key in seen:
            raise WorkflowCompileError("WORKFLOW_ERROR_ROUTE_AMBIGUOUS")
        seen.add(key)


def _validate_compensations(
    nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]
) -> set[str]:
    targets: set[str] = set()
    for node in nodes.values():
        target_id = node.get("compensation")
        if target_id is None:
            continue
        target = nodes.get(target_id)
        if target is None or target_id == node["id"] or target["type"] not in {"tool", "transform"}:
            raise WorkflowCompileError("WORKFLOW_COMPENSATION_INVALID")
        if target.get("input_mapping") is None:
            raise WorkflowCompileError("WORKFLOW_COMPENSATION_INVALID")
        if target.get("compensation") is not None or any(edge["to"] == target_id for edge in edges):
            raise WorkflowCompileError("WORKFLOW_COMPENSATION_INVALID")
        targets.add(str(target_id))
    return targets


def _validate_retry_policy(value: Any, node_type: str) -> dict[str, Any]:
    if node_type not in {"retrieve", "generate", "custom", "transform"}:
        raise WorkflowCompileError("WORKFLOW_RETRY_POLICY_INVALID")
    policy = _mapping(value, "retry_policy")
    _require_exact_keys(
        policy,
        {"max_attempts", "backoff_seconds", "retry_on", "idempotent"},
        "retry_policy",
    )
    max_attempts = policy.get("max_attempts")
    backoff_seconds = policy.get("backoff_seconds")
    retry_on = policy.get("retry_on")
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= MAX_RETRY_ATTEMPTS
    ):
        raise WorkflowCompileError("WORKFLOW_RETRY_POLICY_INVALID")
    if (
        isinstance(backoff_seconds, bool)
        or not isinstance(backoff_seconds, int)
        or backoff_seconds != 0
    ):
        raise WorkflowCompileError("WORKFLOW_RETRY_POLICY_INVALID")
    if retry_on != ["transient"] or policy.get("idempotent") is not True:
        raise WorkflowCompileError("WORKFLOW_RETRY_POLICY_INVALID")
    return {
        "max_attempts": max_attempts,
        "backoff_seconds": backoff_seconds,
        "retry_on": ["transient"],
        "idempotent": True,
    }


def _validate_join_config(config: dict[str, Any]) -> None:
    _require_exact_keys(
        config, {"mode", "branches", "merge", "required"}, "join config", optional={"required"}
    )
    mode = config.get("mode")
    if mode not in {"all", "threshold", "fail_fast"}:
        raise WorkflowCompileError("WORKFLOW_JOIN_POLICY_INVALID")
    branches = config.get("branches")
    if not isinstance(branches, list) or not 1 <= len(branches) <= MAX_PARALLEL_BRANCHES:
        raise WorkflowCompileError("WORKFLOW_JOIN_POLICY_INVALID")
    canonical = [_identifier(item, "join branch") for item in branches]
    if len(set(canonical)) != len(canonical):
        raise WorkflowCompileError("WORKFLOW_JOIN_POLICY_INVALID")
    required = config.get("required")
    if mode == "threshold":
        if (
            not isinstance(required, int)
            or isinstance(required, bool)
            or not 1 <= required <= len(canonical)
        ):
            raise WorkflowCompileError("WORKFLOW_JOIN_POLICY_INVALID")
    elif "required" in config:
        raise WorkflowCompileError("WORKFLOW_JOIN_POLICY_INVALID")
    try:
        merge = compile_mappings(config.get("merge"), restrict_destination=True)
    except MappingError as exc:
        raise WorkflowCompileError(exc.code) from None
    owned = tuple(f"/branches/{name}/" for name in canonical)
    if any(not entry["from"].startswith(owned) for entry in merge):
        raise WorkflowCompileError("WORKFLOW_JOIN_POLICY_INVALID")
    config["branches"] = canonical
    config["merge"] = [dict(item) for item in merge]


def _validate_parallel_regions(
    nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], adjacency: dict[str, list[str]]
) -> None:
    owners = [node for node in nodes.values() if node["type"] in {"parallel", "for_each"}]
    branch_edges = [edge for edge in edges if "branch" in edge]
    for owner in owners:
        join_id = owner["config"]["join"]
        join = nodes.get(join_id)
        if join is None or join["type"] != "join":
            raise WorkflowCompileError("WORKFLOW_PARALLEL_REGION_INVALID")
        outgoing = [edge for edge in branch_edges if edge["from"] == owner["id"]]
        names = [edge["branch"] for edge in outgoing]
        expected = join["config"]["branches"]
        if owner["type"] == "for_each":
            if (
                names != ["for_each_items"]
                or expected != ["for_each_items"]
                or outgoing[0]["to"] != owner["config"]["body_entry"]
            ):
                raise WorkflowCompileError("WORKFLOW_PARALLEL_REGION_INVALID")
        elif (
            not names
            or len(names) > MAX_PARALLEL_BRANCHES
            or names != expected
            or len(set(names)) != len(names)
        ):
            raise WorkflowCompileError("WORKFLOW_PARALLEL_REGION_INVALID")
        for edge in outgoing:
            current = edge["to"]
            seen: set[str] = set()
            while current != join_id:
                if current in seen or nodes[current]["type"] in {"parallel", "for_each", "join"}:
                    raise WorkflowCompileError("WORKFLOW_PARALLEL_REGION_INVALID")
                seen.add(current)
                output_mapping = nodes[current].get("output_mapping")
                if owner["type"] == "parallel" and (
                    output_mapping is None
                    or any(
                        not item["to"].startswith(f"/branches/{edge['branch']}/")
                        for item in output_mapping
                    )
                ):
                    raise WorkflowCompileError("WORKFLOW_PARALLEL_REGION_INVALID")
                next_edges = [item for item in edges if item["from"] == current]
                if len(next_edges) != 1:
                    raise WorkflowCompileError("WORKFLOW_PARALLEL_REGION_INVALID")
                nxt = next_edges[0]
                if nxt.get("branch") != edge["branch"]:
                    raise WorkflowCompileError("WORKFLOW_PARALLEL_REGION_INVALID")
                current = nxt["to"]
    if branch_edges and not owners:
        raise WorkflowCompileError("WORKFLOW_PARALLEL_REGION_INVALID")


def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise WorkflowCompileError("WORKFLOW_BUDGET_EXCEEDED")
    return value


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


def _validate_child_depth(value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_CHILD_DEPTH:
        raise WorkflowCompileError(f"subworkflow max_depth must be 1..{MAX_CHILD_DEPTH}")


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
