# AgentHub Master Plan

## Purpose

Track project-level intent without treating target designs as implemented behavior. Detailed target design remains in [`agenthub-v3-django-plan.md`](../../agenthub-v3-django-plan.md); `v3` in that filename means document revision 3, not a product generation.

## Current state

As of 2026-07-10, Sprint 0 (foundation) and Sprint 1 (tenant/identity/catalog) are
implemented and verified.

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

Not yet present: a real LLM/embedding provider, workflows, tools, agents, or applied
production deployment. Sprint 7 deployment resources are reviewable drafts, not live
infrastructure. Model/embedding providers are deterministic defaults (no real LLM call
yet). Consumer auth is bearer-token only (OIDC/JWT/mTLS later); LDAP is configured but
not yet validated against a live directory.

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
| Gateway and identity context | Planned in target document | Control plane, identity provider | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |
| RAG runtime and ingestion | Planned in target document | Model/embedding provider, pgvector, workers | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |
| Evaluation and release | Planned in target document | Runtime, artifact registry | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |
| Workflow, agent, tools, approval | Planned in target document | Gateway, policy, durable state | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |
| Audit and observability | Planned in target document | All runtime/control paths | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |

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

Use [the repository status model](../ai/definition-of-done.md#status-model). “Planned in target document” is not `Implemented`.
