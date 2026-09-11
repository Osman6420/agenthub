# ADR 0016: Explicit scenario callability and atomic served-index lifecycle

- **Status:** Accepted
- **Date:** 2026-08-01

## Context

Release promotion did not change `Scenario.status`, while gateway admission requires an active
scenario. Console-created scenarios therefore could not become callable without a bootstrap edit.
Staged-index promotion changed only `IndexVersion.status`; retrieval serves the active
`DocumentSetVersion.built_index_version`, so promotion could report success without changing the
retrieval target. ADR-0003 chose immutable stores and metadata pointer flips but did not identify
one current model operation as owner of every served-pointer field.

## Decision drivers

Deny-by-default callability, separation of duties, exact responsibility authorization, atomic
cutover, idempotent retry, instant rollback, auditability, and public API compatibility.

## Considered options

1. Activate scenarios implicitly with release promotion. Rejected because it couples two governed
   decisions and can expose a scenario as an unintended side effect.
2. Treat active `IndexVersion.status` alone as the retrieval pointer. Rejected because retrieval
   resolves the active set version and its exact FK.
3. Keep explicit scenario activation and make one service own every served set/index field. Chosen.

## Decision

- Release promotion and scenario activation are separate commands. Exact `scenario.release`
  authority may activate only when an active release and alias exist and every release-pinned index
  is the ready active `built_index_version` of an active set version.
- Scenario disable stops new admission without mutating the active release. Exact replay is
  idempotent. Gateway/MCP binding resolution remains the final active-scenario enforcement point.
- Served-index promotion/rollback deterministically locks the document set, versions, and indexes.
  One transaction supersedes the prior pair, activates the target `DocumentSetVersion`, assigns its
  exact `built_index_version`, activates that `IndexVersion`, and appends success audit. No store is
  copied, renamed, rebuilt, or deleted.
- Conditional constraints enforce at most one active set version per set and one active scoped index
  per set version. Legacy split metadata is reconciled before constraints; ambiguous/unready state
  becomes non-serving rather than guessed.
- Successful audit persistence is fail-closed with the state transaction. Validation and
  authorization failures are audited separately with stable content-free reasons.

## Security consequences

UI visibility grants no authority. Exact scenario/document-set responsibility and tenant lineage
remain server-derived. Implicit exposure is removed; cross-scope IDs remain denied. Audit contains
opaque IDs, status, and reasons only.

## Operational consequences

Cutover is serialized per set and performs no vector-store I/O. Exact retry is safe and rollback
uses retained immutable metadata/store. Lock contention is bounded to one set's lifecycle commands.

## Data and privacy consequences

The additive migration changes lifecycle metadata and one FK only. It deletes no document, chunk,
vector, store, release, or audit row and reads no content bytes.

## Positive consequences

UI-created scenarios become intentionally callable, retrieval immediately uses the promoted exact
index, partial success is excluded, and rollback/retry semantics are explicit.

## Negative consequences

Operators perform a separate activation after release promotion. A malformed legacy split state
may become non-serving until an authorized candidate is promoted.

## Migration impact

Add two conditional uniqueness constraints after deterministic legacy reconciliation. Reverse
removes constraints but does not recreate unsafe split metadata.

## Rollback considerations

Use scenario disable and served-index rollback first. Schema rollback must confirm no duplicate
active metadata before removing constraints. Immutable prior stores/releases remain retained.

## References

- [ADR-0003](0003-vector-storage-blue-green-per-index-version.md)
- [ADR-0015](0015-responsibility-based-operator-authorization.md)
- [Phase 2.9 Part 2 plan](../planning/archive/phase-2-9-part-2-callable-scenario-atomic-served-index-2026-08-01/plan.md)
