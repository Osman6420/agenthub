# Shared vector storage transition

Status: additive implementation under
[Agent_Hub_MD](../tasks/Agent_Hub_MD/plan.md); not yet the deployment default.
The task owns acceptance criteria and current verification evidence.

## Deployment boundary

Apply the current migration graph with the migration-owner connection; shared
storage starts at ingestion 0017 and its later integrity/retention guards are required.
PostgreSQL requires pgvector >= 0.8.0. Reapply the reviewed
[runtime grant template](../../deploy/postgres/provision-app-role.sql) in staging,
then check FORCE RLS and non-owner role readiness. The template gives shared
vectors SELECT/INSERT and trigger-guarded DELETE, without UPDATE or DDL ownership.

`INGESTION_VECTOR_STORAGE_LAYOUT=legacy` remains the default. `shared_v1` selects
the common table for new source and managed-document builds. Unknown values fail
closed. All workers and web must agree on layout; the current ingestion contract
includes it in the safe configuration fingerprint and binds generations to the
durable job attempt. Drain older workers and
messages before any shared writer cutover. Follow the canonical local/runtime
health procedure rather than relying on this document for running-process state.

Do not switch the deployment default until the task's migration, worker fencing,
retention, workload, role and UI acceptance criteria are verified.

## Bounded backfill

Use a migration-owner database connection and an approved, drained maintenance
window. This command cannot use the non-owner runtime connection. Select exact
organization and generation IDs from the reviewed inventory; do not derive tenant
authority from a request or an endpoint parameter.

Preview (no chunk or layout mutation):

```text
python manage.py backfill_shared_vectors <index-id> --organization-id <org-id> --actor <operator-ref>
```

Add `--apply` to copy at most 1000 rows (`--batch-size` accepts 1–1000). A report
contains only IDs, counts, verification/switch booleans and a checksum. Repeat
while `remaining` is positive. A crash or failed audit rolls back the current
batch; earlier verified batches remain and are not duplicated on retry. Missing,
busy, unsupported, incomplete or inconsistent sources fail with a stable code.

The final batch checks source count and exact identity/content/vector equality,
then atomically marks the generation shared/sealed and records the audit receipt.
The command preserves the old table/ORM rows and performs no re-embedding.
Repeated completed runs compare again and do not recopy. A mismatch is a stop
condition; never delete existing target rows to make the check pass.

Existing document/generation IDs and citation pointers stay unchanged. Live grant
revocation and tombstones still apply. Reverting to a binary without shared readers
after new shared writes is not a supported rollback; retain compatible readers
and use a reviewed forward fix until reverse-copy compatibility is proven.

## Operations and remaining work

Open generations are not serving-ready. Successful builds seal before promotion.
Failed build cleanup sets a terminal fence then deletes at most 1000 rows per
batch; retries resume safely. Referenced generations stay retained to protect historical
citations and evaluation evidence. Migration 0039 adds owner-only maintenance for sealed
shared generations unchanged for at least 90 days, with no serving, release, evaluation,
Run, selected-set, derived-generation, source-preparation or active-build references.
Before final shared-only cutover, invoke the reviewed grant template with the psql
variable `legacy_vector_ddl=false`; its default remains `true` for legacy writers.
After draining legacy writers and reviewing the generation inventory, verify with
`python manage.py check_tenant_rls --shared-vectors-only`. This rejects direct or
inherited/SET ROLE access to legacy provisioning/drop functions and schema CREATE.
Changing grants on a running legacy deployment would break its builds; the template
option and readiness check do not perform the operational cutover automatically. Attempt
fencing rejects stale progress, completion, failure and shared writes after
cancellation/retry. Historical backfill only accepts the exact successful result
of a bound job; the owner-only conversion cannot reopen a generation.
Monitor shared-table size, vacuum/bloat, build time, recall and query
latency. Never log chunk bodies, embeddings or connection credentials.

The opt-in 20k workload is reproducible in an isolated `test_*` PostgreSQL database:
set `AGENTHUB_SHARED_VECTOR_BENCHMARK=1`, then run pytest for
`apps/ingestion/tests/test_shared_vector_workload.py` with the repository PostgreSQL
test profile. It refuses an application database. `.tmp/shared-vector-workload.json`
contains metrics only; a failed threshold is not a completed acceptance criterion.

Shared ANN reads set `plan_cache_mode=force_custom_plan` inside their transaction,
so a pooled session's generic-plan preference cannot hide the geometry-specific
partial HNSW index. The bounded build-load test is
`apps/ingestion/tests/test_shared_vector_build_load.py`, with the same opt-in flag
and isolated PostgreSQL profile. It runs actual PREPARE/EXECUTE queries while a
second connection writes another generation into the shared table. The development
sample used 2200 selected vectors and 4300 concurrent inserts per session mode:
recall@10 was 1.0, p50 7.90/8.00 ms, p95 32.96/30.15 ms, with the shared ANN index
used under both session preferences. These synthetic local measurements are not
production capacity guarantees; the task owns detailed verification evidence.

## Reference-preserving maintenance

Use the migration-owner connection and exact reviewed organization/index identifiers:

```text
python manage.py reclaim_shared_vectors <index-id> --organization-id <org-id> --actor <operator-ref>
```

Preview is the default. Adding `--apply` irreversibly deletes at most 1000 shared chunk
rows (`--batch-size` 1–1000), after the same live reference checks and an owner-checked
SQL retirement fence. The fence, current batch and audit commit atomically. Repeat the
same command while `remaining` is positive; completed replay deletes nothing. Metadata,
document rows, release/evaluation/job evidence, identifiers and legacy stores remain.
There is no scheduled sweep. Referenced history is never expired by this command merely
because it is old. A blocked report is not permission to delete its references.

Migration 0040 serializes new parent-generation references with retirement. A
derivation admitted first protects its parent; retirement committed first rejects
new derivations from that generation. Cross-organization parents are rejected.
Migration 0042 applies the same serialization to selected set indexes and question
evaluation references, and rejects a generation belonging to another set version.
Evaluation admission reloads the locked generation instead of trusting a stale
caller object. These checks preserve existing reference protection during cleanup.

Retirement history prevents migration reversal, because rollback cannot recreate deleted
vectors. Preserve compatible readers and use forward recovery. During development this
command has only been applied to disposable test data; the task tracks rollout acceptance.
