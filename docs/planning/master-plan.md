# AgentHub Master Plan

## Purpose

Track project-level intent without treating target designs as implemented behavior. Detailed target design remains in [`agenthub-v3-django-plan.md`](../../agenthub-v3-django-plan.md); `v3` in that filename means document revision 3, not a product generation.

## Current state

As of 2026-07-13, Sprints 0–11 and Phase 2 P1 (live chat), P2 (content plane & storage), P3 (real
embeddings + staged blue/green indexing), P4 (document-ACL retrieval + FORCE RLS + pointer-flip
promotion — the security core; real ACL-scoped tenant RAG is now servable), P5 (real
retrieve/generate wired into the agent loop + workflow nodes, with per-node prompt/model binding), and
P6 (authored, governed agent system prompt), P7.1 (the deny-by-default `DocumentParser` interface +
dependency-free stdlib parsers — text/markdown/csv/json/html — wired into the staged-build
text-extraction seam), and P7.2 (local pdf/docx/xlsx parsers on the same interface via owner-approved
pdfplumber + python-docx + openpyxl, no egress) are implemented and verified. Phase 2 implementation
and P8.1 + P8.2 (the document-plane operator console UI — tenant-scoped list, author-gated upload,
cross-tenant-safe soft-delete, and the full document-set lifecycle: create → draft version → add
member → publish) are implemented and verified. Phase 2 implementation is in progress (next: P7.3
external OCR egress and P7.4 Confluence/generic-REST connectors, **deferred by the owner and blocked
on their egress sign-off**; and P8.3–P8.4 console UI for scenario binding/grants and purge, no gate);
later live-egress/dependency milestones retain their explicit gates.

- Sprint 0: bootable Django modular-monolith skeleton — settings split, Celery role
  definitions, unauthenticated health probes, dependency manifest + lockfile, Docker
  Compose (pgvector/Redis/MinIO + web/worker/beat), CI enforcing lint/format/type/
  migration-drift/tests. See [`sprint-0-foundation`](../tasks/sprint-0-foundation/plan.md).
- Sprint 1: `tenancy`, `identity`, `catalog`, `audit`, and a custom `console`.
  Organizations/memberships with server-side tenant isolation; consumers/bindings
  with a capability allowlist and fail-closed resolution; projects/scenarios/aliases
  with organization-unique aliases; an append-only audit trail; and an
  LDAP-authenticated operator console (Django Admin removed as the management
  surface). Verified on SQLite and real PostgreSQL. See
  [`sprint-1-tenant-identity-catalog`](../tasks/sprint-1-tenant-identity-catalog/plan.md)
  and [ADR-0001](../adr/0001-custom-console-ldap-auth.md).
- Sprint 2: `artifacts` (immutable, checksummed, secret-safe versioned definitions)
  and `releases` (compiled `ScenarioRelease` with a DB-enforced single-active
  invariant, a deterministic manifest checksum, and a minimal atomic promote).
  GitOps import/export + `validate_artifacts`/`compile_release` commands; console
  Artifacts/Releases screens. Verified on SQLite and PostgreSQL; the operator flow
  (import → validate → compile → promote) ran end-to-end. See
  [`sprint-2-artifacts-releases`](../tasks/sprint-2-artifacts-releases/plan.md).
- Sprint 3: the public `gateway` (DRF) — bearer-token consumer auth (`ConsumerToken`,
  hashed), alias+capability authorization, per-consumer rate limiting, idempotency,
  a standard error envelope, a signed short-lived `ExecutionContext`, and
  `POST /v1/invoke` / `POST /v1/query` / `GET /v1/runs/{id}`. Input is validated
  against the release input contract; a `UsageEvent` and audit are recorded. Verified
  on SQLite and PostgreSQL and live end-to-end. See
  [`sprint-3-gateway-execution-context`](../tasks/sprint-3-gateway-execution-context/plan.md).
