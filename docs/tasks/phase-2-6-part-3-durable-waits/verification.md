# Verification: P2.6.3 Durable Waits

## Status and environment

Verified on 2026-07-17 from branch `phase-2-6/p2-6-3-durable-waits`, based directly on
`c4d47b1`. The host `.venv` could not start because of the documented Windows Store launcher
`A specified logon session does not exist` failure. Per `docs/manual-testing-guide.md` §0.1, checks
ran in disposable `python:3.13-slim` containers with the unchanged project dependencies. Compose
PostgreSQL 16/pgvector, Redis 7 and MinIO were healthy; no application worker was running.

## Acceptance evidence

| Area | Evidence | Result |
| --- | --- | --- |
| Compiler contracts | exact-key/schema/role/TTL tests; compiled contract v3 | Passed |
| Forgery, expiry, replay, tenant/consumer and role denial | `apps/workflows/tests/test_waits.py` | Passed |
| Separation of duties and escalation | membership-derived role, self-decision denial, one-stage durable escalation | Passed |
| Explicit payload schema/protected state | additional-properties denial and P2.6.1 output mapping | Passed |
| Duplicate delivery, cancellation/deadline race | row-locked one-time resume and idempotent reconciler tests | Passed |
| Restart/recovery and durable timers | PostgreSQL-authoritative checkpoint + bounded reconciliation tests | Passed |
| Audit completeness/redaction | success/denial audit and correlation/payload non-disclosure assertions | Passed |
| Tenant database isolation | migration FORCE RLS + app-role provisioning inventory | Passed |

## Commands and results

- `ruff format --check .` — 386 files already formatted.
- `ruff check .` — passed.
- `mypy apps` — passed, 372 source files.
- `python manage.py check` — passed, 0 issues.
- `python manage.py makemigrations --check --dry-run` — passed, no changes.
- `python -m compileall apps config` — passed.
- SQLite focused package: workflow waits/compiler/runtime and existing tool approval console —
  35 passed.
- SQLite RLS/wait package — 13 passed, 2 PostgreSQL-only branches skipped.
- Full SQLite suite — 825 collected; **794 passed, 31 PostgreSQL-only skipped**.
- PostgreSQL local profile against a unique temporary test database: wait + RLS readiness —
  **13 passed, 2 inverse non-PostgreSQL branches skipped**.
- Earlier PostgreSQL workflow wait/runtime run after applying `workflows.0004` — **13 passed**.

Migration `workflows/0004_workflowwait_durable_wait_statuses.py` applied successfully to the named
local development database and to clean temporary PostgreSQL test databases. The clean migration
creates and FORCE-enables the canonical tenant policy for `workflows_workflowwait`.

## Architecture, security and SRE review

- Architecture: one typed tenant-owned record and one transactional transition service extend the
  existing runtime. No P2.6.2 branch or P2.6.5 child-run model changed. Compiler/checkpoint version
  is bumped to v3 so stale graphs fail closed.
- Security: event correlation is an opaque non-authorizing UUID disclosed only on the exact
  consumer-owned run status; lookup uses its SHA-256 hash. Resume also requires active bearer
  authentication, exact consumer/tenant ownership, pending state, immutable lineage, expiry and
  exact schema. Human roles come only from server membership. Correlation and raw payload are absent
  from audit/log metadata.
- SRE: Celery beat invokes a bounded, skip-locked reconciler; workers never sleep. PostgreSQL is
  authority, redelivery is idempotent and terminal/cancelled runs cannot be resurrected.

## Gaps and residual risk

- A live Celery worker/beat restart smoke was not run. Redis health and task wiring were inspected,
  while restart behavior was proven through PostgreSQL checkpoint/reconciler tests. Integration
  should run a real worker/beat restart smoke after merging shared schedule changes.
- The local development database had already recorded migration 0004 before FORCE-RLS operations
  were added during review; clean databases are correct and verified. Recreate/forward-fix that
  disposable local database before using it for app-role readiness; no reset was performed here.
- Event producer identity remains the existing consumer bearer model. OIDC/mTLS or separately
  delegated producer credentials are later hardening.
- Retention/purge policy and product-level wait dashboards remain P2.6.11 integration work.
