"""Bounded-cardinality Prometheus metrics for AgentHub request paths."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

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
INGESTION_BUILD_JOBS = Counter(
    "agenthub_ingestion_build_jobs_total",
    "Durable staged-index job transitions.",
    ("status", "failure_class"),
    registry=REGISTRY,
)
INGESTION_WORKER_COMPATIBLE = Gauge(
    "agenthub_ingestion_worker_compatible",
    "Whether a recent contract/config-compatible ingestion worker exists.",
    registry=REGISTRY,
)
INGESTION_WORKER_HEARTBEAT_AGE = Gauge(
    "agenthub_ingestion_worker_heartbeat_age_seconds",
    "Age of the freshest contract/config-compatible ingestion worker heartbeat.",
    registry=REGISTRY,
)
INGESTION_OLDEST_QUEUE_AGE = Gauge(
    "agenthub_ingestion_oldest_queue_age_seconds",
    "Age of the oldest durable staged-index job awaiting claim.",
    registry=REGISTRY,
)
INGESTION_CLAIM_LATENCY = Histogram(
    "agenthub_ingestion_claim_latency_seconds",
    "Delay from durable queue publication to worker claim.",
    registry=REGISTRY,
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
)
INGESTION_BUILD_DURATION = Histogram(
    "agenthub_ingestion_build_duration_seconds",
    "Duration from staged-index worker claim to terminal success.",
    registry=REGISTRY,
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800),
)
INGESTION_RECONCILIATIONS = Counter(
    "agenthub_ingestion_reconciliations_total",
    "Bounded staged-index reconciliation outcomes.",
    ("outcome",),
    registry=REGISTRY,
)
EVAL_CASES = Counter(
    "agenthub_eval_cases_total",
    "Evaluation case outcomes.",
    ("status",),
    registry=REGISTRY,
)
QUESTION_EVAL_CASES = Counter(
    "agenthub_question_eval_cases_total",
    "Question evaluation case outcomes.",
    ("kind", "status"),
    registry=REGISTRY,
)
QUESTION_EVAL_RUNS = Counter(
    "agenthub_question_eval_runs_total",
    "Question evaluation terminal outcomes.",
    ("kind", "status"),
    registry=REGISTRY,
)
QUESTION_EVAL_DURATION = Histogram(
    "agenthub_question_eval_duration_seconds",
    "Question evaluation wall-clock duration.",
    ("kind",),
    registry=REGISTRY,
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900, 1800),
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
UNIFIED_RUN_ADMISSIONS = Counter(
    "agenthub_unified_run_admissions_total",
    "Canonical unified Run admissions by bounded execution mode.",
    ("execution_mode",),
    registry=REGISTRY,
)
UNIFIED_RUN_EVENTS = Counter(
    "agenthub_unified_run_events_total",
    "Canonical unified Run lifecycle events by closed event type.",
    ("event_type",),
    registry=REGISTRY,
)
RUNTIME_CONTROL_CHANGES = Counter(
    "agenthub_runtime_control_changes_total",
    "Runtime-control decisions by bounded scope, action and outcome.",
    ("scope", "action", "outcome"),
    registry=REGISTRY,
)
RUNTIME_SUSPENSION_BLOCKS = Counter(
    "agenthub_runtime_suspension_blocks_total",
    "Unified runtime work blocked by a persisted suspension at a safe boundary.",
    ("boundary",),
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
SUPERADMIN_EVENTS = Counter(
    "agenthub_superadmin_events_total",
    "Exceptional superadmin activity by bounded event kind.",
    ("kind",),
    registry=REGISTRY,
)

# --- P2.6.11 orchestration-structure telemetry (bounded labels only) ----------------------
WORKFLOW_BRANCHES = Counter(
    "agenthub_workflow_branches_total",
    "Parallel/for_each branch terminal outcomes.",
    ("outcome",),
    registry=REGISTRY,
)
WORKFLOW_JOINS = Counter(
    "agenthub_workflow_joins_total",
    "Join terminal outcomes by policy mode.",
    ("mode", "outcome"),
    registry=REGISTRY,
)
WORKFLOW_WAITS = Counter(
    "agenthub_workflow_waits_total",
    "Durable wait lifecycle phases by kind.",
    ("kind", "phase"),
    registry=REGISTRY,
)
WORKFLOW_RETRIES = Counter(
    "agenthub_workflow_retries_total",
    "Scheduled workflow node retries by failure class.",
    ("failure_class",),
    registry=REGISTRY,
)
WORKFLOW_COMPENSATIONS = Counter(
    "agenthub_workflow_compensations_total",
    "Compensation entry terminal outcomes.",
    ("outcome",),
    registry=REGISTRY,
)
WORKFLOW_CHILDREN = Counter(
    "agenthub_workflow_children_total",
    "Child (sub-workflow/agent) link terminal outcomes.",
    ("kind", "status"),
    registry=REGISTRY,
)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)
