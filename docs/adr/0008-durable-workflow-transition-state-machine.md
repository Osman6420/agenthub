# ADR 0008: Durable Workflow Transition State Machine

- **Status:** Accepted
- **Date:** 2026-07-16

## Context

The current workflow runtime executes one acyclic path, stores a materialized redacted state on
`WorkflowRun`, appends sequenced events and uses `awaiting_node` only for tool approval. Phase 2.6
adds parallel branches, joins, generic waits, retry, compensation and crash recovery. Encoding these
as ad-hoc status changes in individual Celery tasks would make redelivery, concurrent resume and
ambiguous external outcomes unsafe.

The product is unreleased. The source workflow grammar may evolve in place as `agenthub/v1`, but an
old compiled graph or checkpoint must never be interpreted under incompatible transition semantics.

## Decision drivers

- Deterministic transitions under at-least-once task delivery
- Durable recovery across worker/process/deploy failure
- Tenant isolation and server-owned authorization lineage
- Explicit resource budgets and terminal-state protection
- Reviewable audit evidence without persisting secrets or raw sensitive state
- One shared seam that parallel Phase 2.6 branches can extend safely

## Considered options

1. Continue mutating `WorkflowRun` directly in every node/task handler.
2. Treat an append-only event stream as the sole source of truth and rebuild all state by replay.
3. Use a transactional transition service with materialized run state plus immutable transition
   evidence and typed durable child records.
4. Introduce a new external workflow orchestration platform in Phase 2.6.

## Decision

Choose option 3.

- A single workflow transition service owns legal status changes. Celery tasks and HTTP/console
  handlers submit typed commands; they do not independently mutate orchestration status.
- Commands bind organization, run, immutable workflow/release checksum, expected state/revision and
  an idempotency key. The service installs tenant context, locks the owning run/typed child record,
  validates the transition and commits materialized state plus safe event evidence atomically.
- At-least-once delivery is expected. A repeated command returns the committed result or a stable
  stale/terminal outcome; it cannot repeat a transition or resurrect a terminal run.
- `WorkflowRun` remains the bounded materialized run summary. Typed records hold branch attempts and
  results, join state, waits/correlations, node attempts, compensation entries and parent/child
  links. Generic waits do not overload the current `awaiting_node` string.
- Events are immutable audit/diagnostic evidence, not an authorization source and not the sole
  replay source. Sensitive state remains separately bounded/redacted according to its data class.
- Security-sensitive transitions (approval/decision, resume, activation/disable, release promotion
  and operator recovery) commit their required business audit evidence in the same transaction or
  fail closed. Optional logs, metrics and traces fail open and never become transition authority.
- Every resumable record carries a transition-contract/compiler version. Incompatible checkpoints
  fail closed into explicit operator reconciliation; deploys never reinterpret them.
- Join membership, merge order, retry eligibility, compensation order and budgets are fixed in the
  compiled release. Runtime/model output cannot add branches, actions or compensation steps.
- Retry is permitted only for classified transient failures on explicitly idempotent operations.
  `outcome_unknown` cannot be blindly retried or compensated without a verified reconciliation
  contract.
- Cancellation and terminal transitions block new dispatch. Late results may be retained as safe
  evidence but cannot mutate terminal materialized state.
- PostgreSQL is the authority for durable orchestration state. Redis/Celery is delivery, never the
  source of truth. Dispatch-after-commit uses a durable dispatch/outbox or reconciler pattern chosen
  in the owning implementation task.
- Bounds for graph size, fan-out, depth, state bytes, attempts, elapsed time and external calls are
  compiled and enforced again on every transition.

Option 4 is deferred. The Django/PostgreSQL/Celery architecture remains the Phase 2.6 deployment
boundary; a future extraction may preserve these contracts.

## Security consequences

All commands and external results are untrusted. Protected tenant, actor, release, capability and
authorization fields are server-owned and cannot be written through workflow mappings. Resume
correlations require authenticated, opaque, replay-safe designs. Safe events contain identifiers,
checksums and reason codes, never secrets, raw credentials, Python source, document contents or
hidden model reasoning.

## Operational consequences

Operators gain explicit stuck-wait, stale-attempt, retry, compensation and reconciliation states.
Reconcilers run in bounded batches and use the same transition service. Queue availability can
delay work without losing PostgreSQL-authoritative intent.

## Data and privacy consequences

New tenant-owned records require direct organization lineage, FORCE RLS where applicable, retention
and purge rules. State/event schemas must separate operational metadata from confidential payloads.

## Positive consequences

- One concurrency/idempotency model across all workflow primitives
- Crash and redelivery behavior becomes testable at a single seam
- Parallel branches can extend typed records without redesigning status mutation
- Materialized reads remain efficient without relying on full event replay

## Negative consequences

- Additional tables, transitions, locking and reconciliation complexity
- PostgreSQL contention must be measured for highly parallel runs
- Every new primitive must integrate with the transition command contract

## Migration impact

Later tasks add typed records and transition version/checksum fields through forward-only
migrations. Because existing data is dummy and unreleased, an explicitly approved non-production
reset/repopulation may replace incompatible workflows and runs. No reset is authorized by this ADR.

## Rollback considerations

Capability gates stop new starts. In-flight records are not reinterpreted by old code. Rollback uses
matching code plus separately approved non-production repopulation or a forward fix; durable
evidence is not destructively rolled back.

## References

- [Phase 2.6 plan](../planning/phase-2-6-plan.md)
- [P2.6.0 plan](../tasks/phase-2-6-contract-and-scenario-foundation/plan.md)
- [Current contract inventory](../tasks/phase-2-6-contract-and-scenario-foundation/current-contract-inventory.md)
- [ADR 0004](0004-tenant-isolation-postgres-rls-connection-context.md)
- [ADR 0010](0010-workflow-dataflow-join-wait-and-human-task-contract.md)
