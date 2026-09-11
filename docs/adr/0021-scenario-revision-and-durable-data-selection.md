# Scenario execution revision and durable data selection

Date: 2026-09-10

Status: Accepted (additive implementation; default activation and rollout remain open)

## Context

A release's configuration and the document data it serves have different lifecycles.
Resolving mutable catalog bodies during execution can redefine an admitted run, while
pinning document versions forever makes routine data refresh require a new configuration
release. Selecting the newest data on every retry also changes the evidence of one step.

The approved [combined task](../tasks/Agent_Hub_MD/plan.md) separates these lifecycles while
preserving legacy execution, live authorization, audit and recovery controls.

## Decision

`ScenarioRevision` is an immutable, checksummed configuration snapshot captured in the same
transaction as a new-contract release and compiled workflow. It contains resolved artifact
bodies and provenance, the compiled graph, runtime/compiler contracts, exact tenant and
scenario scope, and the data-selection policy. Reusable artifacts remain authoring objects.
The snapshot does not contain retrieved document content or resolved credentials.

New-contract Runs reference the exact revision with a protected foreign key. Snapshot
validation precedes cache use. Missing or inconsistent revisions fail closed; there is no
fallback to a mutable catalog or a newer release. New graphs use compiler contract v7;
legacy graphs retain v6. Workers must understand the admitted contract before claiming it.
Waits, child execution, parallel branches and embedded agents retain their Run's root pins.

`legacy_pinned` keeps existing document-set-version semantics. Opt-in `active_generation`
snapshots instead identify up to 200 logical document sets. Before a retrieval step performs
I/O, the owner commits a checkpoint and then an independently durable selection receipt.
`RunRetrievalSelection` and `RunRetrievalGeneration` record the exact selected set versions
and index generations, including a valid empty choice. Criteria are checksummed; the receipt
does not store the raw query. A Run admits at most 2048 receipts.

The receipt key includes the node, branch identity when applicable, and embedded-agent step
when applicable. A retry of that key retains its choice; changed criteria are rejected.
A subsequent step can select refreshed active data. Agent decisions and accumulated execution
time survive these boundaries so selection cannot cause replanning or reset the node budget.

Receipts are evidence, never authorization. Every read rechecks current tenant, consumer,
scenario and document-set access, shared consent where applicable, and document tombstones.
An exact selected generation may be superseded after selection and still be read if those
checks allow it. Revocation or deletion cannot be undone by replaying a receipt.

PostgreSQL enforces immutable receipts, exact lineage, complete generation counts, FORCE RLS
and protection of referenced generations. Promotion and selection use compatible ordered
locks. Legacy/shared storage layouts remain explicit; a verified backfill can preserve the
same generation identity. Referenced generation cleanup fails before data removal.

## Transaction and operational boundaries

Runtime grants keep WorkflowVersion at SELECT/INSERT, without UPDATE. Capture reads
the immutable workflow without an application row lock; background claim locks only
its Run rather than every joined table. The database integrity trigger retains its
SHARE lock against legacy workflow writers. Migration 0008 makes that trigger alone
SECURITY DEFINER, with a pg_catalog-only search path and no PUBLIC EXECUTE grant.
Its static SQL qualifies application tables, validates exact source/tenant/snapshot
lineage, and writes no additional rows. FORCE RLS still checks the revision INSERT.
An earlier INSERT trigger runs as the caller and checks tenant scope plus the
workflow's organization/scenario before the definer trigger can lock any row.
This avoids both cross-scope elevated locks and granting general workflow mutation
rights to web or worker roles.
Reversal restores invoker execution and the previous function settings without
deleting data; operational rollout must review the function owner and grants.

Gateway admission already commits before execution. Evaluation admission, candidate
preparation, execution, case evidence and final audit now use separate transactions.
The four operator entry points for asking, evaluating and preparing a candidate own short
membership-derived transactions instead of inheriting one request-wide transaction.
Tenant context is always transaction-local and reestablished for every segment.
Authentication, CSRF, exact action authorization and publication gates remain applicable.
Evaluation failure cannot make a candidate active. A prepared candidate can remain available
for diagnosis when its later evaluation fails.

