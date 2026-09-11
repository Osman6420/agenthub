# Verification — Phase 2.6 ingestion operational lifecycle

## Result

P2.6.10 is implemented and verified on branch
`phase-2-6/p2-6-10-ingestion-lifecycle`, based exactly on commit `88fc203`, and integrated through
merge commit `fd49568`. Combined evidence is recorded in the
[first-wave integration verification](../phase-2-6-wave-1-integration/verification.md). The
implementation adds no dependency, changes no workflow grammar/public readiness
contract/deployment role, performs no database reset and makes no live provider call.

## Implemented contract

- PostgreSQL-authoritative tenant-owned staged-index job plus direct-tenant outbox, immutable
  checksum/pipeline lineage, bounded counters/attempts and additive constraints.
- Transactional request + outbox creation, identifier-only Celery body, tenant header revalidation,
  row-locked idempotent claim, redelivery and terminal/late-result protection.
- Bounded dispatcher/reconciler for broker failure, stale claims and exact promotable-index linking
  after a lost final job update. Ambiguous provider/OCR outcomes require reconciliation.
- Persistent compatible-worker heartbeat with opaque instance ID, contract/service revision and
  non-secret configuration fingerprint; public `/v1/health/ready` remains unchanged.
- Host/Compose parity inputs, `check_ingestion_preflight`, periodic Celery-beat reconciliation,
  bounded metrics/alert and Turkish-first console status/retry/cancel controls.
- Existing scenario-author predicate governs build/retry/cancel. Existing release-manager predicate
  alone governs promotion; successful jobs produce only `promotable` indexes.

## Automated evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Focused SQLite lifecycle/authz | Pass | `16 passed, 2 PostgreSQL-only skipped` |
| Focused PostgreSQL lifecycle/constraints/FORCE RLS | Pass | `12 passed` |
| Full SQLite regression | Pass | `725 passed, 31 skipped` in 36.48s |
| Full PostgreSQL/pgvector regression | Pass | Clean `--create-db`: `751 passed, 5 skipped` in 270.83s |
| Formatter | Pass | `ruff format --check .` after final formatting |
| Lint | Pass | `ruff check .` |
| Type check | Pass | `mypy .`: 379 source files, no issues |
| Django system check | Pass | `manage.py check`: no issues |
| Migration drift | Pass | `manage.py makemigrations --check --dry-run`: no changes |
| Migration apply | Pass | Local PostgreSQL applied additive `ingestion.0011...` |

The first full PostgreSQL attempt used a previously reused test database and failed after migration
tests encountered stale schema state and a connection abort. This was not counted as evidence. A
clean `--create-db` rerun passed the complete suite.

Focused coverage includes request replay/checksum lineage, partial active uniqueness, bounded
attempt constraints, monotonic progress, duplicate claim/redelivery, cancellation and late result,
broker-unavailable outbox retention, exact lost-final-update reconciliation, ambiguous outcome,
stale/config-mismatched heartbeat, secret-free heartbeat storage, bounded metric labels,
cross-tenant 404, auditor 403 and non-owner FORCE RLS denial for both job and outbox.

## Real-service and failure-drill evidence

Canonical Compose inspection reported PostgreSQL/pgvector, Redis and MinIO healthy. No Compose web
or worker service was running. Host liveness remained HTTP 200.

- Host preflight with canonical PostgreSQL/Redis/MinIO inputs: `ingestion_preflight=ok`, contract 1,
  non-secret fingerprint only; before a compatible worker, `compatible_worker=no`.
- A worktree ingestion worker consumed a real Redis reconciler task; preflight then reported
  `compatible_worker=yes`.
- First real durable build deliberately selected the deployment's incompatible 3072-dimensional
  profile while the deterministic provider produced 64 dimensions. It failed closed at attempt 1
  with `EMBEDDING_DIMENSION_MISMATCH`; no secret/raw exception was stored.
- With the tenant-granted 64-dimensional deterministic profile, existing synthetic MinIO set
  version 10 produced job `8936a68c-8de7-4591-b536-2bc25e43dbdb`, one document/one chunk and
  promotable index 8; the job converged to `succeeded` at attempt 1.
- Worker-loss/restart drill: job `80710da5-c4c0-4502-bade-15bf914b40ce` remained visible as
  `queued`, attempt 0, with published outbox while no worker ran. Restarting the worktree worker
  converged it to `succeeded`, attempt 1, promotable index 9.
- No index/release promotion, database reset, deletion, production egress or live provider call was
  performed. Synthetic smoke evidence remains in the local database by design.

## Security, privacy and telemetry evidence

- Migration applies FORCE RLS to direct-tenant job and outbox tables; PostgreSQL test uses a
  `NOSUPERUSER NOLOGIN` non-owner role and proves empty/wrong tenant denial and correct-tenant read.
- Job/outbox/audit/heartbeat exclude document bytes, filenames, endpoints, credentials and raw
  errors. Secret-presence tests prove credential values are absent from heartbeat rows.
- Metrics labels are only bounded state, failure class and reconciliation outcome. Tenant, job,
  document and worker-instance IDs are prohibited and tested. Gauges/histograms cover compatible
  worker, heartbeat age, oldest queue age, claim latency and build duration.
- Required state-changing audit writes occur inside the owning transaction. Optional metrics remain
  non-authoritative.

## Runtime/restart state

The stale pre-task ingestion worker was stopped. After the restart drill, the P2.6.10 worktree
ingestion worker remains running with launcher PID `27844`, queue `ingestion`, host-mode canonical
MinIO/Redis/PostgreSQL inputs and service revision `p2-6-10-local`. Existing web processes were not
restarted and therefore continue serving their pre-task checkout code; the public readiness
contract was not changed.

## Residual risks and merge gate

- PostgreSQL heartbeat authority adds bounded periodic writes; production retention/cleanup and
  alert thresholds require environment-owner tuning.
- The reconciler scans at most 100 organizations and 100 jobs per run. Very large installations
  must monitor oldest-queue age and shard/schedule without increasing request-path work.
- Local test/smoke credentials were environment-only defaults. Production object-store/broker
  identity and secrets remain deployment-owned.
- The first-wave integration retained ingestion migration `0011` and renumbered this decision from
  ADR `0011` to ADR `0012` because P2.6.8 had already allocated ADR `0011`. Migration drift and the
  integrated verification suite must be rerun on the merge result.
