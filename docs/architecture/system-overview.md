# System Overview

## Verified current system

The repository contains an executable Django modular monolith. Foundation,
tenant/identity/catalog, artifact/release, gateway/ExecutionContext, and the
deterministic RAG runtime slices are implemented and verified. The authoritative
milestone status and evidence links are maintained in the
[master plan](../planning/master-plan.md).

Sprint 7 adds a verified MCP/operations slice: `/mcp/` authenticates existing
consumer tokens and delegates invoke/query to the gateway policy and release-routing
path; `/internal/metrics` exposes bounded Prometheus metrics to an authenticated private
scraper; HTTP and Celery propagate W3C trace context to an allowlisted optional OTLP
collector; and deployment, dashboard, alert, and runbook drafts live under `deploy/`.
Automated verification includes the completed Sprint 6 routing contract; live platform
infrastructure verification remains pending.

Sprint 8 adds the verified workflow core: reviewed DSL artifacts compile to immutable
DAGs, releases pin the exact definition/checksum, and the gateway starts durable async
runs authorized by `workflow_run`. Workers claim by run id, enforce graph/state/time
bounds, persist redacted events, and expose tenant-scoped status/cancel. Custom nodes
are pre-installed allowlisted extensions, not uploaded code or external-tool access.

Sprint 9 adds the governed tool boundary: immutable tenant-scoped tool
definitions/bindings pin into releases; a default-deny proxy enforces capability,
contracts, field allowlists, SSRF-safe egress, and `secret:<name>` resolution; a durable
approval lifecycle (separation-of-duties, checksum binding, expiry, idempotent resume,
uncertain-outcome handling) gates high-risk side-effecting calls; and a workflow `tool`
node pauses for approval and resumes. Real HTTPS/MCP egress is opt-in; the default
adapter opens no socket. Approvals are operator actions (console + management commands).

The exact current artifact schemas, workflow/agent DSL, release roles and authoring limits are
documented in the
[Artifact ve DSL Yazım Kılavuzu](artifacts-and-dsl-authoring-guide.md).

Phase 2.5 Part 8 adds disabled-by-default OpenAI-compatible inbound adapters without an
OpenAI dependency or outbound call. A REST consumer may use `/v1/chat/completions` for synchronous
RAG or `/v1/responses` for synchronous RAG and background workflow/agent creation. The required
`model` value is the consumer-bound generated scenario alias, not a provider model or raw database
identifier. MCP and HTTPS enforce their corresponding consumer protocol and both retain the same
binding/capability, active/canary release, input/output contract, idempotency, audit and usage
governance. History is bounded, text-only and request-scoped; streaming, multimodal input, client
tools/functions and request-side governance overrides are intentionally unsupported.

Phase 2.8 Part 1 makes `/console/` the selected organization home and reduces primary navigation to
Ana Sayfa, Projeler, Dokümanlar, İstemciler and Çalıştırmalar. Scenarios live under projects; artifact, release,
DSL and run-subtype details remain reachable from their owning context. Legacy global catalogue GET
routes redirect to authorized contextual destinations while canonical detail and mutation routes
retain their contracts. Active organization remains a presentation filter derived from allowed
scope, never an authorization input. The
[Part 1 verification record](../planning/archive/phase-2-8-part-1-console-information-architecture-2026-07-22/verification.md)
is the status authority for automated and remaining manual/PostgreSQL evidence.

Phase 2.8 Part 2 removes the cross-organization workspace state. Session selection is revalidated
on every request and only narrows already-authorized querysets; authorized deep links align the
workspace only after exact-object authorization. Platform organization creation atomically creates
the initial organization-admin membership. Membership lifecycle services lock the organization and
target row, preserve at least one organization admin, and write required audit events in the same
transaction. `document_manager` extends document/set/source/index authority without entering the
scenario, consumer, release or membership role sets. Project, document-set and consumer creation
derive organization from the active workspace; scenario creation derives project from its
authorized contextual route.

## Target architecture

[`agenthub-v3-django-plan.md`](../../agenthub-v3-django-plan.md) defines the full
target. Later slices—including external model providers and agent execution—remain
planned unless the master plan records verification. Sprint 7 deployment assets are
verified drafts, not applied production infrastructure.

Major proposed flow: trusted ingress authenticates a consumer, resolves tenant/scenario capability, and creates an execution context; the pinned release drives RAG/workflow/agent execution; tool access passes through a controlled proxy; state changes and security decisions produce audit events. This is a design summary, not evidence of implementation.

## Versioning baseline

- The target document is revision 3; this revision number is not an AgentHub product/API version.
- The system is implemented as a greenfield AgentHub and has no runtime, build, or migration dependency on a v2 application or the archived RAGaaS documents.

## Assumptions requiring confirmation

- A modular monolith remains the intended initial deployment boundary.
- External providers and operational ownership have not yet been selected.

Update this document only from implemented code/configuration and verified runtime behavior. Record durable deviations from the target in ADRs.
