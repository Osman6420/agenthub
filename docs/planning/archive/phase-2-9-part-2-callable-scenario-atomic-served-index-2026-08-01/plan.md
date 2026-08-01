# Task Plan: phase-2-9-part-2-callable-scenario-atomic-served-index

## Task summary

Complete Phase 2.9 Part 2 with explicit exact-scope scenario activate/disable transitions and one
transactional served-index promotion/rollback operation that owns document-set-version state,
`built_index_version`, and index state.

## Background

The role/UI audit found that console-created scenarios remain `draft`, so gateway binding resolution
denies them even after release promotion. Existing staged-index promotion marks only an
`IndexVersion` active, while retrieval resolves an `active` `DocumentSetVersion` and its
`built_index_version`; therefore the promoted index is not served.

## Scope

- Add governed scenario activate/disable services and contextual console actions.
- Require exact `scenario.release` authority and readiness (active release plus active alias).
- Keep activation separate and explicit after release promotion; never activate implicitly.
- Make served-index promotion/rollback atomic, idempotent, reconcilable, and audited.
- Add one-active-version/index database invariants with a safe legacy-state preparation migration.
- Add allow/deny, concurrency, failure, migration, gateway, retrieval, and browser evidence.

## Non-goals

- No production access/reset, new dependency, secret/egress change, or public API contract change.
- No automatic activation from release promotion, publish, build, sync, or evaluation.
- No Part 3 release/runtime control-surface expansion.

## Acceptance criteria

- An exact release manager can activate a ready scenario and disable it; consumers are admitted only
  while it is active.
- Blocked/replayed scenario transitions are safe and audited without sensitive content.
- Index promotion atomically activates and links the candidate set-version/index pair and
  supersedes the prior served pair.
- Retry is idempotent, rollback restores the prior pair, and injected failures preserve prior state.
- Same-tenant cross-scope, foreign, unassigned, inactive, and neighboring-role POSTs are denied.
- Applicable SQLite/PostgreSQL/static/browser gates pass with recorded evidence.

## Affected components

`apps/catalog`, `apps/identity`, `apps/ingestion`, `apps/documents`, `apps/console`, existing gateway
admission, migrations, tests, architecture/security/user documentation, and planning records.

## Interfaces affected

Add authenticated CSRF-protected console POST routes for scenario activation/disable. Preserve public
gateway, MCP, and retrieval contracts. Preserve lifecycle Python names where practical while
correcting them to served-pointer semantics.

## Data impact

Scenario status moves explicitly among `draft`, `active`, and `disabled`. Index transitions change
only lifecycle metadata/FK pointers; immutable vector stores and snapshots are not copied or rebuilt.
The additive migration repairs split metadata deterministically and deletes no rows/stores.

## Security impact

The browser remains non-authoritative. Trusted exact objects, tenant lineage, readiness, and
responsibility are resolved server-side. Audit contains stable IDs/reasons only.

## Authorization impact

The user explicitly approved Part 2 implementation on 2026-08-01. Scenario lifecycle uses existing
exact `scenario.release`; index lifecycle uses existing exact `document_set.operations.manage`. No
grant is broadened.

## Observability impact

Emit stable allow/deny/replay events. Successful transition audit is fail-closed in the same database
transaction as state changes.

## Migration impact

Add conditional uniqueness for active document-set versions per set and active document-set-scoped
indexes per set-version. Forward preparation preserves the newest coherent pair and supersedes other
active metadata; reverse removes constraints without fabricating prior split state.

## Dependencies

Phase 2.9 Part 1, ADR-0003 immutable index stores/pointer flip, and ADR-0015 exact responsibilities.

## Implementation steps

1. Record plan/threat model and inspect symbols, references, migrations, tests, and runtime rules.
2. Implement/test exact scenario lifecycle, routes, UI, concurrency, audit, and gateway callability.
3. Implement/test transactional served-index promotion/rollback, migration, console integration,
   idempotency/reconciliation, and failure rollback.
4. Update durable/current-behavior docs and Phase 2.9/master-plan status.
5. Run SQLite/PostgreSQL/frontend/static/browser gates, complete staff/AppSec/SRE diff review,
   archive the verified task, and commit before continuing to Part 3.

## Test plan

Service and console tests cover readiness, allow/deny, tenant/lineage, retry, reconciliation,
concurrency, rollback, audit redaction/failure, gateway callability, retrieval target, and migration.
Run targeted/full applicable SQLite and PostgreSQL suites plus the manual browser journey.

## Rollout plan

Apply the additive migration, deploy application/worker code together, then verify migrations,
liveness, exact allow/deny transitions, and synthetic call/retrieval. Deploy performs no transition.

## Rollback plan

Use scenario disable and served-index rollback for behavior rollback. Remove additive constraints
only after confirming no duplicate active metadata; preserve immutable stores and releases.

## Risks

Incomplete locking can create split state; legacy split rows can be ambiguous; audit failure can
orphan evidence; UI visibility can be mistaken for authority. Deterministic locking, constraints,
fail-closed reconciliation/audit, and direct POST tests mitigate these risks.

## Open questions

None. Scenario activation remains a separate explicit command; release promotion never activates it.

## Status

Implemented and verified 2026-08-01. See `verification.md`; the task is archived under the Phase
2.9 Part 2 completion-date directory.

## Completion criteria

All acceptance/security criteria are verified, current behavior and durable decisions documented,
migration/rollback evidence recorded, task archived, and Part 3 made active.
