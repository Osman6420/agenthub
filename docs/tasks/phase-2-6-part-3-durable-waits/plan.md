# Task Plan: phase-2-6-part-3-durable-waits

## Status

Implemented and verified on the P2.6.3 branch. Real Redis/Celery worker restart smoke remains an
explicit operational gap; PostgreSQL migration, FORCE RLS, recovery service and full regression are
verified in the linked record.

## Objective

Implement P2.6.3 on the `c4d47b1` integration baseline: typed `human_task`, durable `timer`, and
authenticated `event_wait` primitives that resume exactly once after restart without sleeping a
worker or accepting client-owned authority.

## Authorized scope and assumptions

- ADR-0008 and ADR-0010 are authoritative; the merged P2.6.1 mapping contract is reused.
- Existing tool approval behavior remains unchanged. Human tasks share its checksum, role, expiry,
  separation-of-duties and one-decision invariants through a workflow-specific service/model.
- Event ingress uses existing authenticated consumer bearer identity. It may resume only a wait
  owned by that exact consumer and tenant; correlation is an opaque one-time public identifier,
  never authorization by itself.
- Human decisions use server-resolved organization membership roles. Request bodies never supply
  roles, tenant, actor, release, capability or checksums.
- No P2.6.2 parallel-state or P2.6.5 child-run model is changed.

## Milestones

1. **Contracts and records** — extend the canonical compiler with bounded exact configs; add
   tenant-owned wait and human-task records, one-time correlation hash lookup, immutable checksum and
   compiler/release lineage, expiry/deadline and safe decision metadata.
2. **Transition service** — create waits atomically, validate explicit JSON Schemas, authorize
   actor/tenant/role server-side, consume once under row locks, map validated data through P2.6.1,
   audit required decisions, and make duplicate delivery/replay stable denials.
3. **Runtime and recovery** — checkpoint at wait nodes, dispatch no sleeping task, reconcile due
   deadlines in bounded batches, make cancel/timeout races terminal-safe, and resume through the
   existing Celery run-id task.
4. **Surfaces** — add a deny-by-default authenticated event-resume endpoint and tenant/role-scoped
   console human-decision action without widening invoke/status authorization.
5. **Verification and closure** — cover compiler, authn/authz, schema, replay, races, recovery and
   redaction; run repository gates plus PostgreSQL/Celery recovery where available; record evidence.

## Acceptance criteria

- `human_task`, `timer`, and `event_wait` configs reject unknown fields and enforce bounded roles,
  schemas, TTLs and timeout/escalation routes at compile time.
- Every checkpoint binds organization, run, workflow/release checksum, node and pending-action
  checksum. Resume payload cannot alter this lineage or protected state.
- Correlation IDs are random opaque UUIDs, disclosed only through the owner-scoped run status; the
  lookup uses a SHA-256 hash and correlation values are never logged or audited. They are not
  bearer authorization: exact authenticated consumer and tenant ownership is always required.
- Resume is authenticated, exact-consumer and tenant scoped, schema allowlisted, row-locked,
  expiry-aware and one-time. Forgery, replay, wrong state and cross-tenant use deny and audit.
- Human decisions derive roles from current membership, forbid self-decision when configured,
  enforce expiry and one decision, and validate the declared decision schema.
- Timers and expiries persist deadlines and are completed by a bounded reconciler; no task sleeps.
- Cancellation/timeout/resume races cannot resurrect a terminal run. Redelivery is idempotent.
- Restart recovery reconstructs execution only from PostgreSQL-authoritative checkpoints and the
  exact compiled contract version.
- No secrets or raw decision/event payload values enter logs, traces or audit metadata.

## Operational and rollback plan

- Capability remains unavailable unless a compiled workflow contains the new primitive.
- A periodic scheduler may call the bounded reconciliation task; manual invocation is safe and
  idempotent. Queue loss delays resumption but does not lose intent.
- Rollback stops new dispatch/resume traffic and uses matching code or a forward fix. Durable wait
  evidence is retained; no destructive rollback or database reset is authorized.

## Verification plan

- Focused compiler/service/runtime/gateway/console tests on SQLite.
- PostgreSQL concurrency and row-lock race tests, migration application/drift, and real Celery
  restart/recovery when local services are healthy.
- Ruff format/check, mypy, Django check, compileall, relevant pytest and full pytest.
- Final architecture, application-security and SRE diff review.