Question evaluation workers and resumable release evaluations retain one session advisory
lock across case commits, using separate question/release tenant/run namespaces.
This follows the existing direct-PostgreSQL ingestion lock
topology and requires connection affinity. A replaced connection is rejected as a lost
owner; process/connection loss releases the lock. Persisted evidence makes redelivery skip
completed cases. Cancellation is checked between cases and at finalization. This is not a
new generic job/lease system; the unified ingestion job work remains in the combined task.

`ScenarioPublication` records an immutable operator/scenario intent, the reviewed and
prepared configuration checksums, exact candidate and evaluation, and the previous live
release. It adds no independent job or evaluation status authority. Preparation and
admission commit together; evaluation executes outside the operator transaction; final
promotion, scenario activation, completion receipt and audit commit together. Current
operator permissions, unchanged authored inputs/data bindings/live baseline, successful
exact evaluation, alias and canonical index/provider gates are checked before that commit.
Both legacy and snapshot releases use this entry point without changing their contracts.

Completed intent replay cannot reactivate a subsequently superseded release. Pending stale
intents are rejected before further evaluation work. Failed evaluations require a new
explicit attempt. PostgreSQL seals intent/release/evaluation pins and completed case evidence,
checks scope and completion lineage, and applies FORCE RLS. Empty-history migration reversal
is supported; protected publication history requires a forward-compatible recovery plan.
Canonical promotion and rollback share ordered organization/scenario locks with publication.
Non-key scenario locks preserve writer serialization without blocking unrelated FK inserts.

Branch process loss keeps the existing `WORKFLOW_BRANCH_RECOVERY_REQUIRED` policy. Durable
selection does not authorize automatic replay of arbitrary branch side effects.

## Compatibility, rollout and consequences

Existing rows, database defaults and the low-level compatibility factory remain
`legacy` / `legacy_pinned`. The authorized console creation service now selects snapshot /
active-generation for new scenarios and records that choice in its creation audit. Existing
scenarios can explicitly opt in for future publications with an actor-bound, expiring review
and a compare-and-swap over draft, data bindings and live baseline. This configuration change
never mutates an existing release or Run; normal evaluation/publication is still required.
The additive migrations have only been exercised in isolated test databases during this task.
Do not deploy this transition until mixed-worker, retention, rollback, performance and
integrated browser acceptance in the task have been completed.

Old binaries do not understand new revisions. Rollback must preserve compatible readers and
workers for new Runs; removing new tables or pointing old workers at new-contract work is
not a safe rollback. Existing data and old vector stores remain preserved.

The additional receipt tables deliberately exceed the conceptual table-count estimate:
foreign keys, concurrency, immutable evidence and bounded retention cannot be replaced by
an unchecked JSON identifier list. Retention must account for these protected references
and existing evidence/checkpoint references before reclaiming generations.

## Evidence

Source refresh uses the same `ScenarioPublication` receipt with exactly one origin: authored
draft or durable source job. Its evaluation pins the exact prepared generation and unchanged
data generations, through immutable EvalRun/Run foreign keys. Only those runs may read a
promotable generation; normal consumer grants and live revocation checks still apply. Every
approved target must pass before one transaction selects the index and all replacement
releases. Current approval, baseline, bindings and preparation policy are rechecked under
ordered organization/scenario/data-set locks. Provider work occurs outside that transaction.
Failure leaves live pointers intact, and replay reuses completed evaluation evidence.
Prepared passing evidence cannot open ordinary promotion until its pinned generations are
actually serving. The legacy index-before-evaluation automatic path now fails closed when
no shared source-job receipt exists.

Security, concurrency, non-owner PostgreSQL, HTTP, branch, agent, evaluation, compatibility
and known incomplete acceptance evidence are maintained in the single
[task verification record](../tasks/Agent_Hub_MD/plan.md). This ADR records the decision;
it does not claim that the complete product transition or deployment has finished.
