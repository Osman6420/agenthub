# Architecture Decision Records

Create an immutable, sequentially named ADR (`NNNN-short-title.md`) for durable decisions such as authentication provider, authorization/tenant model, audit storage, database/broker, public API style, major dependency/framework, retention/encryption, deployment topology, or significant build-versus-buy choice. Do not use ADRs for small implementation details or temporary task choices.

Statuses are Proposed, Accepted, Superseded, or Rejected. An accepted ADR is changed only for factual corrections; a new ADR supersedes it and links both directions. Use [`template.md`](template.md), obtain relevant security/operations/data review, and link the ADR from affected architecture and plans.

## Current decisions

| ADR | Status | Scope / relationship |
| --- | --- | --- |
| [0001](0001-custom-console-ldap-auth.md) | Accepted | Human operator console and LDAP/AD authentication. |
| [0002](0002-model-embedding-egress-profile-catalog-stdlib-adapter.md) | Accepted | Model/embedding destination governance, platform profile catalog, and SDK deferral. |
| [0003](0003-vector-storage-blue-green-per-index-version.md) | Accepted | WS1 M0 vector-store decision; composes with ADR-0004. |
| [0004](0004-tenant-isolation-postgres-rls-connection-context.md) | Accepted | WS1 M0 PostgreSQL RLS and transaction-local tenant context. |
| [0005](0005-shared-ssrf-safe-egress-adapter.md) | Accepted | WS1/WS5 M0 implementation contract detailing ADR-0002's shared egress mechanism; does not supersede ADR-0002. |
| [0006](0006-confluence-private-corporate-egress.md) | Accepted | P7.4 connector-specific private corporate egress; preserves ADR-0005 public-only defaults. |
| [0007](0007-governed-rest-contract-incremental-refresh.md) | Accepted | P7.4b closed REST mapping, periodic incremental refresh/vector reuse, and gated optional promotion. |
| [0008](0008-durable-workflow-transition-state-machine.md) | Accepted | P2.6 transactional durable workflow transitions, typed child records and recovery invariants. |
| [0009](0009-child-run-capability-attenuation.md) | Accepted | P2.6 pinned child workflow/agent calls with non-delegating capability attenuation. |
| [0010](0010-workflow-dataflow-join-wait-and-human-task-contract.md) | Accepted | Restricted dataflow paths, deterministic joins, authenticated one-time event resume and typed human tasks. |
| [0011](0011-durable-ingestion-build-jobs-and-worker-readiness.md) | Accepted | PostgreSQL-authoritative staged-index jobs, dispatch outbox, reconciliation and compatible-worker evidence. |