- Sprint 4: the synchronous RAG runtime — `retrieval` (provider interface + static
  default) and `orchestration` (model-provider interface + deterministic stub,
  release-bundle resolver cached by immutable release id, and the `run_rag` engine).
  Governance: grounding threshold + fallback, runtime-generated citations, and
  output-contract validation (invalid model output never reaches the client). The
  gateway now returns real `completed`/fallback output with token usage. Verified on
  SQLite and PostgreSQL and live end-to-end. See
  [`sprint-4-rag-runtime`](../tasks/sprint-4-rag-runtime/plan.md).

Control-plane authoring now provides governed create-only console forms and
idempotent GitOps import for organizations, projects, scenarios/aliases, consumers,
and bindings, with tenant/role enforcement and transactional audit. It is verified
on SQLite and PostgreSQL. See
[`control-plane-authoring`](../tasks/control-plane-authoring/plan.md).

Sprint 5 now provides governed ingestion, staged pgvector/HNSW indexes, source
advisory locks, retry/dead-letter audit, bounded HTTPS/S3 connectors, and
tenant/pinned-index cosine retrieval. It is verified on SQLite and PostgreSQL; see
[`sprint-5-ingestion-pgvector`](../tasks/sprint-5-ingestion-pgvector/plan.md).

Sprint 6 is complete: governed evaluation and a fail-closed release lifecycle.
An `eval_suite` artifact (bounded, allowlisted deterministic assertions) is validated
at author time; `apps.evaluations` runs a candidate against its pinned suite in
isolation and stores a redacted, audited report; `promote` requires a passing eval and
ready tenant-owned pinned indexes, and `rollback` atomically restores a superseded
release. Releases can pin `index_versions`, which the resolver now feeds to the
retriever (closing the earlier end-to-end retrieval gap). Verified on SQLite and
PostgreSQL; see
[`sprint-6-eval-promotion-rollback`](../tasks/sprint-6-eval-promotion-rollback/plan.md).
Consumer-scoped, time-bounded canary routing, role-gated console lifecycle actions,
and eval/promote/rollback/start-canary/stop-canary commands are delivered and verified.

Sprint 7 is implemented and verified: authenticated stateless MCP
ingress reuses the REST gateway policy
and release-routing seam; bounded Prometheus metrics project canonical usage/ingestion/
eval/release events; W3C trace context propagates through HTTP and Celery with optional
OTLP export; readiness checks migration state; and reviewed dashboard, alert, runbook,
ExternalSecret, workload, and default-deny OpenShift drafts are present. SQLite and
PostgreSQL suites pass, including parity against the completed Sprint 6 routing
contract. Live OTel/Prometheus/Grafana/OpenShift validation remains an operational
follow-up because deployment is outside the sprint scope. See
[`sprint-7-mcp-metrics-operations`](../tasks/sprint-7-mcp-metrics-operations/plan.md).

Sprint 8 is implemented and verified: strict workflow/custom-node artifacts compile to
immutable checksummed DAGs; built-in nodes execute through a bounded asynchronous Celery
runtime with durable redacted runs/events, idempotent start/redelivery, tenant-scoped
status/cancel, output contract/policy enforcement, and release pins. Custom nodes must
be active, organization-allowlisted, pre-installed with an exact package version, and
schema-valid before/after execution. Workflow output/trajectory assertions reuse the
Sprint 6 eval and promotion gate. See
[`sprint-8-workflow-core`](../tasks/sprint-8-workflow-core/plan.md).

Sprint 9 is implemented and verified: `apps.tools` is a governed tool registry +
execution boundary. Immutable tenant-scoped `ToolDefinition`/`ToolBinding` artifacts
pin into releases; a default-deny proxy enforces capability, contracts, field
allowlists, SSRF-safe egress (public-unicast-only, DNS-rebinding defense), and
least-privilege `secret:<name>` resolution; a durable approval lifecycle adds
separation-of-duties, a request-checksum binding, 30-minute expiry, idempotent resume,
and `outcome_unknown` handling. A workflow `tool` node pauses for approval and resumes.
Real egress (stdlib HTTPS/MCP adapters) is opt-in via `TOOL_ADAPTER`; the default is a
no-egress deterministic adapter, so tests make no outbound call. No new production
dependency was added. See [`sprint-9-tool-registry-approval`](../tasks/sprint-9-tool-registry-approval/plan.md).

