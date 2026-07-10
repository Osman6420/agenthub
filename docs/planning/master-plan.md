# AgentHub Master Plan

## Purpose

Track project-level intent without treating target designs as implemented behavior. Detailed target design remains in [`agenthub-v3-django-plan.md`](../../agenthub-v3-django-plan.md).

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

Not yet present: the public product API/gateway and `ExecutionContext`, RAG runtime,
ingestion, artifact versioning/release compiler, tools, agents, evaluation/release,
and deployment manifests — planned per later sprints in the v3 target plan. LDAP is
configured but not yet validated against a live directory.

## Scope

The target plan proposes a governed multi-tenant AgentHub supporting RAG, workflows, agents, tools, evaluation, releases, and audit in a Django modular monolith.

## Non-goals

This plan does not claim target architecture is deployed or choose unresolved vendors/configuration. Uncontrolled agent playgrounds are excluded by the target design.

## Assumptions

- The v3 target plan supersedes v2 for intended implementation; this requires owner confirmation.
- Component boundaries below are planning concepts, not deployed services.

## Components

| Component | Status | Dependencies | Detailed plan | Architecture doc | Verification |
| --- | --- | --- | --- | --- | --- |
| Platform foundation/toolchain (Sprint 0) | Verified | Django 5.2, Celery, PostgreSQL/pgvector, Redis, MinIO | [sprint-0-foundation](../tasks/sprint-0-foundation/plan.md) | [v3 target plan §5, §24](../../agenthub-v3-django-plan.md) | [verification.md](../tasks/sprint-0-foundation/verification.md) |
| Tenant/identity/catalog + operator console (Sprint 1) | Verified | Foundation, LDAP (prod) | [sprint-1-tenant-identity-catalog](../tasks/sprint-1-tenant-identity-catalog/plan.md) | [v3 target plan §6, §9, §23](../../agenthub-v3-django-plan.md), [ADR-0001](../adr/0001-custom-console-ldap-auth.md) | [verification.md](../tasks/sprint-1-tenant-identity-catalog/verification.md) |
| Gateway + ExecutionContext (Sprint 3) | Planned in target document | Sprint 1 | Not created | [v3 target plan §10, §11](../../agenthub-v3-django-plan.md) | Not available |
| Gateway and identity context | Planned in target document | Control plane, identity provider | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |
| RAG runtime and ingestion | Planned in target document | Model/embedding provider, pgvector, workers | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |
| Evaluation and release | Planned in target document | Runtime, artifact registry | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |
| Workflow, agent, tools, approval | Planned in target document | Gateway, policy, durable state | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |
| Audit and observability | Planned in target document | All runtime/control paths | Not created | [v3 target plan](../../agenthub-v3-django-plan.md) | Not available |

## Cross-cutting concerns

Tenant isolation, server-side authorization, release immutability, secret handling, audit, observability, evaluation gates, idempotency, and rollback apply across components. See [`docs/ai`](../ai/engineering-rules.md).

## Dependencies

All runtime dependencies remain proposed until manifests and deployment decisions exist. Confirm identity provider, model providers, storage, queue/cache, OpenShift constraints, ownership, and compliance requirements before implementation.

## Milestones

1. Approve architecture and durable decisions via ADRs.
2. Establish repository/toolchain and enforceable CI baseline.
3. Implement and verify the first secure vertical slice defined in the v3 plan.
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
