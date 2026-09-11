# Verification — P2.6.10 ingestion activation closure

## Status

**Verified.** Static gates, focused SQLite and PostgreSQL/FORCE-RLS tests, canonical preflight
readiness, one real-service synthetic durable build, and the worker-absence/restart, duplicate/
redelivery and reconciliation drills all passed on the exact Phase 2.6 integration commit below.
No P2.6.10 code defect was found; no index or release was promoted; no authorization, public API,
deployment role or dependency was changed. The only tracked change on this branch is this file.

## Exact commit and environment

- Branch: `codex/p2-6-10-ingestion-activation`, created from and identical to integration head
  `feat/foundation-sprint-0-1` @ `7f18a268bbde5ca4fa62b503d4c33bf79b94d9c8`
  (`docs(phase-2-6): plan activation closure wave`).
- Ancestry confirmed: P2.6.4 recovery merge `b3f641d` and P2.6.10 lifecycle merge `fd49568`
  (`fe45549 feat: add durable ingestion job lifecycle`) are ancestors of the base commit.
- Interpreter: repository `.venv` Python 3.13.14 (Windows 11).
- Canonical Compose infrastructure (`deploy/compose/docker-compose.yml`), queried live:
  `agenthub-postgres-1` (pgvector/pg16) healthy, `agenthub-redis-1` (redis:7) healthy,
  `agenthub-minio-1` healthy. Host env matched the manual-guide contract
  (`DATABASE_URL` localhost:5432, `REDIS_URL` localhost:6379/0,
  `OBJECT_STORE_ENDPOINT` http://localhost:9000, bucket `agenthub`, `minioadmin` MinIO creds,
  `AGENTHUB_SERVICE_REVISION=development`).
- **Shared-repo note.** Closure ran in the shared primary working directory. A separate parallel
  session (`codex/p2-6-7-mcp-catalog-sync`) checked out its branch and committed `42e90a3` in the
  same tree during the drills. `git diff 7f18a26..42e90a3` is confined to `apps/tools/*` and that
  task's own docs — **no `apps/ingestion`, `apps/console` or migration overlap** — so the ingestion
  code exercised is byte-identical to integration head. To avoid disturbing that session, this
  branch was committed from a dedicated sibling worktree (`../agenthub-p2-6-10`); the other
  session's web/runtime processes were left running.

## Process ownership

- Before: another session's web (`runserver 127.0.0.1:8000`) and runtime worker (`-Q runtime,default`)
  were running; one **idle** ingestion worker (started ~19 h earlier, heartbeat 19 h stale, main-tree
  `.venv`, no `.worktrees` path) and no beat.
- The stale idle ingestion worker was stopped so exactly one integration-head consumer existed for
  the drills. The other session's web and runtime worker were **not** touched.
- After (final live state): one integration-head ingestion worker + one beat/reconciler under this
  closure's ownership; the other session's runtime worker and web (`/v1/health/live` → `{"status":"ok"}`)
  still running and untouched.

## Static gate (all pass)

| Check | Result |
| --- | --- |
| `ruff format --check apps` | 383 files already formatted |
| `ruff check apps` | All checks passed |
| `mypy apps` | exit 0 (no issues) |
| `manage.py check` (test settings) | 0 issues |
| `manage.py makemigrations --check --dry-run` (test settings) | No changes detected |
| `compileall apps config` | ok |

## Focused tests

- **SQLite** (`config.settings.test`, `apps/ingestion/tests/test_job_lifecycle.py` +
  `test_staged_build.py`): **11 passed, 10 skipped** (skips are the PostgreSQL/pgvector-only cases).
- **PostgreSQL/pgvector/FORCE-RLS** (`config.settings.local`, Compose postgres, `--create-db`,
  `test_job_lifecycle.py`): **12 passed**, covering durable-idempotent request + immutable checksum,
  claim/redelivery/progress/cancel terminality, late-result-cannot-resurrect-cancelled, ambiguous →
  `reconciliation_required`, broker-publish-failure retains durable pending intent, reconciler links
  the exact promotable result after a lost final update, stale/config-drift heartbeat rejection,
  attempt/active-duplicate constraints, bounded metric labels, heartbeat persists no endpoint/secret,
  the PostgreSQL **partial-unique** concurrency backstop, and **non-owner FORCE-RLS** denial
  (`app.tenant_scope` empty→0, other-tenant→0, owner-tenant→1; `relrowsecurity`/`relforcerowsecurity`
  both true on `ingestion_stagedindexbuildjob` and `ingestion_stagedindexbuildoutbox`).

## Migrations (no reset)

- `ingestion` migrations `0001`–`0011` all applied; `migrate ingestion` and `migrate documents`
  report **No migrations to apply**. No drift in the P2.6.10 scope; the database was not reset and no
  evidence was deleted.