Sprint 10 is implemented and verified: `apps.agents` is a durable, bounded agent runtime.
An `agent_definition` artifact (data, not code) compiles to an immutable checksummed
config pinned into releases (fail-closed unless every declared tool resolves to a pinned
`tool_binding` role). The tenant-scoped `AgentRun` (opaque `public_id` UUID) runs a
guarded decision loop on the verified Sprint 8/9 Celery, tool-proxy, and approval
contracts: step/tool-call/token/deadline/state-size/checkpoint-version caps fail closed,
every planner decision is re-validated against the immutable compiled tool allowlist, a
required tool approval pauses (`waiting_approval`) and auto-resumes on the decision
signal, and output must pass contract + policy. LangGraph (`langgraph==1.2.9`, one
approved pinned dependency) is integrated only as an `AgentPlanner` adapter via
`AGENT_PLANNER`; the default is deterministic, so CI runs no graph code. `POST /v1/invoke`
returns `202` + UUID `run_id`; `GET`/`DELETE /v1/runs/{id}` dual-dispatch workflow/agent.
Trajectory eval assertions, a role-gated console agent-run list + redacted trace, and
`list_agent_runs` / `cancel_agent_run` commands are included. No LangSmith/Cloud/hosted
service or new public endpoint. See [`sprint-10-agent-runtime`](../tasks/sprint-10-agent-runtime/plan.md).

Sprint 11 is implemented and verified: the visual workflow builder. `apps.builder` adds a
tenant-scoped mutable `WorkflowDraft` and an operator JSON API (`/console/api/builder/`) for
draft CRUD, compiler diagnostics, node-schema generation, and publish — all reusing the
console LDAP/session identity and Sprint 1 role/tenant authorization (membership read scope;
`can_author_scenarios` write gate), with CSRF, 401/403 JSON, and audited state changes.
Diagnostics and publish route through the shared `validate_body` / `create_artifact_version`
path (producing an immutable `workflow_definition` artifact — no bypass); the node-schema
endpoint exposes only tool binding *roles* and public config schema, never endpoints or
secrets. A React Flow SPA (`frontend/`, Vite + React + TypeScript, pinned lockfile) is served
same-origin as Django static assets and mounted in a role-gated console page: draft
create/edit/save, node palette + drag/drop canvas, typed edges, schema-generated config
panel, backend diagnostics on the graph, unsaved-change protection, role-driven read-only
mode, and deterministic DSL serialization. The frontend is non-authoritative (every
operation is a backend round-trip). Five approved new production frontend dependencies
(Node/npm, Vite, React, React DOM, `@xyflow/react`) with a Node CI job; no new Python runtime
dependency. The delivered scope is verified; several originally-planned builder enhancements
(optimistic concurrency, autosave, soft-delete, GitOps draft export, artifact preview view,
CSP) are **deferred to Phase 2** because the builder is being repurposed toward AI-assisted
authoring. The single canonical Sprint 11 record is
[`sprint-11-workflow-builder`](../tasks/sprint-11-workflow-builder/plan.md); the earlier
duplicate plan is archived under [`planning/archive`](archive/README.md).

**Phase 2 is in progress:** a governed document plane (per-scenario sources +
real parsers/embeddings + retrieval-time document authorization), a modernized Turkish UI,
AI-assisted authoring alongside the visual builder, personal end-user MCP with identity
delegation, and a **foundational live model runtime** (Workstream 5 — the real chat/embedding
provider; today only a deterministic stub ships). The WS1 document plane and WS5 runtime share
one SSRF-safe egress + a platform-managed profile catalog and are delivered on one interleaved
critical path ([`components/runtime-and-document-plane-sequence.md`](components/runtime-and-document-plane-sequence.md));
the egress architecture is [ADR-0002](../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md).
See [`phase-2-plan.md`](phase-2-plan.md). P1 is verified; every later new dependency/live-egress
destination still needs its explicit milestone approval.

