# Threat Model: sprint-7-mcp-metrics-operations

## Assets

Consumer credentials and sessions, tenant bindings, release routing, MCP/REST
contracts, runtime availability, traces/metrics/logs, operational topology, alert
integrity, deployment identities, and secrets.

## Actors

Authenticated consumers, internal debug consumers, tenant operators, platform/SRE
operators, telemetry collectors, compromised clients, and external attackers.

## Entry points

MCP ingress/session negotiation and tool calls, trace headers, metrics/readiness
endpoints, exporter protocols, dashboards/alerts, deployment configuration, and
management access to workloads.

## Trust boundaries

External MCP client to web; transport adapter to shared authorization/runtime service;
web/worker to collector; collector to telemetry backend; cluster ingress/service
account/network policy to private workloads; configuration references to secrets.

## Data classifications

Credentials and secret values are restricted. Prompts, documents, outputs, and debug
retrieval results may be confidential. Tenant/release/consumer identifiers and traces
are internal/pseudonymous. Aggregate service metrics are operational internal data.

## Authentication

MCP identity maps server-side to the existing consumer authentication model; no
self-asserted session subject is accepted. Operator and telemetry backend access use
separate least-privilege workload identities. Metrics exposure is private or
authenticated according to the approved topology.

## Authorization

MCP invokes the same action/object/capability checks as REST. Debug retrieval requires
an explicit capability and internal-consumer eligibility. Health and telemetry access
does not confer application access and never accepts tenant scope from the caller.

## Tenant isolation

Alias, run, ingestion, release, and debug lookups are constrained to the authenticated
consumer's authorized organization/scenario. Trace baggage is untrusted metadata and
cannot set tenant, actor, capability, or release context.

## External systems

MCP clients, OTel collector/backend, Prometheus/Grafana, OpenShift ingress/API, secret
manager, Postgres, Redis, object store, and approved provider endpoints. Connections
require TLS where appropriate, timeouts, size limits, least privilege, and explicit
destinations.

## Abuse cases

- Use MCP differences to bypass a REST binding, rate limit, or canary decision.
- Enumerate tools, aliases, runs, ingestion jobs, chunks, tenants, or topology.
- Inject oversized/deep messages or high-cardinality labels to exhaust resources.
- Smuggle tenant/actor data through trace headers or forge trusted spans.
- Exfiltrate prompts, tokens, PII, debug chunks, or secrets through telemetry.
- Scrape metrics/readiness publicly or poison dashboards and alerts.
- Reach workers, databases, or collectors through permissive ingress/egress policies.

## Failure cases

Malformed MCP frames, disconnect/replay, collector latency/outage, broken propagation,
metric explosion, alert storms/silence, stale readiness, unavailable dependencies,
and incorrect NetworkPolicy or secret references.

## Logging and audit risks

Protocol errors and span attributes can capture complete arguments or authorization
headers. Use allowlisted attributes, redaction, truncation, sampling, and stable safe
reason codes. Audit authorization-sensitive MCP decisions separately; telemetry
delivery failure must not masquerade as audit success.

## Mitigations

One shared policy/application-service path; strict versioned schemas and bounds;
authenticated sessions; per-consumer rate limits; deny-by-default debug capability;
untrusted trace-header normalization; bounded label allowlists; private telemetry
endpoints; exporter deadlines/queues; default-deny NetworkPolicies; workload-specific
service accounts; secret references only; rule/manifest tests and staged rollout.

## Residual risks

Backend administrators can correlate pseudonymous telemetry. Template policies cannot
prove live-cluster isolation. MCP client/protocol interoperability and telemetry volume
need production-like load evidence. Compromised valid consumers retain their granted
capabilities until revoked.

## Required security tests

REST/MCP authorization parity; unauthenticated/expired/replayed session denial;
cross-tenant run/ingestion/debug denial; schema fuzz and size/depth bounds; rate-limit
parity; trace-baggage privilege injection denial; telemetry secret/PII scanning;
cardinality limits; private metrics/readiness access; exporter outage containment; and
manifest tests proving no external runtime/worker/data-store ingress.