- Two **pre-existing, out-of-scope** shared-DB conditions were observed and left unchanged (not
  P2.6.10 defects, not fixed here): (a) `workflows` `0005`–`0008` are unrecorded in this shared local
  DB while `workflows_workflowwait` already exists — a parallel-branch migration artifact, so a
  full `migrate` errors in the unrelated `workflows` app; (b) `tools 0004` is a cosmetic
  auto-index-rename that surfaces only under PostgreSQL index naming. Both exist on the base commit
  independent of this work; the canonical `config.settings.test` drift gate is clean.

## Canonical preflight readiness (`check_ingestion_preflight`)

- No compatible/fresh worker (stale 19 h heartbeats present): plain preflight →
  `ingestion_preflight=ok contract=1 config=21054045… compatible_worker=no`; `--require-worker` →
  `CommandError: COMPATIBLE_WORKER_UNAVAILABLE`. **A live-but-stale heartbeat and a reachable broker
  do not count as ready.**
- After a compatible integration-head worker heartbeat: `--require-worker` →
  `ingestion_preflight=ok contract=1 config=21054045… compatible_worker=yes`.
- Output carries only contract revision, a 12-char non-secret config fingerprint and coarse
  compatibility — no endpoint or credential.

## Real-service synthetic durable build (Redis + Celery + MinIO + pgvector)

Synthetic `.txt` uploaded through the authenticated console MinIO-backed bulk-upload view on the
seeded `demo` tenant; deterministic 64-dim embedder (no egress); durable path via
`create_build_job`. **No promotion and no release were performed.**

- Job `cd0ac864-…` created: durable job **and** outbox committed and published (checksum-matched)
  **before** broker execution; `index_count_at_request=0` — request/outbox precede execution.
- Convergence through claim→build: `queued → running → succeeded` (revision `1→3`, `attempt=1`,
  `documents_completed=1`, `chunks_completed=1`); result `IndexVersion` **`promotable`**,
  `store_ready=true`. Left promotable and **not active** — **no automatic promotion**, no release
  change.

## Failure and recovery drills

- **Worker absence.** With no ingestion consumer, the accepted job stayed `queued` (attempt 0, no
  claim, no index) across repeated polls — visible and recoverable; the message sat unconsumed in
  Redis. Broker acceptance was never execution.
- **Compatible worker converges.** Starting one integration-head worker consumed the already-queued
  message and drove the job to `succeeded` with a single promotable index.
- **Duplicate / redelivery.** Re-publishing the same job task returned `already_converged` (0.06 s);
  job unchanged (`attempt=1`, `revision=3`) and the index count stayed **1** — no duplicate index.
- **Worker loss + restart.** Worker stopped; a fresh job `a88acfd5-…` stayed `queued`/no-index while
  down; after restart the new worker converged it exactly once (`attempt=1`, one promotable index).
- **Periodic reconciler.** Beat scheduled `reconcile_staged_index_build_jobs`, which ran live and
  bounded (returned 0). The lost-final-update linking, ambiguous→`reconciliation_required`,
  broker-failure/outbox-replay, late-result-idempotency, max-attempt and active-duplicate branches
  are proven by the 12 PostgreSQL unit tests on this same engine (see Focused tests).

## Audit, redaction and metrics

- Audit events for both jobs: `ingestion.staged_index.job_requested` (user/`admin`) and
  `ingestion.staged_index.job_succeeded` (system/`ingestion-worker`), `outcome=success`,
  `resource_type=staged_index_build_job`, opaque `public_id` references, empty `reason`.
- Redaction scan over every job row, every outbox row and all audit payloads: **all clean** — no
  document text marker, object-store endpoint/host, credentials, filename, or raw traceback.
- Metric labels bounded (live introspection + unit test): `INGESTION_BUILD_JOBS`→`(status,
  failure_class)`, `INGESTION_RECONCILIATIONS`→`(outcome)`; no tenant/job/document/worker labels.

## Checks not run / limitations

- A live worker kill **exactly between provider commit and final job update** is timing-sensitive on
  a sub-second deterministic build; the lost-final-update and worker-stale reconciliation paths are
  covered by the real-PostgreSQL unit tests rather than a live mid-build kill.
- The live `/metrics` HTTP endpoint was not scraped — the running web belongs to another session and
  was not restarted; metric-label bounds are proven by unit test and live label introspection.
- No production provider/egress, no query against the new index (authority was intentionally not
  widened: the smoke did not promote the index or create a release), and no database reset.

## Residual risks

- Local Windows/Compose does not prove production scheduler, network policy, secret manager or
  large-scale queue behavior; environment owners must still tune heartbeat retention, alert
  thresholds and reconciler sharding before production activation (per threat model).
- The shared local DB carries the pre-existing, out-of-scope `workflows`/`tools` migration
  conditions noted above; they are unrelated to P2.6.10 and were deliberately left unchanged.

## Final-diff / staff–security–SRE review

Reviewed as staff engineer, application-security engineer and SRE: the only tracked change is this
verification record; no code, schema, authorization, contract, dependency or deployment role was
modified. ADR-0012's contract (PostgreSQL-authoritative job/outbox, delivery-only broker, compatible-
worker readiness, promotable-only result, manual reconciliation for ambiguous outcomes) held under
every executed drill.
