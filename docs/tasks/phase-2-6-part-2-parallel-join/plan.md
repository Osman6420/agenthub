# Task Plan: phase-2-6-part-2-parallel-join

## Task summary

Implement P2.6.2: durable bounded `parallel`, deterministic `join` and bounded `for_each` workflow
execution. The increment extends the accepted transactional transition seam with typed branch and
join records while preserving tenant isolation, immutable release semantics, at-least-once delivery
safety and explicit state/concurrency budgets.

## Background

The current runtime walks one acyclic path and materializes one bounded state on `WorkflowRun`.
ADR-0008 requires all future orchestration changes to pass through a transactional transition
service; ADR-0010 fixes `all`, `threshold` and `fail_fast` joins, branch-owned result namespaces,
explicit ordered merge mappings and compile-time closed branch membership. P2.6.2 implements those
contracts after P2.6.1 supplies canonical typed mappings.

The primary acceptance scenarios are AML/fraud evidence fan-out (S04) and parallel procurement
decisions (the parallel execution portion of S03). Wait/human-task semantics remain P2.6.3-owned.

## Scope

- Add strict compiler contracts for `parallel`, `join` and `for_each` regions.
- Prove at compile time that every region has a closed named branch set, one owned join, valid
  branch paths, deterministic ordering and no ambiguous/nested ownership.
- Support `all`, `threshold` and `fail_fast`; reject impossible thresholds and implicit merge.
- Compile explicit P2.6.1 mappings for branch input/result and ordered join output.
- Add tenant-owned durable branch attempt/result and join state with direct organization/run/release
  lineage, transition-contract version, idempotency identity and safe status metadata.
- Dispatch branches and collection items through PostgreSQL-authoritative intent plus a durable
  after-commit dispatch/outbox or reconciler contract; Redis/Celery remains delivery only.
- Install tenant context and lock the owning run/branch/join record for every transition.
- Enforce compiled maximum branches/items/concurrency, elapsed time, attempts and per-branch/
  aggregate state bytes at compile and runtime.
- Give every `for_each` item a stable server-owned ordinal/key and isolated result namespace.
- Define deterministic threshold/fail-fast closure, late-result handling and explicit ordered merge
  independent of task completion order.
- Propagate cancellation to undispatched/runnable work; prevent late or duplicate results from
  mutating a terminal run or closed join.
- Add bounded reconciliation for committed-but-undispatched, stale-running and join-ready work.
- Add compiler/runtime/eval/trace diagnostics and executable S04 fixtures for happy, partial,
  denial, crash, redelivery, cancellation and budget paths.

## Non-goals

- Human tasks, timers or authenticated external event resume (P2.6.3).
- Generic retry classification, error edges, compensation or `outcome_unknown` reconciliation
  (P2.6.4). P2.6.2 may redispatch only idempotent internal transition/branch work under its fixed
  delivery contract; it does not retry ambiguous external effects.
- Sub-workflow/agent-call composition (P2.6.5).
- Dynamic graph mutation, model-created branches or unbounded/nondeterministic collection iteration.
- Shared mutable branch state or implicit last-writer-wins.
- A new workflow engine, broker, streaming platform or production dependency.
- UI activation before compiler, runtime, recovery, authorization, audit and eval gates pass.
- Resetting any database or deleting durable run evidence.

## Acceptance criteria

1. Compiler rejects unknown keys/modes, duplicate branches, missing/multiple joins, unreachable
   paths, branch escape/re-entry, cycles, ambiguous nesting, impossible thresholds, merge conflicts
   and resource-bound violations with stable diagnostics.
2. Compiled branch membership, order, join mode/threshold, mappings and budgets are immutable and
   checksum-bound to the release; runtime/model/task input cannot add or reorder work.
3. Every branch/item has durable organization/run/release/checksum lineage, stable identity and
   idempotent transition keys; duplicate Celery delivery cannot repeat a committed transition.
4. Branches receive only their mapped immutable input plus server-owned execution context and write
   only their owned result namespace.
5. `all`, `threshold` and `fail_fast` close deterministically under concurrent completion. Join
   output order follows compiled branch/item order, never completion order.
6. Collection item identity/order remains stable across crash, redispatch and worker replacement;
   item count and concurrency never exceed compiled hard limits.
