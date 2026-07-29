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

Phase 2.8 Part 4 makes scenario authoring preset-led and scenario-local. Empty Workflow, Document
Answer and Agent Loop create one compiler-validated mutable draft and no release. Workflow drafts
carry a stable logical-artifact description; every published immutable version carries a separate
exact-version description. Candidate manifests are prepared through a tenant-scoped
`artifact type → logical artifact → exact version` selector that exposes descriptions, checksum and
bounded dependency impact but never artifact bodies. The server re-resolves every submitted ID,
enforces the closed role/type contract and compiles through the canonical release compiler.
Invocation examples use the active alias and the release-pinned execution-mode analysis. Studio AI
authoring has a safe deployment preflight and remains candidate-only.

Phase 2.8 Part 5 makes an exact draft document-set membership part of every new document upload
transaction; standalone creation is denied and the elevated storage inventory is no longer a normal
navigation destination. Staged indexes pin immutable chunking and retrieval artifact versions plus
optional exact model/prompt summary provenance. Every per-index PostgreSQL store contains both
pgvector and `simple` full-text indexes under the same FORCE-RLS tenant policy. Keyword and vector
candidates therefore share the tenant, consumer grant, pinned set-version, active-index and
tombstone intersection; hybrid mode combines their ranks with weighted reciprocal-rank fusion and
returns component diagnostics. A set preparation policy may enqueue an idempotent staged build
after publish, but only the separately authorized promotion action can change the active index.
Historical set, document and index versions remain deep-linkable. Existing unbound rows are exposed
only by a non-mutating inventory command; destructive cleanup remains separately gated.

Retrieval profiles may additionally enable bounded hierarchical summary routing. The first stage
searches only derived `summary` chunks and selects exact live `DocumentVersion` IDs; the second
stage searches only original `content` chunks inside that authorized document scope and applies a
per-document diversity cap. Summaries therefore route retrieval but never become the grounding
passage in this mode. If no authorized summary matches, the provider falls back to direct content
retrieval. Both stages use the same active per-index FORCE-RLS store and server-derived ACL scope.

Phase 2.8 Part 6 adds organization-owned reusable question sets with mutable drafts and immutable
published versions/cases. Retrieval evaluations pin the exact question-set version, document-set
version, index and retrieval artifact; answer evaluations pin the exact scenario release and may
also pin an approved judge model and prompt revision. Retrieval hit@k, recall@k and MRR remain
separate from deterministic answer pass rates, with explicit applicable and unscored denominators.
The optional LLM judge is disabled by default, schema-validated and records only a verdict, safe
reason code and immutable provenance.

Evaluation workers use an internal operator-test retrieval path only after server-side
document-set authorization. It preserves tenant, set-version and index filters but does not create
or reuse consumer grants. Stored retrieval evidence contains bounded pointers, ranks, checksums and
scores rather than copied chunk bodies; the console resolves exact retained chunk text only for an
authorized reader. One-off document/scenario questions do not create benchmark runs or change
aggregate metrics. Evaluation tables use direct tenant lineage and PostgreSQL FORCE RLS, lifecycle
events are audited without content, and expired generated answers/retrieval evidence can be
redacted unless legal hold applies.

Phase 2.8 Part 7 keeps every native execution, evaluation, ingestion, index-build and connector-sync
table authoritative while presenting one bounded organization-scoped operations projection. The
projection uses closed kinds/status groups, tenant-first querysets, a 90-day maximum range, ten-page
maximum and fifty rows per page; it exposes only safe metadata and routes actions back through each
native authorization boundary.

Durable runtime suspension now has exact platform, organization, project and scenario scopes.
Admission, background claim and every non-terminal transition check the effective hierarchy;
suspended work retains its durable state and stops cooperatively at a transition boundary rather
than being mass-cancelled. Pause/resume and individual execution cancellation are distinct,
CSRF-protected, capability-authorized and fail-closed audited actions. Document-set quarantine is a
separate document-manager control: it prevents new/claimed ingestion, index and connector work
without granting document content access. Automatic and policy controls require privileged resume,
and exceptional superadmin actions keep their dedicated high-severity audit and alert path.

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
