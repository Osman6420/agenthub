# Phase 2.6 P2.6.10 — Ingestion operational lifecycle plan

## Status and authority

**Implemented and verified on branch `phase-2-6/p2-6-10-ingestion-lifecycle`.** Implementation was
authorized by the P2.6.10 owner request on 2026-07-16 and remains pending ordered integration.
The change remains additive, preserves existing authorization predicates and promotion authority,
does not change workflow grammar or public health/readiness contracts, and adds no production
dependency or deployment role.
This plan follows the [Phase 2.6 plan](../../planning/phase-2-6-plan.md#p2610--durable-ingestion-job-lifecycle-and-workerconfig-readiness)
and the [2026-07-16 local ingestion smoke](../local-document-ingestion-smoke-2026-07-16/verification.md).

## Current-state analysis

- Console dispatches `build_document_set_index_task` to `ingestion` and confirms broker acceptance.
  That does not prove a compatible consumer exists.
- No durable staged-build request exists. `IndexVersion(BUILDING)` is created inside the worker, so
  an unclaimed task has no domain state or progress. Connector runs already provide a useful durable
  queued/running/retry/terminal precedent.
- `/v1/health/live` is process liveness; `/v1/health/ready` covers database, migrations and Redis,
  not queue consumption or compatible object-store/runtime configuration.
- Compose defines `worker-ingestion` and shared object-store variables. The host-mode guide starts
  only `runtime,default` and lacks an equivalent object-store environment contract.
- Promotion is deliberately separate and authorization-sensitive; this plan preserves it.

## Target design

### Accepted implementation decisions

- PostgreSQL is authoritative for jobs, ingestion-specific dispatch outbox intents and worker
  heartbeats. Redis/Celery remains delivery only.
- The lifecycle names are the canonical states below. Terminal evidence is retained; converged
  outbox rows retain only identifier/checksum metadata and no content.
- Worker compatibility uses a bounded contract revision plus a non-secret configuration
  fingerprint. Public `/v1/health/ready` remains unchanged; tenant console state is coarse and
  platform diagnostics use management/preflight commands.
- Retry is limited to pre-claim dispatch and locally proven idempotent build failure classes.
  Provider/OCR outcome ambiguity enters `reconciliation_required` and is never blindly retried.
- Existing scenario-author build/cancel/retry and release-manager promotion predicates remain the
  authorization authority. This part introduces no new role or permission.
- Default bounds are three attempts, 30-second worker-heartbeat TTL, five-minute claim timeout,
  five-minute running-heartbeat timeout and 100-row reconciliation batches; all are validated
  settings and may be tightened operationally without changing persisted lineage.

### Durable job and dispatch

Add a direct-organization-owned `StagedIndexBuildJob` (final name during model review) before
dispatch. It stores an opaque ID, set/profile lineage, pipeline/request checksum, state,
attempt/max-attempts, bounded counters, dispatch/claim/heartbeat/finish timestamps, allowlisted error
code and nullable result `IndexVersion`. It never stores document content, endpoints, credentials or
raw provider errors.

Canonical server transitions are:

`dispatch_pending → queued → running → succeeded`

with controlled transitions to `retry_wait`, `failed`, `cancelled` or
`reconciliation_required`. Delay/stall is derived from age and heartbeat until reconciliation proves
an outcome. A job and outbox intent commit together; a bounded dispatcher publishes idempotently.
Celery receives opaque IDs only and reloads/re-authorizes authoritative records on transactional
claim. A partial unique constraint prevents concurrent active builds for the same organization,
set version, profiles and pipeline fingerprint. At-least-once delivery must converge.

### Worker/config readiness

Workers publish bounded role heartbeats containing opaque instance ID, queue role, service/image
revision, supported contract and non-secret configuration fingerprint. The fingerprint may cover
settings schema and normalized broker/object-store identity, never keys/tokens. A recent compatible
consumer is ready; stale/mismatched workers do not count; multiple compatible consumers are healthy.

Keep public liveness/readiness coarse. Add authenticated platform-operator component readiness,
worker-local probes and metrics. Tenant UI receives an actionable aggregate, never hostnames, PIDs,
topology, endpoints or credential details. Web query readiness must not fail only because ingestion
is degraded.

Compose and host mode use one environment contract and preflight. Web, runtime and ingestion roles
must agree on code/contract revision, broker and non-secret object-store identity. Credential
presence/usability may be checked without logging or fingerprinting values.

### Progress, reconciliation and recovery

Progress updates are monotonic bounded document/chunk counters; correctness never depends on an
exact percentage. A periodic bounded reconciler:

- republishes pending outbox intents;
- detects old unclaimed jobs and missing compatible workers;
- locks stale running jobs into reconciliation;
- links an exact promotable index committed before a lost final job update;
- retries only proven idempotent stages within caps;
- treats ambiguous OCR/embedding/provider outcomes as reconciliation-required, never blind retry;
- limits scan batch/frequency and alerts on backlog/age thresholds.

### Console and authorization

Document-set and Scenario Studio views show Turkish-first durable status, timestamps, monotonic
progress, safe reason and next action. Polling backs off, stops at terminal state and offers manual
refresh. It distinguishes “request recorded,” “queued/no compatible worker,” “running,” “retry
waiting,” “promotable,” “failed,” and “outcome needs reconciliation.”

Existing scenario-author predicates govern permitted build/retry/cancel actions and are rechecked
server-side; any predicate change needs owner approval. Platform diagnostics stay operator-only.
Every tenant query/action has direct organization scope and PostgreSQL FORCE RLS where applicable.
Build success never grants release promotion authority.

## Delivery increments and parallel lanes

1. [x] Contract/ADR: lifecycle, timeouts, outbox, retry classes, readiness exposure.
2. [x] Data/dispatch: additive models, constraints, outbox, transactional creation/claim.
3. [x] Worker/reconciliation: heartbeat, progress, recovery, bounded periodic task.
4. [x] Operations: Compose/host contract, preflight, worker probes, metrics/alerts.
5. [x] Console: tenant-safe status/recovery after response contract freeze; server-rendered refresh
   remains the existing interaction model, so no new polling/public API contract was introduced.
6. [x] Integration: real-service smoke and restart/failure drills.

After increment 1, lanes 2–4 can run in parallel. Console can use a frozen response contract.
Shared ingestion model/task files retain one integration owner to avoid conflicting state machines.

## Security, privacy, observability and audit

- Validate every ID, lineage and transition server-side; cap jobs, attempts, polling, strings,
  counters, reconciliation batches and retention.
- Logs/audit exclude content, embeddings, secrets, raw exceptions and unnecessary filenames.
- Audit request, dispatch failure/retry, claim, retry scheduling, completion/failure,
  reconciliation, cancel/retry and authorization denial with safe references/reasons and trace ID.
- Metrics use bounded labels only: queue role, job state, compatibility and failure class. Measure
  oldest queue age, dispatch/claim latency, heartbeat age, duration and retry/reconciliation counts.
  Tenant/job/document/worker instance IDs are prohibited metric labels.

See [threat model](threat-model.md).

## Database and migration impact

Use additive forward migrations for job/outbox and, if selected, persistent heartbeats. Add partial
uniqueness, transition/check constraints and RLS together. Existing indexes remain readable and need
no destructive backfill; only new requests enter the job path. Retain terminal lineage/audit per an
approved policy and purge converged outbox payloads without deleting linked evidence.

## Verification and acceptance

- **SQLite:** lifecycle, checksum/idempotency, bounds, progress monotonicity, localization,
  authn/authz denial, polling and safe errors.
- **PostgreSQL/pgvector:** partial uniqueness, concurrent/duplicate claims, non-owner FORCE RLS,
  exact result linking, lost-final-update reconciliation and promotion separation.
- **Real services:** Redis + Celery ingestion + MinIO `.txt` upload → published set → durable job →
  promotable/active pgvector index → scenario release → authenticated `/v1/query`.
- **Failure drills:** no/broken broker, no/stale/mismatched/duplicate worker, worker kill before/after
  index commit, object-store mismatch, timeout/max attempts, web restart and stale revision.
- **Telemetry:** audit/redaction, trace correlation, bounded metric labels and alerts.

Acceptance requires: broker acceptance is never described as execution; every accepted job remains
visible/recoverable; component and web readiness are distinct; host/Compose pass equivalent
preflight; cross-tenant actions fail closed; promotion separation remains; all evidence is recorded
in [verification.md](verification.md).

## Rollout, rollback and owner decisions

Gate dispatch, readiness and UI polling independently. Deploy additive schema, then compatible
dispatcher/workers, then web/UI; canary locally. Rollback stops new dispatch but retains/reconciles
jobs/outbox/audit with the matching worker revision. Never delete evidence or restore dispatch-only
success messaging.

Before implementation, owners decide state names and thresholds/retention; shared versus
ingestion-specific outbox; PostgreSQL versus Redis heartbeat authority; provider retry versus
`outcome_unknown`; and approve any authorization, public API or deployment-topology change.