7. Cancellation stops new dispatch and marks pending/runnable work safely. Late results may create
   bounded evidence but cannot reopen a join, mutate terminal state or resurrect the run.
8. Worker loss, crash between commit/dispatch, broker redelivery and stale-running work converge
   through bounded reconciliation without losing intent or duplicating completed transitions.
9. State-size, elapsed-time, branch/item, concurrency and attempt budget exhaustion terminates with
   stable safe outcomes and no partial join merge.
10. Tenant context/RLS and object authorization deny missing scope, foreign-run/branch references
    and cross-tenant task payload substitution on PostgreSQL non-owner coverage.
11. Trace/eval/operator data shows safe branch/join status and reason codes without branch payloads,
    secrets, document content or high-cardinality metric labels.
12. S04 executes independent evidence work concurrently and synthesizes only after its compiled
    join policy; happy, partial threshold, fail-fast, duplicate/late, cancellation and recovery paths
    have recorded evidence.
13. Applicable repository formatter, lint, type, Django, migration, SQLite, PostgreSQL and Celery
    recovery checks pass, followed by staff-engineering, application-security and SRE diff review.

## Affected components

- `apps/workflows/compiler.py`: region ownership, topology and budget compilation
- workflow transition service/runtime/tasks: branch commands, dispatch, join closure and recovery
- `apps/workflows/models.py` plus additive migrations: typed branch/join durable records
- tenant RLS inventory/policies for every new tenant-owned table
- evaluations: branch/join assertions and deterministic reference execution
- builder/Studio node catalog and diagnostics; console trace/status views after activation gates
- observability events/metrics/traces and operations/reconciliation commands/tasks
- P2.6 scenario fixtures, workflow authoring guide and current-behavior documentation

## Interfaces affected

The unreleased canonical `agenthub/v1` graph gains `parallel`, `join` and `for_each` nodes plus
branch edge discriminators described by the P2.6.0 target contract. Compiled graph and resumable
record contract versions change. Existing consumer invoke/status/cancel routes remain compatible;
safe branch/join progress may be added to authorized status/trace responses without exposing state.

Expected stable diagnostics include `WORKFLOW_PARALLEL_REGION_INVALID`,
`WORKFLOW_JOIN_POLICY_INVALID`, `WORKFLOW_MAPPING_CONFLICT` and `WORKFLOW_BUDGET_EXCEEDED`.

## Data impact

Add tenant-owned branch attempt/result and join records with direct organization lineage, immutable
run/release/checksum association, bounded status/timing/counter metadata and separately classified
bounded result state. Indexes and uniqueness constraints must support idempotent claim/transition
without unbounded scans. Define retention/purge behavior while preserving required audit/run lineage.

Branch payloads can contain confidential tenant data. Persist only schema-approved mapped values;
never copy server-owned authorization context, credentials or raw unredacted provider errors.

## Security impact

Parallelism amplifies resource consumption and attack surface. All fan-out is compile-time closed or
bounded by a compiled collection maximum, with runtime enforcement. Branch tasks are untrusted
delivery messages and cannot supply organization, capability, release, branch ownership or join
policy. Explicit branch-owned namespaces and deterministic merge prevent cross-branch mass
assignment and race-based state corruption. See [threat-model.md](threat-model.md).

## Authorization impact

No authority is delegated between branches. Each node retains its existing tool, retrieval, custom
node and release authorization boundary using server-owned context. Branch/task IDs are locators,
not proof; the runtime resolves them under organization/run/release scope. Any public or operator
recovery action requires a separate explicit role/action policy and audit before implementation.

## Observability impact

Add stable events for region open, branch/item claim/start/finish/cancel/late-result, join ready/
close/fail and reconciliation outcome. Metrics use bounded labels such as node type, join mode,
status and safe reason code; tenant/run/branch/item IDs remain redacted log/trace/audit fields. Do
not log mapped state. Required audit transitions commit atomically/fail closed; optional telemetry
failure cannot change scheduling or join decisions.

## Migration impact

Forward-only additive migrations are expected for branch/join and possibly durable dispatch intent.
Every tenant-owned table requires direct organization lineage, FORCE RLS where applicable,
non-owner verification, uniqueness/idempotency constraints and bounded indexes. Exact migration
numbers are allocated by the Phase 2.6 integration owner after P2.6.1 merges. No destructive
migration or implicit reset is authorized.

## Dependencies

