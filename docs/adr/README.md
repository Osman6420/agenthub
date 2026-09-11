# Architecture Decision Records

Create an immutable, sequentially named ADR (`NNNN-short-title.md`) for durable decisions such as authentication provider, authorization/tenant model, audit storage, database/broker, public API style, major dependency/framework, retention/encryption, deployment topology, or significant build-versus-buy choice. Do not use ADRs for small implementation details or temporary task choices.

Statuses are Proposed, Accepted, Superseded, or Rejected. An accepted ADR is changed only for factual corrections; a new ADR supersedes it and links both directions. Use [`template.md`](template.md), obtain relevant security/operations/data review, and link the ADR from affected architecture and plans.

## Current decisions

The additive execution snapshot and independently durable data-selection decision is
[ADR-0021](0021-scenario-revision-and-durable-data-selection.md); activation remains gated
by the combined task's verification record.

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
| [0011](0011-reviewed-python-node-isolation-and-lifecycle.md) | Proposed | P2.6.8 minimum isolated runner, exact-checksum review/activation, source governance and safe catalog contract. |
| [0012](0012-durable-ingestion-build-jobs-and-worker-readiness.md) | Accepted | PostgreSQL-authoritative staged-index jobs, dispatch outbox, reconciliation and compatible-worker evidence. |
| [0013](0013-scoped-operator-capabilities-and-superadmin-recovery.md) | Superseded | Staged closed operator capabilities and delegated object scopes; superseded by ADR-0015. |
| [0014](0014-unified-workflow-engine-cutover.md) | Accepted | One executable workflow artifact/runtime, compiler-owned execution modes, breaking cutover and empty-database rollback. |
| [0015](0015-responsibility-based-operator-authorization.md) | Accepted | Roleless membership, typed scope responsibilities, exact scenario approval and typed human/consumer identity. |
| [0016](0016-explicit-scenario-and-atomic-served-index-lifecycle.md) | Accepted | Separate governed scenario callability plus one atomic document-set/index serving pointer. |
| [0017](0017-bounded-halfvec-response-truncation.md) | Accepted | Refines ADR-0003 for explicit `halfvec(4000)` provider-response truncation. |
| [0018](0018-portable-openshift-build-and-database-initialization.md) | Accepted | Portable mirror/Binary builds plus deadlock-free managed and bundled database initialization. |
| [0019](0019-explicit-combined-scenario-manager.md) | Accepted | Additive exact scenario manager; composes with ADR-0015 without broadening old assignments. |
| [0020](0020-shared-generation-vector-storage.md) | Accepted; rollout in progress | Fixed shared geometry indexes, immutable generation lineage and owner-only additive backfill. |
| [0021](0021-scenario-revision-and-durable-data-selection.md) | Accepted; rollout in progress | Immutable execution snapshots and durable retrieval generation selection. |
| [0022](0022-shared-connection-and-ingestion-job-authority.md) | Accepted; rollout in progress | Exact Connection identities and one ingestion job/outbox authority with protocol compatibility projections. |
