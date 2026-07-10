# Task Plan: sprint-7-mcp-metrics-operations

## Task summary

Add an MCP ingress that reuses gateway authorization, production-safe telemetry,
operational alerts/runbooks, and draft OpenShift deployment boundaries.

## Background

Sprints 3–5 established the REST gateway, runtime, ingestion, and usage records.
Sprint 6 is adding evaluated promotion, canary, and rollback. Sprint 7 exposes the
same governed scenarios to MCP consumers and supplies the metrics needed to operate
those paths and assess canaries. Planning can proceed before Sprint 6 completes;
implementation must revalidate Sprint 6's final lifecycle events and routing seams.

## Scope

- MCP session authentication mapped to existing consumers and bindings.
- Versioned schemas for invoke, query, run status, ingestion status, and authorized
  retrieval debugging; approval is schema-reserved until Sprint 9 supplies it.
- Shared REST/MCP application services and identical capability decisions.
- OpenTelemetry propagation across ASGI and Celery boundaries.
- Bounded-cardinality Prometheus metrics for gateway, runtime, ingestion, eval, and
  release lifecycle behavior.
- Initial dashboards, alerts, runbooks, and OpenShift/NetworkPolicy/secret templates.
- Production readiness checks that distinguish required from degraded dependencies.

## Non-goals

- A second authorization model, public runtime/worker ingress, production cluster
  deployment, vendor-specific telemetry backends, tools/approvals, or agent runtime.
- Logging prompts, document bodies, tool payloads, tokens, or unbounded identifiers
  as metric labels.

## Acceptance criteria

- REST and MCP resolve the same authenticated consumer, binding, capability, tenant,
  scenario, and release for equivalent requests.
- MCP schema snapshots are versioned and incompatible changes fail contract tests.
- Scenario-level latency, errors, token usage, ingestion, eval, and promotion/canary
  signals are observable without sensitive data or unbounded cardinality.
- Trace context propagates through approved async work and invalid inbound trace
  context cannot override authorization or trusted actor attributes.
- Only the web workload receives external ingress; runtime, ingestion, eval, data
  stores, and scheduler remain private in deployment and NetworkPolicy templates.
- Alerts link to actionable runbooks and readiness fails safely for required services.

## Affected components

`gateway`, `identity`, `catalog`, `observability`, `ingestion`, `evaluations`,
`releases`, Celery configuration, settings, deployment manifests, tests, and docs.

## Interfaces affected

New MCP transport and versioned tool schemas; new metrics endpoint/collector output,
trace headers, readiness details, dashboards, alerts, and deployment templates. REST
contracts remain backward compatible.

## Data impact

No business-payload persistence is expected. Telemetry contains stable pseudonymous
IDs and aggregates subject to explicit retention. Avoid raw consumer IDs in metric
labels; use bounded scenario/release dimensions only where operationally approved.

## Security impact

MCP is a new externally reachable parser/transport boundary. Inputs require the same
schemas, size limits, rate limits, idempotency rules, and safe errors as REST. Metrics
and health endpoints must not expose secrets, topology, tenant data, or payloads.

## Authorization impact

Every MCP operation authenticates a `Consumer` and calls the existing binding and
capability policy. `retrieve_debug` additionally requires the explicit capability and
an internal-consumer policy. No MCP-supplied tenant, role, release, or scenario ID is
trusted.

## Observability impact

This sprint establishes stable event/metric names, request/trace propagation, label
budgets, sampling and redaction rules, SLO-oriented dashboards, and alert ownership.
Security/business audit remains separate from application telemetry.

## Migration impact

Prefer no schema migration. Any trace/telemetry persistence must be additive and
separately justified. Deployment resources are templates until reviewed per target
environment.

## Dependencies

Sprints 3–5 verified behavior and the final Sprint 6 lifecycle/routing contracts. OTel,
Prometheus, Grafana, cluster ingress, secret manager, and network policy conventions
require environment-specific operator validation. New production packages require
explicit approval.

## Implementation steps

1. Freeze shared transport-independent invocation/status services and MCP schemas.
2. Add MCP authentication, validation, error mapping, rate limiting, and operations.
3. Instrument ASGI/runtime/Celery boundaries with redacted traces and bounded metrics.
4. Add readiness dependency classification and telemetry failure behavior.
5. Add dashboards, alert rules, ownership, and incident/runbook drafts.
6. Add OpenShift workload, secret/config, service account, ingress, and default-deny
   NetworkPolicy templates.
7. Add contract, authorization, isolation, cardinality, propagation, and manifest
   policy tests; update current-state documentation after verification.

## Test plan

- REST/MCP parity for happy path, auth failure, capability denial, cross-tenant alias,
  canary routing, rate limiting, and safe error envelopes.
- MCP malformed/oversized/deep input, unknown fields/tools, replay, and debug denial.
- Schema snapshot compatibility and transport-independent domain tests.
- Trace propagation across Celery, invalid header handling, redaction, and exporter
  outage behavior.
- Metric label/cardinality assertions and absence of tokens, payloads, and PII.
- Prometheus rule tests, dashboard lint, manifest render/schema/policy checks, and
  verification that only web has external ingress.

## Rollout plan

Deploy instrumentation with exporters disabled or sampled, establish baselines, then
enable dashboards/alerts before exposing MCP to an allowlisted consumer cohort.
Apply manifests through environment review; do not infer production readiness from
template validation.

## Rollback plan

Disable MCP routing and exporters by configuration while preserving REST. Revert
alerts/dashboards independently. Roll back additive deployment resources in dependency
order; retain audit and canonical usage data.

## Risks

- Transport drift could create an authorization bypass.
- High-cardinality or sensitive telemetry can create cost and privacy incidents.
- Exporter failure could affect requests if instrumentation is not fail-open and
  bounded; security audit failure semantics remain independently fail-closed.
- Draft network policies can cause outage or unintended reachability if applied
  without environment-specific review.

## Open questions

- Telemetry retention, sampling, label budget, SLOs, and alert owners.
- OpenShift namespaces, routes, service accounts, approved egress destinations, and
  secret resolver integration.
- Whether automatic canary abort is Sprint 7 scope or remains a later approved task.

## Approved decisions

- Initial MCP ingress is restricted to the internal network/VPN and authenticates
  through the existing `ConsumerToken` model. Public internet exposure is out of scope.
- Telemetry uses OpenTelemetry Collector, Prometheus, and Grafana. PostgreSQL remains
  the canonical store for usage and audit records.
- Sprint 7 produces deployable OpenShift manifest drafts but does not deploy them to a
  live cluster. Network policy is default-deny, and only `agenthub-web` receives
  external ingress.
- These decisions were approved by the project owner on 2026-07-10.

## Status

Planned; implementation waits for Sprint 6 contract revalidation and required
security, dependency, public-interface, and network approvals.

## Completion criteria

Applicable Definition of Done gates pass on SQLite and PostgreSQL; MCP parity,
authorization/isolation, telemetry redaction/cardinality, alert, trace, and manifest
evidence is recorded. Cluster deployment and live backend checks are explicitly
verified or reported as unavailable.