P1 now provides an opt-in real OpenAI-compatible chat provider and platform-managed profile
catalog; deterministic remains the default and no live endpoint/credential was provisioned or
called. Not yet present: a real embedding provider or applied production deployment. Sprint 7
deployment resources are reviewable drafts, not live infrastructure. Consumer auth is bearer-token
only (OIDC/JWT/mTLS later); LDAP is configured but not yet validated against a live
directory. Agent operational follow-ups remain: a global start/resume kill switch, the
checkpoint retention/purge job, and load/soak tests.

## Scope

The target plan proposes a governed multi-tenant AgentHub supporting RAG, workflows, agents, tools, evaluation, releases, and audit in a Django modular monolith.

## Non-goals

This plan does not claim target architecture is deployed or choose unresolved vendors/configuration. Uncontrolled agent playgrounds are excluded by the target design.

## Assumptions

- The target plan is a greenfield design. It does not require or assume a v2 application, release, database, configuration, or migration source.
- Component boundaries below are planning concepts, not deployed services.

## Components

| Component | Status | Dependencies | Detailed plan | Architecture doc | Verification |
| --- | --- | --- | --- | --- | --- |
| Platform foundation/toolchain (Sprint 0) | Verified | Django 5.2, Celery, PostgreSQL/pgvector, Redis, MinIO | [sprint-0-foundation](../tasks/sprint-0-foundation/plan.md) | [v3 target plan §5, §24](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-0-foundation/verification.md) |
| Tenant/identity/catalog + operator console (Sprint 1) | Verified | Foundation, LDAP (prod) | [sprint-1-tenant-identity-catalog](../tasks/sprint-1-tenant-identity-catalog/plan.md) | [v3 target plan §6, §9, §23](../../agenthub-v3-django-plan.md), [ADR-0001](../adr/0001-custom-console-ldap-auth.md) | [verification.md](../tasks/sprint-1-tenant-identity-catalog/verification.md) |
| Artifact registry + release compiler (Sprint 2) | Verified | Sprint 1 | [sprint-2-artifacts-releases](../tasks/sprint-2-artifacts-releases/plan.md) | [v3 target plan §6.3, §8](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-2-artifacts-releases/verification.md) |
| Gateway + ExecutionContext (Sprint 3) | Verified | Sprints 1–2 | [sprint-3-gateway-execution-context](../tasks/sprint-3-gateway-execution-context/plan.md) | [v3 target plan §10, §11](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-3-gateway-execution-context/verification.md) |
| RAG runtime (Sprint 4) | Verified | Sprint 3 | [sprint-4-rag-runtime](../tasks/sprint-4-rag-runtime/plan.md) | [v3 target plan §13](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-4-rag-runtime/verification.md) |
| Ingestion + pgvector index (Sprint 5) | Verified | Sprint 4 | [sprint-5-ingestion-pgvector](../tasks/sprint-5-ingestion-pgvector/plan.md) | [v3 target plan §14](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-5-ingestion-pgvector/verification.md) |
| Eval + gated promotion/rollback (Sprint 6) | Verified | Sprints 4–5 | [sprint-6-eval-promotion-rollback](../tasks/sprint-6-eval-promotion-rollback/plan.md) | [v3 target plan §15, §16](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-6-eval-promotion-rollback/verification.md) |
| MCP + metrics + operations (Sprint 7) | Verified | Sprints 3–6 | [sprint-7-mcp-metrics-operations](../tasks/sprint-7-mcp-metrics-operations/plan.md) | [v3 target plan §12, §21, §24](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-7-mcp-metrics-operations/verification.md) |
| Workflow core (Sprint 8) | Verified | Sprints 6–7 | [sprint-8-workflow-core](../tasks/sprint-8-workflow-core/plan.md) | [v3 target plan §15](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-8-workflow-core/verification.md) |
| Tool registry + approval (Sprint 9) | Verified | Sprint 8 | [sprint-9-tool-registry-approval](../tasks/sprint-9-tool-registry-approval/plan.md) | [v3 target plan §17](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-9-tool-registry-approval/verification.md) |
| Agent runtime (Sprint 10) | Verified | Sprints 8–9 | [sprint-10-agent-runtime](../tasks/sprint-10-agent-runtime/plan.md) | [v3 target plan §18](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-10-agent-runtime/verification.md) |
| Visual workflow builder (Sprint 11) | Verified | Sprints 2, 8 | [sprint-11-workflow-builder](../tasks/sprint-11-workflow-builder/plan.md) | [v3 target plan §25](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-11-workflow-builder/verification.md) |
| Document plane (Phase 2 · WS1) | **P2–P6 + P7.1/P7.2 (parsers) + P8.1–P8.4 (console UI) Verified**; effective consumer grants enforced; P7.3 OCR / P7.4 connectors deferred (egress-gated) | Sprints 5–6, P1 shared egress | [document-plane-plan](components/document-plane-plan.md) + [threat model](components/document-plane-threat-model.md) | [phase-2-plan](phase-2-plan.md) | [P2](../tasks/phase-2-p2-content-plane/verification.md) + [P3](../tasks/phase-2-p3-embeddings/verification.md) + [P4](../tasks/phase-2-p4-acl-rls/verification.md) + [P7](../tasks/phase-2-p7-parsers-ocr-connectors/verification.md) + [P8](../tasks/phase-2-p8-console-ui/verification.md) |
| Live model runtime (Phase 2 · WS5) | **P1 + P5 + P6 Verified** (WS5 runtime scope complete) | Shared egress + `ModelProfile` catalog | [P1](../tasks/phase-2-p1-live-chat/plan.md) + [P5](../tasks/phase-2-p5-agent-workflow-rag/plan.md) + [P6](../tasks/phase-2-p6-agent-system-prompt/plan.md) + [sequence](components/runtime-and-document-plane-sequence.md) | [ADR-0002](../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md) + [ADR-0005](../adr/0005-shared-ssrf-safe-egress-adapter.md) | [P1](../tasks/phase-2-p1-live-chat/verification.md) + [P5](../tasks/phase-2-p5-agent-workflow-rag/verification.md) + [P6](../tasks/phase-2-p6-agent-system-prompt/verification.md) |

