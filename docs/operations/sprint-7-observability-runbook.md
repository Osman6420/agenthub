# Sprint 7 Observability Runbook

## Scope and safety

The dashboard and alerts use aggregate telemetry. PostgreSQL remains canonical for
usage and audit. Never paste bearer tokens, prompts, document bodies, consumer data,
or raw eval/tool payloads into incidents, logs, dashboards, or tickets.

## Gateway errors

1. Confirm whether failures affect REST, MCP, or both and identify the bounded operation.
2. Check readiness and recent deployments without exposing dependency details publicly.
3. Correlate safe request/trace IDs with application logs and canonical audit/usage.
4. Disable MCP independently if only MCP fails; do not bypass authorization or audit.
5. Roll back the application only when database compatibility has been verified.

## Latency

1. Separate gateway, runtime/provider, retrieval, database, Redis, and exporter latency.
2. Confirm telemetry export queues are bounded and are not blocking request handling.
3. Check worker queue depth and provider deadlines; do not increase timeouts blindly.
4. Reduce or disable MCP exposure before changing tenant rate limits or safety gates.

## MCP denials

1. Determine whether denials are expected client mistakes or a credential/binding attack.
2. Verify the consumer, binding, capability, and scenario without copying tokens.
3. Revoke a compromised token and preserve audit evidence.
4. Never grant `retrieve_debug` merely to silence a denial alert.

## Telemetry outage

Telemetry export is fail-open and bounded; security/business audit semantics are
independent. Restore the collector/backend, confirm backlog limits, and record the
visibility gap. Do not claim missing telemetry as successful request evidence.
Prometheus uses a secret-backed bearer token in addition to private network controls;
rotate the token through the external secret manager and never paste it into incidents.

## Orchestration alerts (P2.6.11)

Bounded-label series `agenthub_workflow_branches_total{outcome}`,
`agenthub_workflow_joins_total{mode,outcome}`, `agenthub_workflow_waits_total{kind,phase}`,
`agenthub_workflow_retries_total{failure_class}`,
`agenthub_workflow_compensations_total{outcome}` and
`agenthub_workflow_children_total{kind,status}` back the alerts below. Labels carry no
tenant/run/artifact identifiers; use structured logs, traces and audit (which do) to locate
the affected tenant/run.

### Queue saturation

`AgentHubQueueSaturation` fires when the oldest queued work has waited over 15 minutes.
Check worker liveness (`agenthub_ingestion_worker_compatible`), Celery concurrency and
Redis. Do not enable additional org concurrency while this is firing.

### Stuck waits

`AgentHubStuckWaits` fires when durable waits expire rather than resume. Inspect the
tenant's workflow trace (Workflow izleri) for `event_wait`/`human_task`/`timer` nodes past
deadline; confirm event delivery / human-task routing. Expired waits fail closed.

### Retry storm

`AgentHubRetryStorm` fires on elevated `retry_wait` transitions. Identify the failing node
class from `failure_class`; a `transient` storm usually points at a flapping dependency.
Retries are bounded (max 3) — a storm means many runs are retrying, not one runaway run.

### Compensation failure

`AgentHubCompensationFailure` (page) fires when a compensation entry is `blocked`. This
needs operator recovery via the workflow-recovery surface; the run holds durable state and
will not silently drop the compensation.

### Budget / kill-switch

`AgentHubBudgetKillSwitch` fires when agent runs fail at an elevated rate — typically budget
caps (steps/tokens/tool-calls) or the `AgentRuntimeControl` kill switch being engaged. Check
whether the global/per-org runtime is suspended (`resume_agent_runtime` to restore) before
assuming a code fault.

## Rollback

Set `MCP_ENABLED=false`, `METRICS_ENABLED=false`, or clear
`OTEL_EXPORTER_OTLP_ENDPOINT` independently. Existing REST, canonical usage, and audit
remain enabled. Network and deployment templates require environment-owner review
before application or rollback.