- Merged and verified P2.6.0, accepted ADR-0008 and ADR-0010
- Merged and verified P2.6.1 canonical mapping/runtime state seam
- Integration-owner allocation for shared transition interface and migrations
- Existing PostgreSQL tenant-context/RLS, Celery runtime queue and cancellation behavior
- Owner decision on durable dispatch implementation and exact resource/reconciliation thresholds

## Implementation steps

1. Reinspect the merged P2.6.1 compiler/runtime transition interface, live migration graph, current
   run/task/cancel behavior and applicable P2.6.0 fixtures; update this plan if reality differs.
2. Fix numeric limits, branch/item identity, nested-region ownership, join terminal rules, retention
   and durable dispatch/reconciliation design. Record a new ADR only if these extend or change
   ADR-0008/0010 materially.
3. Write executable compiler contract tests for region topology, deterministic ordering, mappings,
   nesting and all budget/invalid cases.
4. Add typed branch/join models, constraints, indexes, tenant lineage and RLS migration/provisioning
   tests through the allocated additive migration.
5. Extend the single transition service with typed idempotent open/claim/start/finish/cancel/
   join-close commands; prohibit direct status mutation in task handlers.
6. Implement PostgreSQL-authoritative dispatch intent and bounded reconciler, including crash
   windows before/after broker publication and stale claim recovery.
7. Implement branch execution with P2.6.1 input/output mapping and branch-owned result state; adapt
   existing nodes without weakening their authorization/proxy/ACL boundaries.
8. Implement deterministic `all`, `threshold` and `fail_fast` join evaluation and ordered atomic
   merge, including late results and terminal guards.
9. Implement bounded `for_each` expansion with stable ordinal/key, concurrency admission and
   aggregate budgets; never materialize or dispatch beyond the maximum.
10. Integrate cancellation, capability gates, safe trace/eval/diagnostic output and S04 executable
    fixtures; expose Studio palette only after backend verification.
11. Run focused and full SQLite/PostgreSQL/Celery recovery gates and record commands/results in
    `verification.md`.
12. Review final diff for concurrency correctness, lock ordering/contention, authorization/RLS,
    denial paths, broker/database failure windows, cardinality, rollback and operational recovery.

## Test plan

- Compiler topology/property tests: branch ownership, join cardinality, nesting, cycles, thresholds,
  routes, mappings, deterministic order and graph/fan-out/state budgets.
- Model/migration tests: direct organization lineage, uniqueness/idempotency, indexes, migration
  drift, FORCE RLS provisioning and non-owner cross-tenant denial.
- Transition concurrency tests: simultaneous branch completion, duplicate command/idempotency key,
  threshold races, fail-fast races, join-close contention and lock-order safety.
- Delivery/recovery tests: crash before/after dispatch commit, broker publish failure, redelivery,
  stale claim, worker loss, reconciler duplication and deploy/version mismatch.
- Runtime tests for `all`, `threshold`, `fail_fast` and `for_each`, including empty/min/max arrays,
  stable ordering, partial failure, timeout, cancellation and late result.
- Security tests for forged organization/run/branch IDs, foreign tenant state, branch namespace
  escape, protected-key write, capability smuggling and oversized/deep output.
- Existing tool approval, retrieval ACL, generate and custom-node tests executed inside branches to
  prove unchanged boundaries; ambiguous side effects are never blindly redispatched.
- Observability/audit tests for event completeness, redaction, required-audit failure and bounded
  metric labels.
- Executable S04 scenario/eval tests plus relevant S01/S03 parallel-path coverage.
- Repository gates: formatting, lint, typing, Django checks, migration drift, focused/full SQLite,
  PostgreSQL non-owner/RLS/concurrency and real Celery/Redis recovery smoke as applicable.

## Rollout plan

- Keep `parallel`, `join` and `for_each` disabled by default and reject them at release activation
  until compiler/runtime/migration/recovery evidence is complete.
- Merge only after P2.6.1 into the designated integration branch; apply additive migrations before
  starting matching workers.
- Deploy matching web/runtime/reconciler code, verify contract/queue compatibility and initially
  enable only deterministic non-production reference scenarios with conservative hard caps.
- Monitor queue depth, branch age, join age, reconciliation rate, state bytes, lock contention and
  failures before per-organization canary enablement.
- Do not enable workflows containing waits/compensation/child calls until their owning parts pass.

