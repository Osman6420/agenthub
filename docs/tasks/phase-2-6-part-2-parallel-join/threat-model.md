# Threat Model: phase-2-6-part-2-parallel-join

## Assets

- Tenant workflow input, branch/item state, join output and final run result
- Immutable compiled graph, release checksum, branch membership/order and resource budgets
- Server-owned tenant, actor, capability, approval and execution context
- PostgreSQL orchestration authority and immutable audit/transition evidence
- Worker, broker and database availability

## Actors

- Scenario authors and organization/platform operators
- Authorized consumers and malicious/compromised tenant users
- Runtime/reconciliation workers and broker deliveries
- Untrusted tool, retrieval, model and custom-node outputs
- External systems invoked by existing governed nodes

## Entry points

- Authored/imported `parallel`, `join`, `for_each`, branch edges and merge mappings
- Consumer workflow input, especially collection values
- Celery branch/item tasks and reconciliation commands
- Concurrent branch results, cancellation and late/stale delivery
- Authorized status/trace/eval/operator surfaces

## Trust boundaries

- Author/client JSON to canonical compiler
- Compiled release to transition commands and branch dispatch
- PostgreSQL committed intent to Redis/Celery delivery
- Broker payload to tenant-scoped locked durable records
- Shared run input to isolated branch-local state
- Untrusted branch output to P2.6.1 schema/mapping validation and join merge
- Concurrent/late result to a closed or terminal join/run

## Data classifications

Compiled topology and safe node schemas are internal tenant data. Run input, retrieval content,
tool/model/custom output and branch results may be confidential/restricted. Credentials, secret
values, authorization context and raw provider errors are restricted and cannot enter branch
payloads, diagnostics, logs, metrics or traces.

## Authentication

Existing session/LDAP and consumer bearer authentication remains unchanged. Broker possession or a
branch/run identifier does not authenticate an actor or authorize a transition. Internal tasks
resolve server-owned lineage from PostgreSQL and fail closed without tenant scope.

## Authorization

Branches receive no delegated ambient authority. Existing node authorization is re-applied using
the run's server-owned context. Compiled membership and release pins, not task/model/client data,
determine executable work. Operator recovery/cancellation requires existing or explicitly approved
role/action authorization and auditable reason capture.

## Tenant isolation

Every branch/join/dispatch record carries direct organization lineage and uses FORCE RLS where
applicable. Worker transactions install `app.tenant_scope` before reads/locks. Parent/run/branch IDs
are resolved together under organization and release checksum; foreign task payload substitution
fails closed.

## External systems

PostgreSQL is orchestration authority; Redis/Celery is untrusted at-least-once delivery. Existing
tools/MCP/model/retrieval/custom-node adapters remain separate trust boundaries. P2.6.2 introduces
no live endpoint or dependency and never treats an ambiguous external result as safely retryable.

## Abuse cases

- Author unbounded fan-out or nested regions to exhaust workers, database, broker, provider quota or
  tenant budget.
- Forge branch membership/order/threshold in a task or model output.
- Race two completions to close/merge a join twice or produce completion-order-dependent output.
- Write another branch/shared/protected namespace and exploit implicit last-writer-wins.
- Substitute organization/run/release/branch IDs in broker payloads for cross-tenant execution.
- Use huge/deep collection items or expanding outputs for memory/state/broker denial of service.
- Replay a completed task, deliver a stale result after cancellation or resurrect a terminal run.
- Cause a crash in the commit/dispatch window to lose work or create ghost/duplicate work.
- Trigger automatic redispatch after an ambiguous external side effect.
- Infer confidential branch payloads or topology through trace/error/log/metric output.
- Abuse reconciliation with unbounded scans or crafted stale records.

## Failure cases

- Broker unavailable after durable intent commit
- Worker loss before claim, during node work or after result/transition commit
- Concurrent threshold/fail-fast completion and cancellation
- Partial branch failure, timeout, state-budget exhaustion or malformed output
- Stale/mismatched compiler or transition-contract worker
- Required audit commit failure
- Database deadlock/contention or reconciler overlap
- Late result after join closure or terminal run

## Logging and audit risks

Branch result state can contain confidential documents, personal data and provider output. IDs and
collection keys can create high-cardinality metrics or expose business identifiers. Logging broker
payloads/pre-post state or raw exceptions can leak data. Missing audit during cancellation, early
closure or recovery can obscure who/what changed the run.

## Mitigations

- Compile-time closed topology, deterministic order and explicit merge mappings
- Hard cumulative branch/item/concurrency/depth/time/attempt/state limits at compile and transition
- Typed durable records with direct organization/release/checksum/version lineage and unique
  idempotency constraints
- One transactional transition service, row locking, expected revision/state and terminal guards
- PostgreSQL-authoritative dispatch intent plus bounded idempotent reconciliation
- Tenant scope/FORCE RLS and non-owner cross-tenant verification
- Branch-local input/output namespaces and P2.6.1 protected-key/schema/size enforcement
- Stable server-owned item ordinals/keys independent of mutable content/completion order
- Cancellation admission guard; late results retained only as bounded safe evidence
- No generic retry of side effects or `outcome_unknown`
- Redacted stable events, bounded metrics, no state values or business IDs in labels
- Matching compiler/worker contract checks and disabled-by-default rollout

## Residual risks

PostgreSQL lock contention and queue amplification require load/soak evidence beyond correctness
tests. Existing governed nodes may call external systems whose outcome is ambiguous on worker loss;
P2.6.4 reconciliation remains required. Legitimately authorized parallel calls can amplify tenant
cost even within caps, so conservative defaults and operational alerts remain necessary. A shared
outbox design can create coupling with P2.6.10 if ownership is not settled before implementation.

## Required security tests

- Invalid topology, branch injection, impossible threshold and ambiguous merge rejection
- Maximum/over-limit branches, items, nesting, concurrency, duration, attempts and state bytes
- Protected/shared namespace write and cross-branch overwrite denial
- Authentication failure, action authorization denial and cross-tenant run/branch/task substitution
- FORCE RLS/non-owner access for every new tenant-owned table
- Duplicate/concurrent completion and exactly-once join-close transition
- Crash-before/after-dispatch, broker failure, stale claim and reconciler duplication
- Cancellation/terminal guard with undispatched, running and late-result branches
- Stable `for_each` identity/order across redelivery and worker replacement
- Tool/retrieval/custom authorization non-bypass inside branches
- Ambiguous side-effect result is not automatically retried
- Required-audit failure blocks applicable transition
- Confidential state, provider error and identifier redaction; bounded metric labels
- Compiler/transition version mismatch and stale checkpoint fail closed
