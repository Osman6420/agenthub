# Verification: phase-2-6-part-2-parallel-join

## Status

Implemented and repository-verified on `phase-2-6/p2-6-2-parallel-join` from `c4d47b1`.
Integration acceptance and a real multi-process Celery crash smoke remain open.

## Contract and design evidence

- P2.6.0 ADR-0008/0010 and target corpus inspected; the merged P2.6.1 mapping seam was reused.
- Decisions/threat model were updated before code: workflow-specific durable intent, hard caps, no
  nested regions, deterministic early-close/cancellation/late-result policy.
- Contract is `agenthub/compiled-workflow/v3` / `workflow-compiler/v3`; stale checkpoints fail closed.
- No implicit last-writer-wins: branch writes are namespace-owned and join merge is explicit,
  conflict-checked and applied in compiled branch/item order.

## Migration and tenant isolation

- Additive migration: `workflows.0004_workflowbranch_workflowjoin`.
- Both tables carry direct organization, run/checksum/version lineage, unique identities, attempt
  constraints and bounded operational indexes.
- PostgreSQL enables and forces canonical tenant RLS; runtime-role SQL grants required access only.
- Every open/claim/complete/cancel/reconcile operation installs tenant context inside its transaction
  and re-resolves organization plus row locator. Wrong-tenant coverage resolves no row.

## Verification results

- `ruff format --check .`: 387 files formatted; `ruff check .`: passed.
- `python -m mypy .`: passed, 387 source files.
- `manage.py check`: passed; migration drift: no changes detected.
- Full SQLite: `797 passed, 31 skipped` (PostgreSQL-only), 33.25s.
- Focused PostgreSQL workflow/RLS/context with `--create-db`: `107 passed, 3 skipped`, 24.16s.
- Workflow focused: `97 passed`; compiler/mapping/transition focused: `73 passed`.
- Before PostgreSQL verification, canonical Compose PostgreSQL/Redis/MinIO were healthy and
  `/v1/health/live` returned HTTP 200.

Coverage includes deterministic reverse completion, duplicate/late delivery, terminal cancellation,
wrong-tenant substitution, namespace escape, merge conflict, invalid policy and fan-out bounds.

## Integration-owned shared-file changes

- Shared compiler/runtime/tasks/services/models receive additive v3 primitive hooks.
- Existing compiler test updates only the compiled contract version expectation.
- Provisioning SQL, architecture guide and Phase 2.6 plan add the new tables/contract evidence.

Likely merge conflicts: compiler version/constants and node/edge validation; runtime dispatch/resume;
task exception/dispatch handling; workflow models/migration number; provisioning SQL; Phase plan and
architecture guide. Resolve against integration HEAD; never retain two contract versions or two
different `0004` workflow migrations.

## Staff engineer, AppSec and SRE review

- Staff: immutable topology, stable identities/order and additive shared hooks; no P2.6.1 mapping or
  P2.6.3/P2.6.5 model changed.
- AppSec: deny-by-default mapping roots remain authoritative; broker data is locator-only; tenant
  context/FORCE RLS and terminal/closed-join guards fail closed.
- SRE: PostgreSQL is intent authority; after-commit dispatch avoids ghost work; pending work is
  bounded/reconcilable; attempts/state/fan-out are capped; early closure cancels residual work.

## Checks not run and remaining risks

- A separate Celery worker kill/restart and Redis broker-redelivery smoke was not run. Eager
  task/transition tests cover idempotency guards, not process-loss timing.
- No load/soak or lock-contention benchmark was run; monitor queue depth, join age and lock waits.
- S04 was the contract reference, but full release/eval activation remains P2.6.11/integration-owned.
  Keep production activation disabled until that pack and real Celery recovery smoke pass.