## Rollback plan

- Disable new parallel starts globally/per organization and stop new dispatch; cancellation remains
  available through the matching transition contract.
- Keep additive tables and durable evidence. Do not downgrade or reinterpret in-flight records with
  old code; use matching workers for drain/cancel or explicit operator reconciliation.
- Roll back code only after no incompatible active records remain, or forward-fix the matching
  contract. Never delete branch/join history as rollback.
- Any disposable local/test repopulation remains separately confirmed and target-verified.

## Risks

- Concurrent completion can double-close a join or produce completion-order-dependent output.
- Incorrect lock ordering can deadlock or serialize all tenant work around `WorkflowRun`.
- Fan-out can amplify Celery backlog, database rows, state bytes, external calls and cost.
- A crash between database commit and broker dispatch can strand work; dispatch-before-commit can
  create ghost/duplicate work.
- Threshold/fail-fast early closure can mishandle late successful/error results or cancellation.
- `for_each` item identity derived from mutable content can change across retry and duplicate work.
- Branch tasks may accidentally trust payload tenant/release/capability data or omit tenant scope.
- External side effects inside branches remain subject to `outcome_unknown`; this increment cannot
  make them safe by generic retry.
- Retention/reconciliation scans can become unbounded or leak confidential branch payloads.

## Open questions

1. Which durable dispatch design extends the shared transition service: a workflow-specific outbox
   table or a reusable orchestration dispatch intent? It must not conflict with P2.6.10 ownership.
2. What are the initial hard maxima for branches, collection items, concurrency, nested region depth,
   per-branch bytes, aggregate bytes, attempts and elapsed time?
3. Is nested parallel/`for_each` supported initially, rejected, or allowed only to a small compiled
   depth with cumulative concurrency admission?
4. For `fail_fast`, which closed outcome classes trigger early closure before P2.6.4 introduces the
   generic failure taxonomy?
5. After threshold/fail-fast closure, are undispatched/running non-required branches cancelled,
   allowed to finish as evidence, or policy-selectable? They must never alter the closed result.
6. What retention/purge window applies to branch result payloads versus safe transition evidence?
7. Which operator reconciliation actions are necessary in P2.6.2, and do any require separate
   authorization/public-interface approval?

## Implementation decisions (2026-07-17)

- Use workflow-specific `WorkflowBranch` and `WorkflowJoin` durable records. A branch row is also
  the PostgreSQL-authoritative dispatch intent; `pending` means committed but not yet claimed and
  the bounded reconciler republishes only those server-owned row identifiers. This avoids a shared
  outbox contract owned by another lane.
- Hard maxima are 16 static branches, 100 `for_each` items, concurrency 16, duration 300 seconds,
  three delivery attempts, 256 KiB per branch result and 1 MiB aggregate result state. Authored
  values may reduce but never raise these limits; runtime transitions enforce them again.
- Nested `parallel`/`for_each` regions are rejected in this first increment. Region ownership is
  therefore single-level and statically provable without redefining the shared state machine.
- `fail_fast` closes on the first failed, timed-out or cancelled branch. `threshold` closes after
  the compiled success count is reached or fails when the remaining branch count makes it
  impossible. `all` requires every branch to succeed.
- Early closure marks pending/running non-required rows cancelled. A late/duplicate completion is a
  stable no-op (`late`/`duplicate`) and cannot change the join or terminal run.
- Branch result payload follows the owning run retention in this increment. No purge interface is
  added; changing retention remains an integration/operations decision.
- Reconciliation is an internal bounded service/task only. No new operator/public recovery action
  or authorization surface is introduced.

## Status

In progress. P2.6.1 is present on base commit `c4d47b1`; dispatch, numeric budget, nesting and
early-join lifecycle decisions are closed above before implementation.

## Completion criteria

This task reaches `Implemented` when compiler, durable models/migrations, transition commands,
dispatch/reconciliation, runtime, cancellation, fixtures, eval/diagnostics and documentation form a
small complete disabled-by-default increment. It reaches `Verified` only with recorded SQLite,
PostgreSQL non-owner/RLS/concurrency and Celery crash/redelivery evidence plus security/SRE review.
It reaches `Completed` after current-behavior docs and Phase 2.6/master-plan evidence are updated and
the integration owner accepts the P2.6.2 seam for P2.6.4/P2.6.11 consumers.