## Cross-cutting concerns

Tenant isolation, server-side authorization, release immutability, secret handling, audit, observability, evaluation gates, idempotency, and rollback apply across components. See [`docs/ai`](../ai/engineering-rules.md).

## Dependencies

Implemented dependencies are pinned in `requirements.lock`; environment-specific model
providers, identity integration, storage/queue topology, OpenShift constraints,
ownership, and compliance requirements still require production approval.

## Milestones

1. Approve architecture and durable decisions via ADRs.
2. Establish repository/toolchain and enforceable CI baseline.
3. Implement and verify the first secure vertical slice defined in the target plan.
4. Add ingestion/evaluation/release operations with rollback evidence.
5. Add workflow/tool/agent capabilities only after their threat models and controls are approved.

## Risks

- Target documents may be mistaken for current behavior.
- Identity, tenant, audit retention, provider, and production topology decisions are unresolved.
- No executable verification or enforcement exists yet.

## Open decisions

The operator identity/authorization model is decided (LDAP + custom console, [ADR-0001](../adr/0001-custom-console-ldap-auth.md)); LDAP directory coordinates and group→role mapping are still to be provided. Still open: target-plan authority sign-off, component ownership, data classification/retention, audit storage, provider/network policy, deployment topology, and initial milestone acceptance criteria.

## Completion criteria

Each milestone has an approved plan, threat model where applicable, implemented current-state documentation, verification evidence, operational readiness, residual-risk acceptance, and master-plan update.

## Status legend

Use [the repository status model](../ai/definition-of-done.md#status-model). Architecture-scoped
Phase 2 work is not `Implemented` until code, migrations, tests, and verification evidence land.
