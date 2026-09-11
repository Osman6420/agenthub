# Task Plan: background-rls-entrypoint-hardening

## Status

Planned follow-up; not part of the staged-index incident implementation diff.

## Objective

Remove the remaining confirmed owner-role assumptions from background and operator entry points.
Every protected query/mutation must derive an authoritative organization, open a bounded atomic
transaction, install transaction-local tenant scope, and materialize only the data needed after the
transaction. External I/O must remain outside database transactions.

## Owned workstreams

| Priority | Component owner | Entry points | Required outcome |
| --- | --- | --- | --- |
| P0 | Ingestion | `build_document_set_index_task`, connector automation staging/promotion | Exact-scope DB phases and non-owner end-to-end tests without changing connector/release authorization |
| P0 | Workflows | `execute_unified_run_branch` post-completion convergence | Scoped branch reload/join/resume/redispatch and duplicate-delivery convergence under a non-owner role |
| P1 | Observability | retention backlog reporting and purge | Explicit bounded authorized tenant enumeration; no global owner-visible queryset assumption |
| P1 | Component command owners | ingestion, artifact, release, tool-approval, and runtime-resume commands | Shared trusted organization resolution followed by exact scoped queries; missing/wrong/cross-tenant denial tests |

## Security and operational constraints

- Do not use migration/owner roles, superuser, `BYPASSRLS`, session-wide tenant settings, or
  disabled/relaxed RLS.
- Do not infer organization authority from a client, broker body, or protected row that was queried
  before scope installation.
- Preserve existing authorization, audit, retry, idempotency, cancellation, and data-retention
  contracts.
- Add PostgreSQL `NOSUPERUSER NOBYPASSRLS` integration gates for each workstream; SQLite/owner
  suites are supporting evidence only.

## Acceptance criteria

1. Every listed entry point has a documented trusted tenant source and transaction/external-I/O
   boundary.
2. Same-tenant success plus empty, wrong, and cross-tenant denial pass under FORCE RLS as the real
   non-owner role.
3. Duplicate/retry/reconciliation behavior remains convergent and content-free operational errors
   remain stable.
4. Each workstream ships as a separately reviewable diff with its own threat model and verification
   evidence.

## Source finding

The confirmed paths and evidence are recorded in
`docs/tasks/staged-index-worker-rls-scope-fix/verification.md` under “Repository-wide same-pattern
audit (2026-08-31)”.
