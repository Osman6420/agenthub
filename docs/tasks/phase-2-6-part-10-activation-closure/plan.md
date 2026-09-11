# Phase 2.6 P2.6.10 — Ingestion activation-closure plan

## Status and authority

**Planned; implementation and live drills not started.** This task closes the already implemented
P2.6.10 ingestion lifecycle on the current Phase 2.6 integration baseline. It does not redesign the
job state machine, add a deployment role, change authorization or promote an index/release. The
durable contract remains owned by [ADR 0012](../../adr/0012-durable-ingestion-build-jobs-and-worker-readiness.md)
and the [implementation plan](../phase-2-6-ingestion-operational-lifecycle/plan.md).

## Goal

Prove that the merged `feat/foundation-sprint-0-1` code—not a stale feature-worktree worker—can
accept, durably dispatch, execute, recover and expose one synthetic ingestion build using canonical
local PostgreSQL, Redis and MinIO configuration. Close only evidence or low-risk configuration/doc
gaps discovered by the drills.

## Preconditions and trust boundaries

- Follow section 0 of `docs/manual-testing-guide.md`; inspect Compose and live process state before
  starting or stopping anything.
- Use one integration-head ingestion worker and one beat/reconciler. Detect and stop stale duplicate
  ingestion workers before the smoke; do not stop unrelated processes.
- Use only the seeded local tenant and synthetic `.txt` content. No production data, provider,
  credential, endpoint or external egress is authorized.
- PostgreSQL remains job truth; Redis/Celery is delivery; MinIO holds synthetic source bytes.
- Existing scenario-author build/retry/cancel and release-manager promotion predicates remain
  unchanged. The drill must not promote an index or release.

## Execution increments

### 1. Baseline and static gate

1. Confirm P2.6.4 and P2.6.10 are ancestors of `feat/foundation-sprint-0-1` and the worktree contains
   no unrelated tracked changes.
2. Query canonical Compose health and bounded host process state.
3. Run migration drift, Django system check, Ruff, formatting and mypy.
4. Run focused SQLite and PostgreSQL ingestion lifecycle, authorization, constraint and FORCE-RLS
   tests on the integration head.

### 2. Canonical runtime readiness

1. Apply migrations without resetting the database.
2. Start or restart exactly one integration-head ingestion worker and the bounded reconciler/beat
   using the manual guide's environment contract.
3. Run `check_ingestion_preflight` before and after the compatible worker heartbeat. Record only
   contract revision, shortened non-secret fingerprint and coarse compatibility.
4. Prove stale or mismatched heartbeat evidence does not count as ready.

### 3. Real-service synthetic smoke

1. Upload a bounded synthetic `.txt` document through the existing authorized local flow.
2. Create a durable staged-index job and prove request/outbox commit precedes broker execution.
3. Observe legal monotonic transitions through claim and build to `succeeded`, with a promotable
   index and no automatic promotion.
4. Execute an authenticated retrieval/query against the explicitly selected existing release only
   if the smoke can do so without promoting the new index; otherwise record query verification as
   not applicable rather than widening authority.

### 4. Failure and recovery drills

1. With no compatible worker, prove an accepted job remains visible and recoverable as queued.
2. Restart the integration-head worker and prove that exact job converges once without duplicate
   index creation.
3. Exercise broker publish failure/outbox replay through the existing test or a bounded local outage;
   do not destructively alter Redis data.
4. Exercise worker loss before final commit and lost-final-update reconciliation after exact index
   commit. Ambiguous provider outcomes must enter `reconciliation_required`, never blind retry.
5. Confirm late delivery, duplicate claim, cancellation and max-attempt boundaries remain terminally
   idempotent.

### 5. Evidence and closure

1. Verify safe audit events, trace correlation and bounded metric labels. Search persisted/logged
   evidence for document bytes, filenames, endpoints, credentials and raw exceptions.
2. Record commands, opaque IDs only where necessary, results and runtime/restart state in
   `verification.md`.
3. Update the Phase 2.6 status only after all applicable gates pass. Fix only directly discovered
   P2.6.10 defects; plan broader changes separately.

## Parallelism and ownership

This is intentionally a single short closure lane because worker/process ownership and live failure
drills share state. Static/focused test preparation may run independently, but one integration owner
must control worker restarts, job creation and verification evidence. Do not run this closure in
parallel with another session changing ingestion models, tasks, migrations or Compose roles.

## Security, authorization and privacy requirements

- Revalidate tenant lineage and action authorization server-side; cross-tenant reads/actions remain
  denied by application predicates and PostgreSQL FORCE RLS.
- Do not expose topology or credential details through tenant UI, logs, audit, metrics or evidence.
- Never interpret broker acceptance, a heartbeat or build success as release-promotion authority.
- Do not reset the database, delete retained evidence, contact a live provider or weaken retry,
  reconciliation, audit, RLS, test or readiness controls.

See [threat model](threat-model.md).

## Exit criteria

- Integration-head static, focused SQLite and PostgreSQL/RLS gates pass.
- Canonical preflight distinguishes absent/stale/mismatched and compatible workers.
- A synthetic durable job reaches a promotable index through real Redis/Celery/MinIO services.
- Worker absence/restart and duplicate/redelivery paths converge without lost work or duplicate
  index creation; ambiguous outcomes remain manual reconciliation.
- No index/release is promoted, no authorization contract changes and no sensitive content appears
  in logs, audit, heartbeat, metrics or verification evidence.
- Verification records exact integration commit, checks, skipped drills, residual risk and final
  process state.
