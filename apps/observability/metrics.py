"""Bounded-cardinality Prometheus metrics for AgentHub request paths."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "agenthub_gateway_requests_total",
    "Gateway and MCP HTTP requests.",
    ("transport", "operation", "status"),
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "agenthub_gateway_request_duration_seconds",
    "Gateway and MCP HTTP request latency.",
    ("transport", "operation"),
    registry=REGISTRY,
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
INGESTION_RUNS = Counter(
    "agenthub_ingestion_runs_total",
    "Ingestion run outcomes.",
    ("status",),
    registry=REGISTRY,
)
EVAL_CASES = Counter(
    "agenthub_eval_cases_total",
    "Evaluation case outcomes.",
    ("status",),
    registry=REGISTRY,
)
RELEASE_LIFECYCLE = Counter(
    "agenthub_release_lifecycle_total",
    "Release lifecycle decisions.",
    ("action", "outcome"),
    registry=REGISTRY,
)
RUNTIME_REQUESTS = Counter(
    "agenthub_runtime_requests_total",
    "Canonical runtime usage-event outcomes.",
    ("operation", "status"),
    registry=REGISTRY,
)
TOKENS = Counter(
    "agenthub_tokens_total",
    "Canonical input and output token usage.",
    ("operation", "direction"),
    registry=REGISTRY,
)
WORKFLOW_RUNS = Counter(
    "agenthub_workflow_runs_total",
    "Durable workflow run state transitions.",
    ("status",),
    registry=REGISTRY,
)
WORKFLOW_NODES = Counter(
    "agenthub_workflow_nodes_total",
    "Completed workflow nodes by bounded registry type.",
    ("node_type",),
    registry=REGISTRY,
)
AGENT_RUNS = Counter(
    "agenthub_agent_runs_total",
    "Durable agent run state transitions.",
    ("status",),
    registry=REGISTRY,
)
AGENT_STEPS = Counter(
    "agenthub_agent_steps_total",
    "Completed agent steps by bounded decision type.",
    ("decision",),
    registry=REGISTRY,
)
TOOL_INVOCATIONS = Counter(
    "agenthub_tool_invocations_total",
    "Terminal tool-invocation outcomes.",
    ("status",),
    registry=REGISTRY,
)
TOOL_APPROVALS = Counter(
    "agenthub_tool_approvals_total",
    "Tool approval decisions.",
    ("decision",),
    registry=REGISTRY,
)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)
